"""'실사재고', '입고내역' 시트의 결측치 처리 (리포트형 시트).

두 시트는 제목행·주석·2줄 머리글·합계행이 섞인 엑셀 보고서 모양이다. 상세표만 잘라내 한 줄 머리글로 펴고,
빈칸은 아래 규칙으로 채운다. 규칙은 데이터에서 실제로 성립함을 확인한 관계만 쓴다.

  수량 = 중량 ÷ 환산단위            (실사재고 149/149행, 입고내역 일자별 1,186/1,186칸에서 성립)
  차이 = 당월발주(빈칸은 0) − 당월합계수량   (입고내역 873/873행에서 성립)

규칙으로 설명되지 않는 결측은 조용히 채우지 않고 UnhandledMissingError 로 알린다.
합계행은 데이터가 아니라 검증용으로 쓴다 (상세표의 합과 일치하는지 확인).
"""
import re

import pandas as pd

from prep.blocks import (REPORT_COLUMNS, UnhandledMissingError, ensure_no_missing, fill, find_row, flatten_header, label,
                         make_check as _check, notes_above, take_block as _take_block,
                         to_numbers as _to_numbers)

SHEET_COUNT = "실사재고"
SHEET_RECEIVING = "입고내역"
NONE_TEXT = "없음"          # 해당 코드가 없는 품목
UNSPEC_TEXT = "미기재"       # 원본에 적혀 있지 않은 규격·과세구분
CODE_COLS = ["품목코드_RMS", "품목코드_CK", "품목코드_매장"]
SPEC_COLS = ["규격", "과세면세"]
ACCOUNT_COL = 1              # '계정명' 열 위치 (두 시트 공통)


def _locate(raw: pd.DataFrame):
    """(머리글 첫 줄, 상세표 시작, 상세표 끝(미포함)). 상세표는 계정명이 연속으로 있는 행."""
    h = find_row(raw, ACCOUNT_COL, "계정명")
    if h is None:
        raise ValueError("머리글 행('계정명')을 찾지 못했습니다.")
    start = h + 2
    end = start
    while end < len(raw) and pd.notna(raw.iat[end, ACCOUNT_COL]) and label(raw.iat[end, ACCOUNT_COL]) != "합계":
        end += 1
    return h, start, end


def _label_fill(df, report):
    for col in CODE_COLS:
        if col in df:
            fill(df, col, NONE_TEXT, df[col].isna(), "해당 코드 없음", report)
    for col in SPEC_COLS:
        if col in df:
            fill(df, col, UNSPEC_TEXT, df[col].isna(), "원본에 적혀 있지 않음", report)


def _quantity_from_weight(df, qty: str, weight: str, unit: str, report, zero_needs=()):
    """수량 빈칸: 중량(·금액)이 0이면 0, 아니면 중량 ÷ 환산단위."""
    miss = df[qty].isna()
    zero = (df[weight] == 0)
    for extra in zero_needs:
        zero &= df[extra] == 0
    fill(df, qty, 0.0, miss & zero, "중량(·금액)이 0이라 수량도 0", report)
    miss = df[qty].isna()
    derived = df[weight] / df[unit].where(df[unit] > 0)
    fill(df, qty, derived, miss & derived.notna(), "중량 ÷ 환산단위로 계산", report, shown="중량÷환산단위")


# ---------------------------------------------------------------- 실사재고
def clean_inventory_count(raw: pd.DataFrame):
    """'실사재고' 시트 -> (정제표, 처리내역, {"dropped", "checks", "notes"})."""
    h, start, end = _locate(raw)
    names = flatten_header(raw, h, last_col=11)
    num = ["환산단위", "재고실사_수량", "재고실사_중량_g"]
    df, dropped = _take_block(raw, names, start, end, last_col=11, keep=[*CODE_COLS, *SPEC_COLS, *num])
    _to_numbers(df, num)
    report: list[dict] = []

    _label_fill(df, report)
    _quantity_from_weight(df, "재고실사_수량", "재고실사_중량_g", "환산단위", report)
    ensure_no_missing(df)

    checks = []
    total = find_row(raw, ACCOUNT_COL, "합계", start=end)
    if total is not None:
        for col, j in (("재고실사_수량", 10), ("재고실사_중량_g", 11)):
            checks.append(_check(f"{col} 합계", pd.to_numeric(raw.iat[total, j]), df[col].sum()))
    return df, pd.DataFrame(report, columns=REPORT_COLUMNS), {"dropped": dropped, "checks": checks, "notes": notes_above(raw, h)}


