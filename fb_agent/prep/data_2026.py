"""2026-01~09 실제 매장 데이터 3종(구매청구·입고·일자별 매출)을 정제한다:  python -m prep.data_2026 [--year 2026|2025|2024] [--src data/source/<연도>] [--out data/cleaned/<연도>]

원본은 엑셀 출력물을 마크다운 표로 옮긴 파일이다 (제목행·소계행·합계행·`#NUM!`·병합 셀 빈칸·쉼표 숫자가 섞여 있음).
결과는 <이름>_정제.csv 와 <이름>_결측치_처리내역.csv, 점검 결과는 정제_점검결과.csv 에 남긴다. 원본은 수정하지 않는다.
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from prep.blocks import REPORT_COLUMNS, UnhandledMissingError, ensure_no_missing, fill, make_check

FILES = {
    "구매청구": "구매청구_리스트_26.01_26.09.md",
    "입고": "입고_리스트_26.01_26.09.md",
    "매출일자별": "매출분석_일자별_26.01_26.09.md",
}
FILES_2026_10 = {  # 2026-10: 구매청구·입고는 10-30까지, 일자별 매출은 10-29까지 (10-30은 영업 중이라 뺐다). 메뉴 단위 일자기준 조회는 따로 있다 (prep.menu_sales_daily)
    "구매청구": "구매청구_리스트_26.10.md",
    "입고": "입고_리스트_26.10.md",
    "매출일자별": "매출분석_일자별_26.10.md",
}
FILES_2025 = {     # --year 2025: 2025-01~11 전년동기 데이터 (파일명 구분자가 '-')
    "구매청구": "구매청구_리스트_25.01-25.11.md",
    "입고": "입고_리스트_25.01-25.11.md",
    "매출일자별": "매출분석_일자별_25.01-25.11.md",
}
FILES_2025_12 = {  # 2025-12 별도 다운로드분 (1~11월 파일과 양식이 같다)
    "구매청구": "구매청구_리스트_25.12.md",
    "입고": "입고_리스트_25.12.md",
    "매출일자별": "매출분석_일자별_25.12.md",
}
FILES_2024 = {     # --year 2024: 2024-01~12 (구매청구는 2025-01-02 입고분까지 들어 있다)
    "구매청구": "구매청구_리스트_24.md",
    "입고": "입고_리스트_24.md",
    "매출일자별": "매출분석_일자별_24.md",
}
# 연도마다 [(파일 묶음, 일자별 매출에서 영업하지 않은 날을 '무매출일'로 채울 시작일)]. 묶음마다 정제·점검한 뒤 합친다.
PARTS = {2026: [(FILES, "2026-01-01"), (FILES_2026_10, "2026-10-01")], 2024: [(FILES_2024, "2024-01-01")], 2025: [(FILES_2025, "2025-01-01"), (FILES_2025_12, "2025-12-01")]}
START = {y: parts[0][1] for y, parts in PARTS.items()}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEKDAY = "월화수목금토일"


def read_rows(path) -> list[list[str]]:
    """마크다운 표의 데이터 행을 칸 목록으로. 빈칸과 'NaN'은 None."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append([None if c in ("", "NaN") else c for c in cells])
    return rows


def number(s: pd.Series) -> pd.Series:
    """'1,332.00' -> 1332.0. 숫자로 읽을 수 없는 값이 있으면 오류."""
    out = pd.to_numeric(s.astype("string").str.replace(",", "", regex=False), errors="coerce")
    bad = s.notna() & out.isna()
    if bad.any():
        raise UnhandledMissingError(f"숫자가 아닌 값이 있습니다: {s[bad].unique()[:5].tolist()}")
    return out


def table_with_header(rows, header_row: int) -> pd.DataFrame:
    """header_row 의 칸 이름으로 표를 만든다. 이름이 없거나 겹치는 열은 '빈열N'·'이름_2'로."""
    names, seen = [], {}
    for j, c in enumerate(rows[header_row]):
        c = c or f"빈열{j}"
        seen[c] = seen.get(c, 0) + 1
        names.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
    return pd.DataFrame(rows[header_row + 1:], columns=names)


