import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from prep.clean_sales import (CANCEL_ROW_TEXT, FILL_TEXT, SHEET, UnhandledMissingError, clean_sales_detail)
from prep.md_tables import read_sheet, read_sheets

MD = """## 수불요약
| Unnamed: 0 | 2025년 12월 | Unnamed: 2 |
| --- | --- | --- |
| NaN | 수불 마감 | NaN |
| NaN | 원재료 | 100 |

## 빈시트
| a | b |
| --- | --- |

## 매출입력(매출영수증상세)
| No. | 영수증번호 | 취소구분 | 객수 | 객층 | 주문번호 | 대분류명 | 메뉴코드 | 메뉴명 | 과/면세 | 단가 | 수량 | 총매출 | 할인 | 실매출 | 객수\\_합계 | 총매출\\_합계 | 실매출\\_합계 | 결제수단 | 할인수단 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | NaN | 2 | NaN | 1.0 | 음식 | 10670200.0 | 샤오롱바오 | 과세 | 21000 | 1 | 21000 | 0 | 21000 | 2 | 21000 | 21000 | 신용카드 | NaN |
| 2 | 1 | NaN | 2 | NaN | 2.0 | 음식 | 10710200.0 | 완탕 | 과세 | 11000 | 1 | 11000 | 11000 | 0 | 0 | 0 | 0 | NaN | 비율할인-멤버십10% |
| 3 | 2 | 주문취소 | 1 | 내국인(남자) 1 | NaN | NaN | NaN | NaN | NaN | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NaN | NaN |
| 4 | 3 | 매출취소 | 1 | NaN | 1.0 | 음료 | 54100200.0 | 콜라\\_캔 | 과세 | 3000 | 1 | 3000 | 0 | 3000 | 1 | 3000 | 3000 | 현금 | NaN |
"""


def write(text: str) -> Path:
    p = Path(tempfile.mkdtemp()) / "m.md"
    p.write_text(text, encoding="utf-8")
    return p


class MdTables(unittest.TestCase):
    def test_reads_every_section_with_its_own_shape(self):
        sheets = read_sheets(write(MD))
        self.assertEqual(list(sheets), ["수불요약", "빈시트", SHEET])
        self.assertEqual(sheets["수불요약"].shape, (2, 3))
        self.assertEqual(sheets[SHEET].shape, (4, 20))

    def test_nan_text_and_empty_cells_become_na(self):
        df = read_sheets(write(MD))["수불요약"]
        self.assertTrue(df["Unnamed: 0"].isna().all())
        self.assertEqual(df.iloc[1, 2], "100")                    # 값은 문자열 그대로 (형 변환은 정제 단계)

    def test_markdown_escapes_are_removed_in_header_and_cells(self):
        df = read_sheet(write(MD), SHEET)
        self.assertIn("객수_합계", df.columns)
        self.assertNotIn("객수\\_합계", df.columns)
        self.assertIn("콜라_캔", set(df["메뉴명"].dropna()))

    def test_empty_sheet_keeps_columns(self):
        df = read_sheets(write(MD))["빈시트"]
        self.assertEqual((list(df.columns), len(df)), (["a", "b"], 0))

    def test_escaped_pipe_does_not_split_a_cell(self):
        p = write("## s\n| a | b |\n| --- | --- |\n| x\\|y | z |\n")
        self.assertEqual(read_sheet(p, "s").iloc[0].tolist(), ["x|y", "z"])

    def test_inconsistent_row_width_is_reported_with_line_number(self):
        p = write("## s\n| a | b |\n| --- | --- |\n| 1 | 2 | 3 |\n")
        with self.assertRaisesRegex(ValueError, "4번째 줄"):
            read_sheet(p, "s")

    def test_unknown_sheet_and_missing_file(self):
        with self.assertRaises(KeyError):
            read_sheet(write(MD), "없는시트")
        with self.assertRaises(FileNotFoundError):
            read_sheets(Path("/no/such/file.md"))