# ---------------------------------------------------------------- 입고내역
def clean_receiving(raw: pd.DataFrame):
    """'입고내역' 시트의 품목별 일자 상세표 -> (정제표, 처리내역, {"dropped", "checks", "notes"})."""
    h, start, end = _locate(raw)
    day_cols = [j for j in range(raw.shape[1]) if pd.notna(raw.iat[h, j]) and re.fullmatch(r"\d+일", label(raw.iat[h, j]))]
    if not day_cols:
        raise ValueError("일자(1일, 2일 …) 머리글을 찾지 못했습니다.")
    last_col = max(day_cols) + 2                                  # 마지막 일자의 금액 열까지
    names = flatten_header(raw, h, last_col, overrides={0: "구분"})
    days_in = sorted({int(m.group(1)) for n in names if n and (m := re.match(r"(\d+)일_", n))})
    must = [*CODE_COLS, *SPEC_COLS, "환산단위", "당월발주", "차이", "당월합계_수량", "당월합계_중량_g", "당월합계_금액",
            *[f"{d}일_{k}" for d in days_in for k in ("수량", "중량_g", "금액")]]
    df, dropped = _take_block(raw, names, start, end, last_col, keep=must)

    days = sorted({int(re.match(r"(\d+)일_", c).group(1)) for c in df.columns if re.match(r"\d+일_", c)})
    total_cols = ["당월합계_수량", "당월합계_중량_g", "당월합계_금액"]
    day_cols_of = lambda kind: [f"{d}일_{kind}" for d in days]  # noqa: E731
    _to_numbers(df, ["단가_g", "단가", "환산단위", "당월발주", "차이", *total_cols,
                     *day_cols_of("수량"), *day_cols_of("중량_g"), *day_cols_of("금액")])
    report: list[dict] = []
    checks = []

    # 채우기 전에, 차이 산식이 원래 값이 있는 행에서 성립하는지 확인
    has_diff = df["차이"].notna()
    formula = df["당월발주"].fillna(0) - df["당월합계_수량"]
    checks.append(_check("차이 = 당월발주 − 당월합계수량 (원래 값이 있는 행 불일치 수)", 0,
                         int((~((formula - df["차이"]).abs() < 1e-6) & has_diff).sum())))

    _label_fill(df, report)
    fill(df, "당월발주", 0.0, df["당월발주"].isna(), "발주 없음", report)
    fill(df, "차이", df["당월발주"] - df["당월합계_수량"], df["차이"].isna() & df["당월합계_수량"].notna(),
         "당월발주 − 당월합계수량으로 계산", report, shown="당월발주−당월합계수량")
    for d in days:                                                   # 일자별: 금액 0 -> 중량 0, 수량은 중량·금액이 0이면 0, 아니면 중량÷환산단위
        fill(df, f"{d}일_중량_g", 0.0, df[f"{d}일_중량_g"].isna() & (df[f"{d}일_금액"] == 0), "그날 금액이 0원이라 입고 없음(중량 0)", report)
        _quantity_from_weight(df, f"{d}일_수량", f"{d}일_중량_g", "환산단위", report, zero_needs=(f"{d}일_금액",))
    # 일자별 열 이름이 날마다 따로 기록되면 보고서가 길어지므로 같은 규칙은 한 줄로 합친다
    report = _merge_day_rules(report)
    ensure_no_missing(df)

    # 합계 검증: 상세표의 합 = 요약 '합계' 행, 행별 당월합계 = 일자 합
    summary = _find_summary_row(raw, end)
    if summary is not None:
        for col, j in zip(total_cols, (15, 16, 17)):
            checks.append(_check(f"{col} 합계", pd.to_numeric(raw.iat[summary, j]), df[col].sum()))
    for kind, col in (("수량", "당월합계_수량"), ("중량_g", "당월합계_중량_g"), ("금액", "당월합계_금액")):
        by_day = df[day_cols_of(kind)].sum(axis=1)
        bad = int(((by_day - df[col]).abs() > 1e-6 * (1 + df[col].abs())).sum())
        checks.append(_check(f"행별 당월합계 = 일자 합 ({kind.replace('_g', '')}) 불일치 행 수", 0, bad))
    # 위 두 검사는 이름을 안정적으로 쓰기 위해 별칭도 둔다
    for c in list(checks):
        if c["항목"].startswith("행별 당월합계 = 일자 합 (금액)"):
            checks.append({**c, "항목": "행별 당월합계 = 일자 합 (금액)"})
    return df, pd.DataFrame(report, columns=REPORT_COLUMNS), {"dropped": dropped, "checks": checks, "notes": notes_above(raw, h)}


def _find_summary_row(raw: pd.DataFrame, after: int):
    """상세표 아래 요약 블록에서 '합계' 라벨(11열)과 숫자 합계가 있는 행."""
    for i in range(after, len(raw)):
        v = raw.iat[i, 11]
        if pd.notna(v) and label(v) == "합계" and pd.notna(raw.iat[i, 15]):
            return i
    return None


def _merge_day_rules(report: list[dict]) -> list[dict]:
    """'1일_수량', '2일_수량' … 처럼 날마다 나뉜 같은 규칙을 '일자별_수량' 한 줄로 합친다."""
    merged: dict = {}
    out = []
    for r in report:
        m = re.match(r"\d+일_(.+)", r["열"])
        if not m:
            out.append(r)
            continue
        key = (f"일자별_{m.group(1)}", r["규칙"], r["채운 값"])
        merged[key] = merged.get(key, 0) + r["채운 개수"]
    out += [{"열": k[0], "채운 개수": n, "규칙": k[1], "채운 값": k[2]} for k, n in merged.items()]
    return out