def drop_empty(df: pd.DataFrame, dropped: list, why: str) -> pd.DataFrame:
    empty = [c for c in df if df[c].isna().all()]
    if empty:
        dropped.append(f"{', '.join(empty)} ({why})")
    return df.drop(columns=empty)


def split_item(spec: pd.Series) -> pd.DataFrame:
    """'[수D1/부D2]깐대파_1kg/pk_1kg/pk_1030014GD' -> 태그·품명·규격·사양코드. 원문은 따로 남긴다."""
    tag = spec.str.extract(r"^(\[[^\]]*\])", expand=False)
    body = spec.str.replace(r"^\[[^\]]*\]", "", regex=True)
    code = body.str.extract(r"_(\d{7}[A-Z]{2})(?:\D.*)?$", expand=False)
    parts = body.str.split("_")
    return pd.DataFrame({
        "품명태그": tag.fillna("없음"),
        "품명": parts.str[0].str.strip(),
        "규격": parts.str[1].fillna("미기재"),
        "품목사양코드": code.fillna("없음"),
    })


# ── 일자별 매출 ────────────────────────────────────────────────────────────

def clean_daily_sales(rows, start="2026-01-01"):
    report, dropped, notes, checks = [], [], [], []
    df = pd.DataFrame(rows[2:])
    is_day = df[1].astype("string").str.match(DATE).fillna(False)
    total = df[df[1] == "총 합계"].iloc[0]
    d = df[is_day].copy()
    cols = ["총매출", "실매출", "순매출", "영수증수"]
    out = pd.DataFrame({"매출일자": pd.to_datetime(d[1]).values, "요일_원본": d[2].values})
    for c, j in zip(cols, (3, 4, 5, 6)):
        out[c] = number(d[j]).astype(int).values
        same = (number(d[j]) == number(d[j + 4])).all()
        checks.append(make_check(f"{c}: 전체 합계 열 = 매장 열(중복 열이라 삭제)", 1, int(same)))
    dropped.append("매장별 4열 (전체 합계 열과 값이 같은 중복 열, 매장이 1곳뿐)")
    dropped.append("No. (순번)")
    checks.append(make_check("No. = 1..N 연속", len(out), int(number(d[0]).astype(int).tolist() == list(range(1, len(out) + 1))) * len(out)))
    checks.append(make_check("요일 = 날짜의 실제 요일", len(out), int((out["요일_원본"].str[0] == out["매출일자"].dt.dayofweek.map(lambda i: WEEKDAY[i])).sum())))
    checks.append(make_check("순매출 ≤ 실매출 ≤ 총매출 (모든 날)", len(out), int(((out["순매출"] <= out["실매출"]) & (out["실매출"] <= out["총매출"])).sum())))
    for c, j in zip(cols, (3, 4, 5, 6)):
        checks.append(make_check(f"{c} 합계 = 총 합계 행", float(number(pd.Series([total[j]])).iloc[0]), float(out[c].sum())))

    # 영업하지 않은 날은 원본에 행이 없다. 0원으로 채우지 않고 '무매출일'로 표시한다.
    full = pd.DataFrame({"매출일자": pd.date_range(start, out["매출일자"].max())})
    out = full.merge(out.drop(columns="요일_원본"), on="매출일자", how="left")
    off = out["총매출"].isna()
    out["영업여부"] = np.where(off, "무매출일", "영업")
    for c in cols:
        fill(out, c, 0, off, "원본에 행이 없는 날(휴무 추정) → 매출·영수증 0", report, 0)
        out[c] = out[c].astype(int)
    out["요일"] = out["매출일자"].dt.dayofweek.map(lambda i: WEEKDAY[i] + "요일")
    out["영수증당_순매출"] = np.where(out["영수증수"] > 0, (out["순매출"] / out["영수증수"].where(out["영수증수"] > 0, 1)).round(), 0).astype(int)
    out["매출일자"] = out["매출일자"].dt.strftime("%Y-%m-%d")
    out = out[["매출일자", "요일", "영업여부", *cols, "영수증당_순매출"]]
    off_days = ", ".join(f"{x[5:]}({y[0]})" for x, y in out.loc[off, ["매출일자", "요일"]].values)
    if off.any():
        notes.append(f"무매출일 {int(off.sum())}일: {off_days}. 월요일·신정·설·추석 연휴에 몰려 있어 결측이 아니라 휴무로 추정(확인 필요).")
    ensure_no_missing(out)
    return out, pd.DataFrame(report, columns=REPORT_COLUMNS), {"dropped": dropped, "checks": checks, "notes": notes}


