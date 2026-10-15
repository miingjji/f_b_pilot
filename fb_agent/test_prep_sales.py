import unittest
from pathlib import Path

import pandas as pd

from prep.blocks import UnhandledMissingError
from prep.sales_sheets import SHEET_SALES_SUMMARY, clean_sales_summary

NA = pd.NA


def grid(rows, ncols=19):
    data = [list(r) + [NA] * (ncols - len(r)) for r in rows]
    return pd.DataFrame(data, columns=[f"c{i}" for i in range(ncols)], dtype=object)


def row(no, code, name, uni, qty, amt, dead="0", test="0", staff="0", bom="1 EA"):
    r = [NA] * 19
    r[1:10] = [str(no), code, name, uni, str(qty), str(amt), dead, test, staff]
    r[15:19] = [code, name, uni, bom]                      # 오른쪽 조회표는 왼쪽과 같은 값
    return r


def sheet(body, totals=(5, 300, 1, 0, 0)):
    head = [NA] * 19
    head[1:10] = ["순번", "상품코드", "상품명", "상품명 통일", "판매수량", "판매금액", "Dead", "테스트", "직원중식"]
    head[15:19] = ["품목코드", "품명", "상품명 통일", "BOM유무"]
    first = [NA, "제품별 수량", NA, NA, NA, "9", NA, "1", "2", "0"]
    rows = [first, [], head, *body,
            [NA, "1234"], [NA, "1235"],                                        # 순번만 있는 빈 양식 행
            [],
            [NA, NA, NA, "합계", NA, *map(str, totals)],
            [],
            [NA, NA, NA, NA, "매출입력", "7", "250"]]
    return grid(rows)


BODY = [
    row(1, "A1", "주문메모", "ETC", 10, 0, dead="3"),             # 합계행이 제외하는 첫 2행
    row(2, "A2", "10분뒤", "ETC", 1, 0),
    row(3, "B1", "세트", "세트메뉴명칭", 2, 200, dead="1"),
    row(4, "B2", "콜라", "사이다", 3, 100, bom=NA),             # BOM유무 비어 있음
    row(5, "B1", "세트", "세트메뉴명칭", 2, 200, dead="1"),       # 위 3번과 완전히 같은 중복
]


class SalesSummary(unittest.TestCase):
    def setUp(self):
        # 합계행: 순번3~ 수량 7(2+3+2), 금액 500, Dead 2, 테스트 0, 직원중식 0 (첫 2행 제외 기준)
        self.raw = sheet(BODY, totals=(7, 500, 2, 0, 0))
        self.clean, self.report, self.info = clean_sales_summary(self.raw)

    def test_only_product_rows_kept_without_template_rows_or_totals(self):
        self.assertEqual(len(self.clean), 5)
        self.assertEqual(self.clean["순번"].tolist(), [1, 2, 3, 4, 5])
        self.assertEqual(int(self.clean.isna().sum().sum()), 0)

    def test_empty_spacer_columns_and_duplicate_lookup_columns_are_dropped(self):
        cols = list(self.clean.columns)
        self.assertEqual(cols, ["순번", "상품코드", "상품명", "상품명통일", "판매수량", "판매금액", "Dead", "테스트", "직원중식",
                                "조회_BOM유무", "중복행"])
        self.assertTrue(any("조회_품목코드" in d for d in self.info["dropped"]))   # 왼쪽 표와 같아서 삭제

    def test_lookup_columns_that_differ_are_kept(self):
        raw = sheet(BODY, totals=(7, 500, 2, 0, 0))
        raw.iat[3, 16] = "다른이름"                                                  # 조회_품명이 달라짐
        clean, _, _ = clean_sales_summary(raw)
        self.assertIn("조회_품명", clean.columns)

    def test_bom_blank_gets_label(self):
        self.assertEqual(self.clean["조회_BOM유무"].tolist()[3], "미기재")
        self.assertEqual(self.clean["조회_BOM유무"].tolist()[0], "1 EA")
        r = self.report.set_index("열")
        self.assertEqual(int(r.loc["조회_BOM유무", "채운 개수"]), 1)

    def test_numbers_are_numeric_and_codes_text(self):
        self.assertTrue(pd.api.types.is_integer_dtype(self.clean["판매금액"]))
        self.assertEqual(self.clean["상품코드"].tolist()[0], "A1")

    def test_duplicates_are_flagged_not_deleted(self):
        self.assertEqual(self.clean["중복행"].tolist(), [False, False, False, False, True])
        self.assertEqual(self.info["duplicates"]["rows"], 1)
        self.assertEqual(self.info["duplicates"]["amount"], 200)

    def test_totals_row_checks(self):
        checks = {c["항목"]: c for c in self.info["checks"]}
        self.assertTrue(all(c["ok"] for c in checks.values()), checks)
        self.assertIn("판매금액 합계", checks)
        self.assertIn("판매수량 합계 (순번 1~2 제외: 합계행의 계산 범위)", checks)
        _, _, bad = clean_sales_summary(sheet(BODY, totals=(7, 999, 2, 0, 0)))
        self.assertFalse(all(c["ok"] for c in bad["checks"]))

    def test_amount_without_duplicates_is_reported_for_cross_checks(self):
        self.assertEqual(self.info["amount_total"], 500)
        self.assertEqual(self.info["amount_without_duplicates"], 300)
        self.assertEqual(self.info["reconcile_rows"]["매출입력"], {"수량": 7.0, "금액": 250.0})

    def test_unexplained_missing_is_rejected(self):
        raw = sheet(BODY, totals=(7, 500, 2, 0, 0))
        raw.iat[4, 6] = NA                                                           # 판매금액 비어 있음
        with self.assertRaises(UnhandledMissingError):
            clean_sales_summary(raw)

    def test_missing_header_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "순번"):
            clean_sales_summary(grid([[NA, "아무거나"]]))


REAL = Path(__file__).resolve().parent / "data" / "f_b_menu_data.md"


@unittest.skipUnless(REAL.exists(), "실제 데이터 파일이 없으면 건너뜀")
class RealFile(unittest.TestCase):
    def test_real_sheet(self):
        from prep.md_tables import read_sheet
        clean, report, info = clean_sales_summary(read_sheet(REAL, SHEET_SALES_SUMMARY))
        self.assertEqual(len(clean), 1149)
        self.assertEqual(int(clean.isna().sum().sum()), 0)
        failed = [c for c in info["checks"] if not c["ok"]]
        self.assertEqual(failed, [], failed)
        self.assertEqual(int(clean["중복행"].sum()), 14)
        self.assertEqual(info["duplicates"]["amount"], 1355156)
        self.assertEqual(info["amount_without_duplicates"], 169804335)            # 매출입력 순매출_합계와 일치


if __name__ == "__main__":
    unittest.main()
