"""'수불요약' 시트 정제: 여러 표가 쌓인 재무 요약 보고서.

시트에는 서로 다른 표가 위아래로 놓여 있어서 블록마다 제목(앵커)을 찾아 따로 표로 만든다.

  수불마감        계정별 기초재고 / 입고 / 출고 / 기말재고
  매출지표        매출, 객수, 객단가
  로스요약        원재료·반제품 이론사용 vs 실사기준 사용
  COST비율        전달재고·입고·이달재고·COST(%)
  차이순위_*      표준 대비 실사 차이가 큰 품목 (금액기준 / 중량기준)
  폐기월계        일일 폐기 품목 월계
  실사기준_사용량  기본제공 품목의 총 사용·1인당 제공

실제 값에서 성립함을 확인한 관계(기초+입고−출고=기말, 객단가=매출÷객수, 로스금액=실사−이론, 차이=기말−실사 등)를
점검 기준으로 쓴다. 규칙으로 설명되지 않는 결측은 조용히 채우지 않고 UnhandledMissingError 로 알린다.
"""
import re

import pandas as pd

from prep.blocks import (REPORT_COLUMNS, UnhandledMissingError, ensure_no_missing, fill, find_row, flatten_header, label,
                         make_check, take_block, to_numbers)

SHEET_SUMMARY = "수불요약"
NONE_TEXT = "없음"
TOL = 0.01                                   # 금액·수량 항등식 허용 오차
MOSTLY_EMPTY = 0.5                           # 이 비율 이상 비어 있고 산식을 알 수 없으면 열을 삭제


def _need(row, what):
    if row is None:
        raise ValueError(f"{what}을(를) 찾지 못했습니다.")
    return row


def _finish(df: pd.DataFrame, table: str) -> pd.DataFrame:
    try:
        ensure_no_missing(df)
    except UnhandledMissingError as e:
        raise UnhandledMissingError(f"[{table}] {e}") from None
    return df


def _tag(rows: list[dict], table: str) -> list[dict]:
    return [{**r, "열": f"{table}.{r['열']}"} for r in rows]


def _stray(raw, start, end, from_col, who, notes, why):
    for i in range(start, end):
        for j in range(from_col, raw.shape[1]):
            if pd.notna(raw.iat[i, j]):
                notes.append(f"{who}: {raw.iat[i, 1]} 행의 {j}열 값 {raw.iat[i, j]} 은(는) {why}")


# ---------------------------------------------------------------- 수불마감
def _ledger(raw, out, report, checks, notes, dropped):
    h = _need(find_row(raw, 1, "계정명"), "수불 마감표(머리글 '계정명')")
    names = flatten_header(raw, h, last_col=11)
    start = end = h + 2
    while end < len(raw) and pd.notna(raw.iat[end, 1]):
        last = label(raw.iat[end, 1])
        end += 1
        if last == "합계":
            break
    df, d = take_block(raw, names, start, end, 11, keep=[n for n in names if n])
    dropped += [f"수불마감.{c}" for c in d]
    num = [c for c in df.columns if c != "계정명"]
    to_numbers(df, num)
    rows: list[dict] = []
    for c in num:                                          # 해당 계정에 그 항목의 거래가 없으면 빈칸 = 0
        fill(df, c, 0.0, df[c].isna(), "해당 계정에 이 항목의 거래 없음", rows)
    _finish(df, "수불마감")
    _stray(raw, start, end, 12, "수불마감", notes, "표 밖의 값이라 포함하지 않음")

    inflow = [c for c in df.columns if c.startswith("입고_")]
    outflow = [c for c in df.columns if c.startswith("출고_")]
    calc = df["기초재고"] + df[inflow].sum(axis=1) - df[outflow].sum(axis=1)
    checks.append(make_check("수불마감: 기초+입고−출고=기말 (불일치 행 수)", 0, int(((calc - df["기말재고"]).abs() > TOL).sum()), note=True))   # 2024-09 원재료 81,000원: 원본 시트 값
    total = df["계정명"].map(label) == "합계"
    if total.any():
        diff = (df[~total][num].sum() - df[total].iloc[0][num]).abs() > TOL
        checks.append(make_check("수불마감: 합계행 = 계정별 합 (불일치 열 수)", 0, int(diff.sum())))
    out["수불마감"] = df
    report += _tag(rows, "수불마감")