# ── 입고 리스트 ────────────────────────────────────────────────────────────

def clean_receiving(rows):
    report, dropped, notes, checks = [], [], [], []
    raw = table_with_header(rows, 5)
    item = raw["품목"].notna()
    det = raw[item].copy()
    sub = raw[~item]
    grand = sub[sub["품목명_사양 및 규격"] == "합계"].iloc[0]
    day_sub = sub[sub["품목명_사양 및 규격"].str.endswith(" 소계", na=False) & sub["품목명_사양 및 규격"].str[:10].str.match(DATE)]
    dropped.append(f"소계·합계 행 {len(sub)}개 (일 소계 {len(day_sub)}, 매장 소계 1, 합계 1)")

    money = ["입고단가", "입고수량", "입고금액", "입고부가세", "입고합계"]
    for c in money:
        det[c] = number(det[c])

    # 입고일자·매장명은 그룹의 첫 행에만 있다(병합 셀) → 위 행 값으로
    day = raw["입고일자"].where(raw["입고일자"].astype("string").str.match(DATE).fillna(False)).ffill()
    store = raw["매장명"].where(raw["매장명"].str.contains("점", na=False) & ~raw["매장명"].str.contains("소계", na=False)).ffill()
    for c, s, rule in (("입고일자", day, "병합 셀의 빈칸 → 같은 입고일 그룹의 첫 행 값"), ("매장명", store, "병합 셀의 빈칸 → 위 행의 매장명")):
        was_blank = det[c].isna()
        det[c] = s[item]
        report.append({"열": c, "채운 개수": int(was_blank.sum()), "규칙": rule, "채운 값": "위 행 값"})
    det["입고일자"] = pd.to_datetime(det["입고일자"]).dt.strftime("%Y-%m-%d")

    det = drop_empty(det, dropped, "전부 빈 열")
    det = det.drop(columns=[c for c in ("CORP_CD", "구분_2", "입고번호", "대분류코드", "중분류코드", "소분류코드") if c in det])
    dropped.append("CORP_CD(법인 고정값 134), 구분(전부 '홀'), 입고번호(IB_NO·YYYYMM으로 복원 가능, 그룹 첫 행에만 있음), 분류코드 3열(분류명과 1:1)")
    det = det.rename(columns={"품목": "품목코드_RMS", "품목명_사양 및 규격": "품목명_원본", "YYYYMM": "입고월", "재고단위": "입고단위"})
    det = pd.concat([det, split_item(det["품목명_원본"])], axis=1)

    kind = np.select([det["입고수량"] < 0, det["입고수량"] == 0], ["반품", "수량0"], "입고")
    det["입고유형"] = kind
    notes.append(f"반품 {int((kind == '반품').sum())}건(수량 음수), 수량 0 {int((kind == '수량0').sum())}건 — 삭제하지 않고 `입고유형`으로 표시. 반품·수량0은 예측 학습 시 따로 다룰 것.")

    # 점검
    checks += [
        make_check("입고수량 합 = 합계 행 (합계 행이 반올림되어 있어 0.5 이내 허용)", float(number(pd.Series([grand["입고수량"]])).iloc[0]), float(det["입고수량"].sum()),
                   ok=abs(float(number(pd.Series([grand["입고수량"]])).iloc[0]) - float(det["입고수량"].sum())) <= 0.5),
        make_check("입고금액 합 = 합계 행", float(number(pd.Series([grand["입고금액"]])).iloc[0]), float(det["입고금액"].sum())),
        make_check("입고부가세 합 = 합계 행", float(number(pd.Series([grand["입고부가세"]])).iloc[0]), float(det["입고부가세"].sum())),
        make_check("입고합계 합 = 합계 행", float(number(pd.Series([grand["입고합계"]])).iloc[0]), float(det["입고합계"].sum())),
        make_check("입고금액 + 부가세 = 입고합계 (위반 행 수)", 0, int(((det["입고금액"] + det["입고부가세"] - det["입고합계"]).abs() > 0.5).sum())),
        make_check("일 소계 행 수 = 입고일 수", len(day_sub), det["입고일자"].nunique()),
    ]
    by_day = det.groupby("입고일자")[["입고수량", "입고금액", "입고합계"]].sum()
    s = day_sub.assign(일자=day_sub["품목명_사양 및 규격"].str[:10]).set_index("일자")
    for c in ("입고수량", "입고금액", "입고합계"):
        checks.append(make_check(f"일 소계 = 일별 합 ({c}, 불일치 일수)", 0, int((number(s[c]).reindex(by_day.index) - by_day[c]).abs().gt(0.5).sum())))
    bad_amt = ((det["입고수량"] * det["입고단가"] - det["입고금액"]).abs() > 1)
    checks.append(make_check("수량 × 단가 = 금액 (반올림 허용, 위반 행 수)", 0, int(bad_amt.sum()), note=True))
    if bad_amt.any():
        r = det[bad_amt].iloc[0]
        notes.append(f"수량×단가≠금액 {int(bad_amt.sum())}행: {r['입고일자']} {r['품명']} 단가 {r['입고단가']:g}원 × {r['입고수량']:g} ≠ {r['입고금액']:g}원 (단가 소수점 반올림 차이).")
    checks.append(make_check("(입고월, IB_NO, IB_SEQ) 중복 행 수", 0, int(det.duplicated(["입고월", "IB_NO", "IB_SEQ"]).sum())))

    for c in ("입고수량",):
        det[c] = det[c].astype(float)
    det["입고단가"] = det["입고단가"].astype(float)
    for c in ("입고금액", "입고부가세", "입고합계"):
        det[c] = det[c].astype(int)
    no_order = det["O_NO"].isna()
    for c in ("O_YYYYMM", "O_NO", "O_SEQ"):
        fill(det, c, "0", no_order, "발주 없는 일반입고(반품) → 0 (발주번호 없음)", report, 0)
    for c in ("IB_NO", "IB_SEQ", "O_YYYYMM", "O_NO", "O_SEQ"):
        det[c] = number(det[c]).astype(int)
    front = ["입고일자", "매장명", "매장코드", "거래처코드", "거래처명", "품목코드_RMS", "품명", "규격", "품명태그", "품목사양코드", "대분류명", "중분류명", "소분류명",
             "입고유형", "입고형태", "과세구분", "입고단위", "입고단가", "입고수량", "입고금액", "입고부가세", "입고합계"]
    det = det[front + [c for c in det if c not in front]].reset_index(drop=True)
    ensure_no_missing(det)
    return det, pd.DataFrame(report, columns=REPORT_COLUMNS), {"dropped": dropped, "checks": checks, "notes": notes}


