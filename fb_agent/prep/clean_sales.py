"""'매출입력(매출영수증상세)' 시트의 결측치 처리.

이 시트의 빈칸(NaN)은 대부분 '해당 없음'이라는 뜻이라 dropna 로 지우면 모든 행이 사라진다.
열의 성격별로 의미 있는 값으로 채우고, 규칙으로 설명되지 않는 결측은 조용히 채우지 않고 오류로 알린다.

    python -m prep.clean_sales [--src data/f_b_menu_data.md] [--out data/cleaned]
"""
import argparse
from pathlib import Path

import pandas as pd

from prep.blocks import REPORT_COLUMNS, UnhandledMissingError, fill as _fill_block
from prep.md_tables import read_sheet

SHEET = "매출입력(매출영수증상세)"
# 빈칸의 의미 -> 채울 값
FILL_TEXT = {"취소구분": "정상", "할인수단": "할인없음", "객층": "미기록", "결제수단": "결제없음"}
CANCEL_ROW_TEXT = "해당없음"                      # 메뉴 없는 취소 영수증의 메뉴 관련 열
MENU_TEXT_COLS = ["대분류명", "중분류명", "소분류명", "메뉴명", "과/면세"]
ID_TEXT_COLS = ["법인코드", "브랜드코드", "매장코드", "메뉴코드"]        # 숫자처럼 보여도 문자 ID
SUM_COLS = ["객수_합계", "단가_합계", "수량_합계", "총매출_합계", "할인_합계", "실매출_합계", "순매출_합계", "부가세_합계"]
INT_COLS = ["No.", "그룹코드", "포스번호", "영수증번호", "객수", "주문번호", "단가", "수량",
            "총매출", "할인", "실매출", "순매출", "부가세", *SUM_COLS]


_fill = _fill_block


def clean_sales_detail(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(정제된 DataFrame, 처리 내역 DataFrame). 행은 지우지 않는다."""
    df = raw.copy()
    report: list[dict] = []

    # 1) 취소구분·할인수단·객층: 빈칸 = 해당 사항 없음
    for col, rule in (("취소구분", "취소가 아닌 정상 거래"), ("할인수단", "할인 없음"), ("객층", "객층 입력 안 함")):
        if col in df:
            _fill(df, col, FILL_TEXT[col], df[col].isna(), rule, report)

    # 2) 결제수단: 실매출(합계)이 0원일 때만 '결제 없음'. 돈이 오갔는데 비어 있으면 진짜 결측이라 막는다.
    if "결제수단" in df:
        miss = df["결제수단"].isna()
        if "실매출_합계" in df:
            paid = pd.to_numeric(df["실매출_합계"], errors="coerce").fillna(0) != 0
            if (miss & paid).any():
                raise UnhandledMissingError(
                    f"결제수단이 비었는데 실매출_합계가 0이 아닌 행 {int((miss & paid).sum())}개 "
                    f"(위치: {list(df.index[miss & paid][:5])}). 실제 결측이므로 원본 확인이 필요합니다.")
            miss = miss & ~paid
        _fill(df, "결제수단", FILL_TEXT["결제수단"], miss, "결제 없음 (실매출_합계 0원)", report)

    # 3) 메뉴가 없는 행: 취소 영수증일 때만 허용. 취소 건수가 사라지지 않도록 행은 유지한다.
    if "메뉴명" in df:
        no_menu = df["메뉴명"].isna()
        normal = df["취소구분"].eq(FILL_TEXT["취소구분"]) if "취소구분" in df else pd.Series(False, index=df.index)
        if (no_menu & normal).any():
            raise UnhandledMissingError(
                f"메뉴명이 비었는데 취소 거래가 아닌 행 {int((no_menu & normal).sum())}개 (위치: {list(df.index[no_menu & normal][:5])})")
        for col in [*MENU_TEXT_COLS, "메뉴코드"]:
            if col in df:
                _fill(df, col, CANCEL_ROW_TEXT, df[col].isna() & no_menu, "메뉴 없는 취소 영수증", report)
        if "주문번호" in df:
            _fill(df, "주문번호", 0, df["주문번호"].isna() & no_menu, "메뉴 없는 취소 영수증 (주문 없음)", report)

    # 4) 규칙으로 설명되지 않는 결측은 채우지 않는다.
    left = df.isna().sum()
    left = left[left > 0]
    if len(left):
        raise UnhandledMissingError("규칙이 없는 결측치가 남았습니다: " + ", ".join(f"{c} {int(n)}개" for c, n in left.items()))

    # 5) 형 정리: 정수 열, 문자 ID('1067.0' -> '1067')
    for col in INT_COLS:
        if col in df:
            df[col] = pd.to_numeric(df[col]).round().astype("int64")
    for col in ID_TEXT_COLS:
        if col in df:
            df[col] = df[col].astype(str).str.replace(r"\.0$", "", regex=True)
    return df, pd.DataFrame(report, columns=REPORT_COLUMNS)


def main(argv=None) -> int:
    data = Path(__file__).resolve().parent.parent / "data"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=str(data / "f_b_menu_data.md"))
    ap.add_argument("--out", default=str(data / "cleaned"))
    a = ap.parse_args(argv)

    print(f"읽는 중: {a.src}")
    raw = read_sheet(a.src, SHEET)
    clean, report = clean_sales_detail(raw)

    money = ["총매출", "할인", "실매출", "순매출", "부가세"]
    same = all(float(pd.to_numeric(raw[c]).sum()) == float(clean[c].sum()) for c in money if c in raw)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    clean.to_csv(out / "매출입력_정제.csv", index=False, encoding="utf-8-sig")
    report.to_csv(out / "매출입력_결측치_처리내역.csv", index=False, encoding="utf-8-sig")

    print(f"행 {len(raw):,} → {len(clean):,} (삭제 {len(raw) - len(clean)}행) | 결측 {int(raw.isna().sum().sum()):,}개 → {int(clean.isna().sum().sum())}개")
    print("금액 합계 정제 전후 동일:", "예" if same else "아니오 (확인 필요)")
    print(report.to_string(index=False))
    print(f"저장: {out / '매출입력_정제.csv'}\n저장: {out / '매출입력_결측치_처리내역.csv'}")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