class CleanSales(unittest.TestCase):
    def setUp(self):
        self.raw = read_sheet(write(MD), SHEET)
        self.clean, self.report = clean_sales_detail(self.raw)

    def test_no_missing_values_left_and_rows_kept(self):
        self.assertEqual(int(self.clean.isna().sum().sum()), 0)
        self.assertEqual(len(self.clean), len(self.raw))          # dropna 하지 않음

    def test_text_columns_get_meaningful_labels(self):
        c = self.clean
        self.assertEqual(c["취소구분"].tolist(), [FILL_TEXT["취소구분"], FILL_TEXT["취소구분"], "주문취소", "매출취소"])
        self.assertEqual(c["할인수단"].tolist()[0], FILL_TEXT["할인수단"])
        self.assertEqual(c["할인수단"].tolist()[1], "비율할인-멤버십10%")          # 있는 값은 그대로
        self.assertEqual(c["객층"].tolist()[0], FILL_TEXT["객층"])
        self.assertEqual(c["객층"].tolist()[2], "내국인(남자) 1")

    def test_payment_blank_means_no_payment_only_when_actual_sales_is_zero(self):
        self.assertEqual(self.clean["결제수단"].tolist(), ["신용카드", FILL_TEXT["결제수단"], FILL_TEXT["결제수단"], "현금"])
        bad = self.raw.copy()
        bad.loc[0, "결제수단"] = pd.NA                             # 실매출_합계 21000 인데 결제수단 없음 = 진짜 결측
        with self.assertRaises(UnhandledMissingError) as cm:
            clean_sales_detail(bad)
        self.assertIn("결제수단", str(cm.exception))

    def test_cancelled_order_row_without_menu_is_kept_and_labeled(self):
        row = self.clean.iloc[2]
        for col in ("대분류명", "메뉴명", "과/면세"):
            self.assertEqual(row[col], CANCEL_ROW_TEXT)
        self.assertEqual(row["메뉴코드"], CANCEL_ROW_TEXT)
        self.assertEqual(row["주문번호"], 0)
        self.assertEqual(self.clean["취소구분"].value_counts()["주문취소"], 1)    # 취소 건수가 유지됨

    def test_types_are_normalized(self):
        c = self.clean
        self.assertEqual(c["주문번호"].tolist(), [1, 2, 0, 1])                     # '1.0' -> 1
        self.assertEqual(c["메뉴코드"].tolist()[0], "10670200")                    # 'xxx.0' -> 'xxx' (문자 ID)
        for col in ("단가", "수량", "총매출", "객수_합계"):
            self.assertTrue(pd.api.types.is_integer_dtype(c[col]), col)

    def test_amounts_are_unchanged(self):
        before = self.raw[["총매출", "할인", "실매출"]].astype(float).sum()
        after = self.clean[["총매출", "할인", "실매출"]].sum()
        self.assertEqual(before.tolist(), after.tolist())

    def test_report_lists_each_rule_with_counts(self):
        r = self.report.set_index("열")
        self.assertEqual(int(r.loc["취소구분", "채운 개수"]), 2)
        self.assertEqual(r.loc["취소구분", "채운 값"], FILL_TEXT["취소구분"])
        self.assertEqual(int(r.loc["결제수단", "채운 개수"]), 2)
        self.assertEqual(int(r.loc["메뉴명", "채운 개수"]), 1)
        self.assertEqual(int(r["채운 개수"].sum()), int(self.raw.isna().sum().sum()))   # 빠짐없이 설명됨

    def test_unknown_missing_column_is_not_filled_silently(self):
        raw = self.raw.copy()
        raw.loc[1, "단가"] = pd.NA
        with self.assertRaises(UnhandledMissingError) as cm:
            clean_sales_detail(raw)
        self.assertIn("단가", str(cm.exception))

    def test_cleaning_is_idempotent(self):
        again, report = clean_sales_detail(self.clean.astype(object).where(self.clean.notna(), pd.NA).astype(str))
        self.assertEqual(int(report["채운 개수"].sum()) if len(report) else 0, 0)


REAL = Path(__file__).resolve().parent / "data" / "f_b_menu_data.md"


@unittest.skipUnless(REAL.exists(), "실제 데이터 파일이 없으면 건너뜀")
class RealFile(unittest.TestCase):
    def test_real_sheet_cleans_without_losing_rows_or_money(self):
        raw = read_sheet(REAL, SHEET)
        clean, report = clean_sales_detail(raw)
        self.assertEqual(len(clean), len(raw))
        self.assertEqual(int(clean.isna().sum().sum()), 0)
        for col in ("총매출", "할인", "실매출", "순매출", "부가세"):
            self.assertEqual(float(pd.to_numeric(raw[col]).sum()), float(clean[col].sum()), col)
        self.assertEqual(int(report["채운 개수"].sum()), int(raw.isna().sum().sum()))


if __name__ == "__main__":
    unittest.main()