# ── 구매청구 리스트 ────────────────────────────────────────────────────────

def clean_purchase_requests(rows):
    report, dropped, notes, checks = [], [], [], []
    raw = table_with_header(rows, 5)
    grand = raw[raw["YMD"].isna()].iloc[0]
    det = raw[raw["YMD"].notna()].copy()
    dropped.append("합계 행 1개")
    for c in ("발주단가", "발주수량", "입고단가", "입고수량", "입고금액", "입고부가세", "입고합계"):
        det[c] = number(det[c])

    # 청구번호는 첫 행에만 있다 → 청구일자+R_NO 로 복원하고, 원본에 있는 값과 맞는지 확인
    derived = det["YMD"] + "-" + det["R_NO"].str.zfill(3)
    given = det["청구번호"].notna()
    checks.append(make_check("청구번호: 원본 값 = 청구일자-R_NO (불일치 행 수)", 0, int((det.loc[given, "청구번호"] != derived[given]).sum())))
    fill(det, "청구번호", derived, ~given, "병합 셀의 빈칸 → 청구일자(YMD)-R_NO(3자리)로 복원", report, "예: 20260101-006")

    # 3개 날짜가 한 칸에 합쳐진 열 → 개별 열과 같은지 확인하고 삭제
    dates = det["청구일자/납기일자/입고일자"].str.split(r"\s+", regex=True)
    ymd = pd.to_datetime(det["YMD"]).dt.strftime("%Y-%m-%d")
    nab = pd.to_datetime(det["NAB_DATE"]).dt.strftime("%Y-%m-%d")
    checks.append(make_check("합쳐진 날짜 열의 청구일·납기일 = YMD·NAB_DATE (불일치 행 수)", 0, int(((dates.str[0] != ymd) | (dates.str[1] != nab)).sum())))
    det["청구일자"], det["납기일자"] = ymd, nab
    received = det["IBCH_DATE"].notna()
    checks.append(make_check("합쳐진 날짜 열의 입고일 = IBCH_DATE (불일치 행 수)", 0, int((dates.str[2][received] != det.loc[received, "IBCH_DATE"]).sum())))

    # 미입고: 발주만 하고 입고가 없는 행 (DEL_CHK = N)
    nr = det["DEL_CHK"] == "N"
    checks.append(make_check("미입고(N) 행의 입고번호·입고일자가 모두 비어 있음", int(nr.sum()), int((det["V_NO"].isna() & det["IBCH_DATE"].isna())[nr].sum())))
    checks.append(make_check("입고번호·입고일자가 빈 행은 모두 미입고(N)", int(det["V_NO"].isna().sum()), int((det["V_NO"].isna() & nr).sum())))
    det["처리상태"] = np.where(nr, "미입고", np.where(det["입고수량"] == 0, "입고수량0", "입고"))
    for c, rule in (("IBCH_DATE", "미입고 → '미입고' (입고 기록이 없음)"),):
        fill(det, c, "미입고", det[c].isna() & nr, rule, report)
    det = det.rename(columns={"IBCH_DATE": "입고일자"})
    for c in ("V_NO", "V_SEQ", "YYYYMM"):
        fill(det, c, "0", det[c].isna() & nr, "미입고 → 0 (입고번호 없음)", report, 0)
    for c in ("O_YYYYMM", "O_NO", "O_SEQ"):
        m = det[c].isna() & nr
        fill(det, c, "0", m, "미입고 → 0 (발주번호가 부여되지 않음)", report, 0)
    notes.append(f"미입고 {int(nr.sum())}행(발주수량 합 {det.loc[nr, '발주수량'].sum():,.0f}): 청구는 했지만 발주·입고되지 않음. 삭제하지 않고 `처리상태`로 표시.")
    zero_y = (det["입고수량"] == 0) & ~nr
    if zero_y.any():
        notes.append(f"입고수량 0이지만 입고번호가 있는 행 {int(zero_y.sum())}개 — `입고수량0`으로 표시.")

    det["입고수량_차이"] = det["입고수량"] - det["발주수량"]
    det["청구후_입고까지_일"] = (pd.to_datetime(det["입고일자"], errors="coerce") - pd.to_datetime(det["청구일자"])).dt.days
    fill(det, "청구후_입고까지_일", -1, det["청구후_입고까지_일"].isna(), "미입고 → -1 (입고까지 걸린 날 없음)", report, -1)
    det["청구후_입고까지_일"] = det["청구후_입고까지_일"].astype(int)
    notes.append(f"발주수량과 입고수량이 다른 행 {int((det['입고수량_차이'] != 0).sum())}개(미입고 {int(nr.sum())} 포함) — `입고수량_차이`.")

    drop = [c for c in ("CORP_CD", "ST_SEC", "FB_SEC", "JOB_FLAG1", "JOB_FLAG2", "GROUP_FLAG", "CONV_DON", "CONV_NUM", "DEL_CHK", "YMD", "NAB_DATE",
                        "청구일자/납기일자/입고일자", "발주번호/입고번호", "R_NO") if c in det]
    det = det.drop(columns=drop)
    dropped.append("CORP_CD·ST_SEC·FB_SEC·JOB_FLAG1/2(고정 코드), GROUP_FLAG·CONV_DON·CONV_NUM(전부 빈 열), DEL_CHK(→처리상태), "
                   "YMD·NAB_DATE·합쳐진 날짜 열·발주번호/입고번호(개별 열과 같음), R_NO(청구번호에 포함)")
    # 이름 정리: 빈열19=청구 순번, 품목명_사양=품목코드, 품목명_사양_2=품목명
    det = det.rename(columns={"빈열19": "청구순번", "품목명_사양": "품목코드_RMS", "품목명_사양_2": "품목명_원본"})
    det = det.drop(columns=["매장명", "매장코드"])
    store = raw["매장명"].dropna().iloc[0]
    det["매장명"] = store
    store_code = raw["매장코드"].dropna().iloc[0]
    det["매장코드"] = store_code
    report.append({"열": "매장명/매장코드", "채운 개수": len(det), "규칙": "첫 행에만 있음(병합 셀) → 전체 행", "채운 값": f"{store} / {store_code}"})
    det = pd.concat([det, split_item(det["품목명_원본"])], axis=1)

    checks += [
        make_check("발주수량 합 = 합계 행", float(number(pd.Series([grand["발주수량"]])).iloc[0]), float(det["발주수량"].sum())),
        make_check("입고수량 합 = 합계 행 (합계 행이 반올림되어 있어 0.5 이내 허용)", float(number(pd.Series([grand["입고수량"]])).iloc[0]), float(det["입고수량"].sum()),
                   ok=abs(float(number(pd.Series([grand["입고수량"]])).iloc[0]) - float(det["입고수량"].sum())) <= 0.5),
        make_check("입고금액 + 부가세 = 입고합계 (위반 행 수)", 0, int(((det["입고금액"] + det["입고부가세"] - det["입고합계"]).abs() > 0.5).sum())),
    ]
    # 같은 발주 줄이 입고일만 다르게 한 번 더 적힌 사본은 가장 이른 입고일 행만 남긴다 (합계 행 대조는 위에서 끝냈다).
    key = ["O_YYYYMM", "O_NO", "O_SEQ"]
    other = [c for c in det if c not in ("입고일자", "청구후_입고까지_일")]
    copy = (~nr) & det.duplicated(key, keep=False) & det.sort_values("입고일자").duplicated(subset=other, keep="first").reindex(det.index)
    if copy.any():
        gone = det[copy]
        notes.append(f"중복 {int(copy.sum())}행 삭제: 같은 발주 줄(발주월·발주번호·순번)이 입고일만 다르게 한 번 더 적힘 "
                     f"(입고일 {', '.join(sorted(gone['입고일자'].unique()))}, 입고합계 {int(gone['입고합계'].sum()):,}원). 가장 이른 입고일 행을 남김. 입고 리스트와 대조는 파일 간 교차 점검 참고.")
        dropped.append(f"중복 사본 {int(copy.sum())}행 (같은 발주 줄이 입고일만 다르게 반복)")
        det = det[~copy].reset_index(drop=True)
        nr = det["처리상태"] == "미입고"
    checks.append(make_check("(발주월, 발주번호, 순번) 중복 행 수 (미입고 제외, 사본 정리 후)", 0, int(det[~nr].duplicated(key).sum())))
    for c in ("O_YYYYMM", "O_NO", "O_SEQ", "V_NO", "V_SEQ", "YYYYMM"):
        det[c] = number(det[c]).astype(int)
    for c in ("입고금액", "입고부가세", "입고합계"):
        det[c] = det[c].astype(int)
    front = ["청구일자", "청구번호", "납기일자", "입고일자", "처리상태", "매장명", "매장코드", "거래처", "품목코드_RMS", "품명", "규격", "품명태그", "품목사양코드", "세금",
             "발주단위", "발주단가", "발주수량", "입고단위", "입고단가", "입고수량", "입고수량_차이", "입고금액", "입고부가세", "입고합계", "청구후_입고까지_일"]
    det = det[front + [c for c in det if c not in front]].reset_index(drop=True)
    ensure_no_missing(det)
    return det, pd.DataFrame(report, columns=REPORT_COLUMNS), {"dropped": dropped, "checks": checks, "notes": notes}