# ---------------------------------------------------------------- 매출지표
def _kpis(raw, out, report, checks, notes, dropped):
    r = find_row(raw, 1, "매출")
    if r is None:
        notes.append("블록 없음: 매출 지표")
        return
    rows, i = [], r
    while i < len(raw) and pd.notna(raw.iat[i, 1]) and label(raw.iat[i, 1]) in ("매출", "객수", "객단가"):
        rows.append((label(raw.iat[i, 1]), raw.iat[i, 2]))
        i += 1
    df = pd.DataFrame(rows, columns=["지표", "값"], dtype=object)
    to_numbers(df, ["값"])
    _finish(df, "매출지표")
    df["값"] = df["값"].astype(float)
    v = dict(zip(df["지표"], df["값"]))
    if {"매출", "객수", "객단가"} <= set(v) and v["객수"]:
        checks.append(make_check("객단가 = 매출 ÷ 객수", v["객단가"], v["매출"] / v["객수"]))
    out["매출지표"] = df


# ---------------------------------------------------------------- 로스요약
def _loss(raw, out, report, checks, notes, dropped):
    hr = find_row(raw, 6, "이론사용")
    if hr is None:
        notes.append("블록 없음: 로스 요약")
        return
    cols = [label(raw.iat[hr, j]) for j in range(6, 10)]
    start = end = hr + 1
    while end < len(raw) and pd.notna(raw.iat[end, 5]):
        last = label(raw.iat[end, 5])
        end += 1
        if last == "합계":
            break
    df = raw.iloc[start:end, 5:10].copy()
    df.columns = ["구분", *cols]
    df = df.reset_index(drop=True)
    df["구분"] = df["구분"].map(label)
    to_numbers(df, cols)
    _finish(df, "로스요약")
    df[cols] = df[cols].astype(float)
    theory, actual, loss, rate = (df[c] for c in cols)
    checks.append(make_check("로스요약: 로스금액 = 실사−이론 (불일치 행 수)", 0, int(((actual - theory - loss).abs() > TOL).sum()), note=True))   # 2024-03~12 원재료 소액~154,261원(04·12월 큼): 원본 시트 값
    ok_rows = actual != 0
    checks.append(make_check("로스요약: 로스율 = 로스금액 ÷ 실사기준사용 (불일치 행 수)", 0,
                             int(((loss[ok_rows] / actual[ok_rows] - rate[ok_rows]).abs() > 1e-6).sum())))
    kinds = df.set_index("구분")
    if {"원재료", "반제품", "합계"} <= set(kinds.index):
        sums = kinds.loc[["원재료", "반제품"], cols[:3]].sum()
        checks.append(make_check("로스요약: 합계 = 원재료+반제품 (불일치 열 수)", 0, int(((sums - kinds.loc["합계", cols[:3]]).abs() > TOL).sum())))
    out["로스요약"] = df


# ---------------------------------------------------------------- COST비율
def _cost(raw, out, report, checks, notes, dropped):
    hr = next((i for i in range(len(raw)) if pd.notna(raw.iat[i, 1]) and pd.notna(raw.iat[i, 2])
               and label(raw.iat[i, 1]) == "구분" and label(raw.iat[i, 2]) == "원재료"), None)
    if hr is None:
        notes.append("블록 없음: COST 비율")
        return
    cols = [label(raw.iat[hr, 2]), label(raw.iat[hr, 3])]
    rows, i = [], hr + 1
    while i < len(raw) and pd.notna(raw.iat[i, 1]):
        rows.append([str(raw.iat[i, 1]).strip(), raw.iat[i, 2], raw.iat[i, 3]])
        i += 1
    df = pd.DataFrame(rows, columns=["항목", *cols], dtype=object)
    to_numbers(df, cols)
    _finish(df, "COST비율")
    df[cols] = df[cols].astype(float)
    out["COST비율"] = df


# ---------------------------------------------------------------- 차이순위
def _rankings(raw, out, report, checks, notes, dropped):
    prefix = label("표준, 실사 차이발생 순위")
    titles = [i for i in range(len(raw)) if pd.notna(raw.iat[i, 1]) and label(raw.iat[i, 1]).startswith(prefix)]
    for t in titles:
        m = re.search(r"\(([^)]*)\)", str(raw.iat[t, 1]))
        table = f"차이순위_{m.group(1) if m else t}"
        h = _need(find_row(raw, 1, "구분", start=t), f"{table}의 머리글 행")
        names = flatten_header(raw, h, last_col=12)
        start = end = h + 2
        while end < len(raw) and pd.notna(raw.iat[end, 3]):
            end += 1
        keep = [n for n in names if n]
        df, d = take_block(raw, names, start, end, 12, keep=keep)
        dropped += [f"{table}.{c}" for c in d]
        rows: list[dict] = []
        carried = df["구분"].ffill()                                   # 병합 셀: 첫 행에만 값이 있다
        fill(df, "구분", carried, df["구분"].isna() & carried.notna(), "병합 셀의 빈칸: 위 행과 같음", rows, shown="위 행 값")
        num = [c for c in df.columns if c not in ("구분", "품목코드_RMS", "품명", "규격")]
        to_numbers(df, num)
        _finish(df, table)
        df["순위"] = df["순위"].round().astype("int64")
        df["품목코드_RMS"] = df["품목코드_RMS"].astype(str)
        extra = int(raw.iloc[start:end, 13:].notna().sum().sum())
        if extra:
            notes.append(f"{table}: 표 오른쪽의 머리글 없는 값 {extra}개는 포함하지 않음 (역로스 행의 보조 번호 등)")
        bad = 0
        for a, b, c in (("기말재고_중량_g", "실사재고_중량_g", "차이_중량_g"), ("기말재고_금액", "실사재고_금액", "차이_금액")):
            bad += int(((df[a] - df[b] - df[c]).abs() > TOL).sum())
        checks.append(make_check(f"{table}: 차이 = 기말−실사 (불일치 칸 수)", 0, bad))
        out[table] = df
        report += _tag(rows, table)


# ---------------------------------------------------------------- 폐기월계
def _disposal(raw, out, report, checks, notes, dropped):
    t = find_row(raw, 1, "일일 폐기 품목 월계")
    h = find_row(raw, 1, "품명", start=t) if t is not None else None
    if h is None:
        notes.append("블록 없음: 일일 폐기 품목 월계")
        return
    names = flatten_header(raw, h, last_col=9, overrides={9: "코드"})
    start = end = h + 2
    stop = label("타_폐기 기준")
    while end < len(raw) and pd.notna(raw.iat[end, 1]) and not label(raw.iat[end, 1]).startswith(stop):
        end += 1
    keep = [n for n in names if n]
    df, d = take_block(raw, names, start, end, 9, keep=keep)
    dropped += [f"폐기월계.{c}" for c in d]
    num = [c for c in df.columns if c not in ("품명", "코드")]
    to_numbers(df, num)
    rows: list[dict] = []
    for c in num:
        rule = "비율 산정 불가(분모 없음)라 0" if "대비" in c else "폐기 없음"
        fill(df, c, 0.0, df[c].isna(), rule, rows)
    if "코드" in df:
        fill(df, "코드", NONE_TEXT, df["코드"].isna(), "코드가 적혀 있지 않음", rows)
        df["코드"] = df["코드"].astype(str)
    _finish(df, "폐기월계")
    out["폐기월계"] = df
    report += _tag(rows, "폐기월계")


# ---------------------------------------------------------------- 실사기준_사용량
def _usage(raw, out, report, checks, notes, dropped):
    t = find_row(raw, 1, "실사 기준 사용량 품목(기본제공)")
    h = find_row(raw, 1, "코드", start=t) if t is not None else None
    if h is None:
        notes.append("블록 없음: 실사 기준 사용량 품목")
        return
    names = flatten_header(raw, h, last_col=8)
    start = end = h + 2
    while end < len(raw) and pd.notna(raw.iat[end, 2]):
        end += 1
    keep = [n for n in names if n]
    df, d = take_block(raw, names, start, end, 8, keep=keep)
    dropped += [f"실사기준_사용량.{c}" for c in d]
    num = [c for c in df.columns if c not in ("코드", "품명")]
    to_numbers(df, num)
    for c in list(num):                                        # 대부분 비어 있고 산식을 알 수 없는 열은 삭제 (값은 기록)
        if df[c].isna().mean() >= MOSTLY_EMPTY:
            vals = [f"{n}행={v}" for n, v in enumerate(df[c], 1) if pd.notna(v)]
            dropped.append(f"실사기준_사용량.{c} ({df[c].notna().sum()}/{len(df)}행만 값이 있고 산식 불명)")
            notes.append(f"실사기준_사용량.{c} 열을 삭제함. 원래 있던 값: {', '.join(vals) or '없음'}")
            df = df.drop(columns=c)
            num.remove(c)
    _finish(df, "실사기준_사용량")
    df["코드"] = df["코드"].astype(str)
    out["실사기준_사용량"] = df


def clean_summary(raw: pd.DataFrame):
    """'수불요약' 시트 -> ({표 이름: DataFrame}, 처리내역, {"dropped", "checks", "notes"})."""
    tables: dict[str, pd.DataFrame] = {}
    report: list[dict] = []
    checks: list[dict] = []
    notes: list[str] = []
    dropped: list[str] = []
    for block in (_ledger, _kpis, _loss, _cost, _rankings, _disposal, _usage):
        block(raw, tables, report, checks, notes, dropped)
    order = ["수불마감", "매출지표", "로스요약", "COST비율"]
    ranked = sorted(k for k in tables if k.startswith("차이순위_"))
    tables = {k: tables[k] for k in [*order, *ranked, "폐기월계", "실사기준_사용량"] if k in tables}
    return tables, pd.DataFrame(report, columns=REPORT_COLUMNS), {"dropped": dropped, "checks": checks, "notes": notes}