def cross_checks(res: dict, first_ym: int = 202601) -> list[dict]:
    """세 파일이 서로 맞는지. 원본 데이터 자체의 차이는 note=True(참고)."""
    out = []
    rcv, req, day = res["입고"]["table"].copy(), res["구매청구"]["table"], res["매출일자별"]["table"]
    rcv["입고월"] = rcv["입고월"].astype(int)
    k = ["입고월", "IB_NO", "IB_SEQ"]
    rq = req[req["처리상태"] != "미입고"].rename(columns={"YYYYMM": "입고월", "V_NO": "IB_NO", "V_SEQ": "IB_SEQ"})
    in_range = rq[rq["입고일자"] <= rcv["입고일자"].max()]
    m = rcv.merge(in_range[k + ["입고수량", "입고합계"]], on=k, how="outer", suffixes=("", "_청구"), indicator=True)
    both = m[m["_merge"] == "both"]
    only_r = m[m["_merge"] == "left_only"]
    # 구매청구 파일은 1월 1일 청구분부터라서, 전달(12월) 청구 → 1/2 입고분과 발주 없는 반품은 청구 쪽에 없는 게 정상
    explained = (only_r["O_YYYYMM"] < first_ym) | (only_r["입고유형"] == "반품")
    out.append(make_check("입고 행 = 구매청구와 키가 일치한 행 + 전달 청구분·반품 (설명 안 되는 행 수, 원본 파일 간 불일치라 참고)", 0, int((m["_merge"] == "left_only").sum() - explained.sum()), note=True))
    out.append(make_check("구매청구에만 있는 입고 행 (입고에 없음)", 0, int((m["_merge"] == "right_only").sum())))
    out.append(make_check("키가 일치한 행의 입고수량 차이 (행 수)", 0, int((both["입고수량"] != both["입고수량_청구"]).sum())))
    out.append(make_check("키가 일치한 행의 입고합계 차이 (행 수)", 0, int((both["입고합계"] != both["입고합계_청구"]).sum())))
    out.append(make_check("입고 합계금액 − (전달 청구분·반품) = 구매청구 입고합계", int(rcv["입고합계"].sum() - only_r["입고합계"].sum()), int(in_range["입고합계"].sum())))
    out.append(make_check("전달 청구분·반품으로 청구에 없는 입고 행 수", 0, int(explained.sum()), note=True))
    out.append(make_check("무매출일에 입고가 있는 날 수 (참고)", 0, int(day.loc[day["영업여부"] == "무매출일", "매출일자"].isin(rcv["입고일자"]).sum()), note=True))
    return out


CLEANERS = [
    ("매출일자별", clean_daily_sales),
    ("구매청구", clean_purchase_requests),
    ("입고", clean_receiving),
]


def merge_parts(name: str, tables: list[pd.DataFrame], notes: list[str]) -> pd.DataFrame:
    """묶음별로 정제한 표를 하나로. 겹치는 행은 키로 정리한다 (구매청구: 월말 청구가 다음 묶음에도 들어 있다)."""
    if len(tables) == 1:
        return tables[0]
    t = pd.concat(tables, ignore_index=True)
    if name == "구매청구":
        before = len(t)
        t = t.drop_duplicates(["청구일자", "청구번호", "청구순번"], keep="last").reset_index(drop=True)
        notes.append(f"구매청구: 묶음이 겹치는 청구 {before - len(t)}행은 나중 묶음 값만 남김.")
    return t


def main(argv=None) -> int:
    data = Path(__file__).resolve().parent.parent / "data"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--year", type=int, choices=sorted(START), default=2026)
    ap.add_argument("--src", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    a.src = a.src or str(data / "source" / str(a.year))
    a.out = a.out or str(data / "cleaned" / str(a.year))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    parts, all_checks, failed = PARTS[a.year], [], False
    cleaned = {name: [] for name, _fn in CLEANERS}
    reports = {name: [] for name, _fn in CLEANERS}
    for k, (files, start) in enumerate(parts):
        tag = f" [{files.get('매출일자별', files['구매청구']).rsplit('_', 1)[-1][:-3]}]" if len(parts) > 1 else ""
        for name, fn in CLEANERS:
            if name not in files:                                  # 이 묶음에 없는 파일
                continue
            table, report, info = fn(read_rows(Path(a.src) / files[name]), **({"start": start} if name == "매출일자별" else {}))
            cleaned[name].append(table)
            reports[name].append(report)
            bad = [c for c in info["checks"] if not c["ok"] and not c.get("참고")]
            failed |= bool(bad)
            all_checks += [{"시트": name + tag, **c} for c in info["checks"]]
            print(f"\n■ {name}{tag}: {len(table):,}행x{table.shape[1]}열\n  채운 결측 {int(report['채운 개수'].sum()):,}개 | 남은 결측 {int(table.isna().sum().sum())}개 | 점검 {len(info['checks']) - len(bad)}/{len(info['checks'])} 통과")
            for d in info["dropped"]:
                print("  삭제:", d)
            for b in bad:
                print(f"  ✗ {b['항목']}: 기대 {b['기대']} / 실제 {b['실제']}")
            for n in info["notes"]:
                print("  ·", n)
            if len(report):
                print(report.to_string(index=False, max_colwidth=48))
    res, merge_notes = {}, []
    for name, _fn in CLEANERS:
        table = merge_parts(name, cleaned[name], merge_notes)
        table.to_csv(out / f"{name}_정제.csv", index=False, encoding="utf-8-sig")
        pd.concat(reports[name], ignore_index=True).to_csv(out / f"{name}_결측치_처리내역.csv", index=False, encoding="utf-8-sig")
        res[name] = {"table": table}
    if len(parts) > 1:
        day, rcv = res["매출일자별"]["table"], res["입고"]["table"]
        all_checks += [
            {"시트": "묶음 합치기", **make_check("일자별 매출: 날짜 중복 없음 (중복 일수)", 0, int(day["매출일자"].duplicated().sum()))},
            {"시트": "묶음 합치기", **make_check("일자별 매출: 첫날~끝날 사이 모든 날짜가 있음 (빠진 일수)", 0, int(len(pd.date_range(day["매출일자"].min(), day["매출일자"].max())) - len(day)))},
            {"시트": "묶음 합치기", **make_check("입고: (입고월, IB_NO, IB_SEQ) 중복 행 수", 0, int(rcv.duplicated(["입고월", "IB_NO", "IB_SEQ"]).sum()))},
        ]
        failed |= any(not c["ok"] for c in all_checks if c["시트"] == "묶음 합치기")
        print("\n■ 묶음 합치기:", f"일자별 매출 {len(day)}일, 입고 {len(rcv):,}행", *(["\n  · " + n for n in merge_notes]))
        for c in all_checks[-3:]:
            print(f"  {'✓' if c['ok'] else '✗'} {c['항목']}: 기대 {c['기대']} / 실제 {c['실제']}")
    cross = cross_checks(res, a.year * 100 + 1)
    print("\n■ 파일 간 교차 점검")
    for c in cross:
        mark = "✓" if c["ok"] else ("⚠ 참고" if c["참고"] else "✗")
        print(f"  {mark} {c['항목']}: 기대 {c['기대']:,} / 실제 {c['실제']:,}")
        failed |= (not c["ok"]) and not c["참고"]
    all_checks += [{"시트": "교차점검", **c} for c in cross]
    pd.DataFrame(all_checks).to_csv(out / "정제_점검결과.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장 위치: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
