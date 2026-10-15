import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import io
import unittest

import pandas as pd

from data import ITEMS
from errors import InvalidInputError
from importer import TEMPLATE_CSV, parse_inventory_file


def csv(text, enc="utf-8"):
    return text.encode(enc)


def parse(text, name="a.csv", enc="utf-8"):
    return parse_inventory_file(name, csv(text, enc), ITEMS)


class Wide(unittest.TestCase):
    def test_template_matches_sample(self):
        r = parse(TEMPLATE_CSV)
        self.assertTrue(r.ok)
        self.assertEqual(r.grams["짜사이"], 1300)
        self.assertEqual(r.grams["단무지"], 8400)
        self.assertEqual(r.missing, [])

    def test_aliases_spacing_and_units(self):
        r = parse("상품명,박스,팩,잔량\n 짜 사이 ,1,2,300\n")
        self.assertEqual(r.grams["짜사이"], 10000 + 2000 + 300)

    def test_cp949_and_bom(self):
        self.assertEqual(parse("품목,PK\n짜사이,2\n", enc="cp949").grams["짜사이"], 2000)
        self.assertEqual(parse("품목,PK\n짜사이,2\n", enc="utf-8-sig").grams["짜사이"], 2000)

    def test_thousand_separator_and_blank_cells(self):
        r = parse('품목,PK,낱개(g)\n짜사이,,"1,500"\n')
        self.assertEqual(r.grams["짜사이"], 1500)


class Other(unittest.TestCase):
    def test_free_text_column(self):
        r = parse("품목,재고\n짜사이,1BOX 2pk 300g\n청양고추,10EA\n")
        self.assertEqual(r.grams, {"짜사이": 12300, "청양고추": 100})

    def test_long_format_sums_duplicates(self):
        r = parse("품목,수량,단위\n짜사이,1,PK\n짜사이,300,g\n")
        self.assertEqual(r.grams["짜사이"], 1300)
        self.assertEqual(len(r.warnings), 1)

    def test_title_rows_before_header(self):
        r = parse("10월 실사,,\n,,\n품목,PK,낱개(g)\n짜사이,1,0\n")
        self.assertEqual(r.grams["짜사이"], 1000)
        self.assertEqual(r.errors, [])

    def test_xlsx(self):
        buf = io.BytesIO()
        pd.DataFrame({"품목": ["짜사이"], "PK": [3]}).to_excel(buf, index=False)
        r = parse_inventory_file("a.xlsx", buf.getvalue(), ITEMS)
        self.assertEqual(r.grams["짜사이"], 3000)


class Formats(unittest.TestCase):
    def test_json_list_and_dict(self):
        r = parse('[{"품목":"짜사이","PK":1,"낱개(g)":300},{"품목":"춘장","재고":"2pk"}]', "a.json")
        self.assertEqual(r.grams, {"짜사이": 1300, "춘장": 4000})
        r = parse('{"짜사이": "1pk 300g", "단무지": {"PK": 3}}', "no_ext")
        self.assertEqual(r.grams, {"짜사이": 1300, "단무지": 8400})

    def test_bad_json(self):
        with self.assertRaises(InvalidInputError): parse('{"a": ', "a.json")
        with self.assertRaises(InvalidInputError): parse('[1, 2]', "a.json")

    def test_memo_lines(self):
        r = parse("10/15 실사\n짜사이 1pk 300g\n단무지: 3pk\n- 춘장 2BOX\n김치 1pk\n")
        self.assertEqual(r.grams["짜사이"], 1300)
        self.assertEqual(r.grams["단무지"], 8400)
        self.assertEqual(r.grams["춘장"], 2 * 12000)
        bad = {e.row: e.item for e in r.errors}
        self.assertEqual(bad[5], "김치")           # 원본 줄 번호 유지
        self.assertEqual(bad[1], "10/15 실사")

    def test_markdown_table(self):
        r = parse("| 품목 | PK | 낱개(g) |\n|---|---|---|\n| 짜사이 | 1 | 300 |\n")
        self.assertEqual(r.grams["짜사이"], 1300)

    def test_tsv_and_semicolon(self):
        self.assertEqual(parse("품목\tPK\n짜사이\t2\n").grams["짜사이"], 2000)
        self.assertEqual(parse("품목;PK\n짜사이;2\n").grams["짜사이"], 2000)

    def test_content_sniffing_ignores_extension(self):
        buf = io.BytesIO()
        pd.DataFrame({"품목": ["짜사이"], "PK": [3]}).to_excel(buf, index=False)
        self.assertEqual(parse_inventory_file("재고.dat", buf.getvalue(), ITEMS).grams["짜사이"], 3000)
        self.assertEqual(parse("품목,PK\n짜사이,1\n", "재고.xlsx").grams["짜사이"], 1000)

    def test_xlsx_picks_valid_sheet(self):
        buf = io.BytesIO()
        with pd.ExcelWriter(buf) as w:
            pd.DataFrame({"메모": ["안내문"]}).to_excel(w, sheet_name="설명", index=False)
            pd.DataFrame({"품목": ["짜사이"], "PK": [2]}).to_excel(w, sheet_name="실사", index=False)
        self.assertEqual(parse_inventory_file("a.xlsx", buf.getvalue(), ITEMS).grams["짜사이"], 2000)

    def test_ods(self):
        buf = io.BytesIO()
        pd.DataFrame({"품목": ["짜사이"], "PK": [4]}).to_excel(buf, index=False, engine="odf")
        self.assertEqual(parse_inventory_file("a.ods", buf.getvalue(), ITEMS).grams["짜사이"], 4000)

    def test_unsupported_binaries(self):
        for blob in (b"%PDF-1.4 ...", b"\x89PNG\r\n", b"\xff\xd8\xff\xe0"):
            with self.assertRaises(InvalidInputError): parse_inventory_file("x", blob, ITEMS)


class Errors(unittest.TestCase):
    def test_row_errors_do_not_stop_others(self):
        r = parse("품목,PK\n짜사이,-1\n단무지,abc\n김치,1\n춘장,2\n")
        self.assertEqual([e.row for e in r.errors], [2, 3, 4])
        self.assertEqual(r.grams, {"춘장": 4000})
        self.assertNotIn("짜사이", r.missing)  # 오류 품목은 '파일에 없음'이 아님

    def test_unknown_item_suggests_close_match(self):
        r = parse("품목,PK\n짜사어,1\n")
        self.assertIn("짜사이", r.errors[0].message)

    def test_unsupported_ea(self):
        r = parse("품목,EA\n짜사이,5\n")
        self.assertIn("EA", r.errors[0].message)

    def test_unitless_number_in_qty_rejected(self):
        r = parse("품목,수량\n짜사이,5\n")
        self.assertFalse(r.ok)

    def test_file_level_errors(self):
        for name, data in [("a.csv", b""), ("a.csv", csv("품목\n짜사이\n")), ("a.csv", csv("foo,bar\n1,2\n")),
                           ("a.xlsx", b"not excel"), ("a.csv", csv("가나다\n라마바\n"))]:
            with self.assertRaises(InvalidInputError, msg=name):
                parse_inventory_file(name, data, ITEMS)


if __name__ == "__main__":
    unittest.main()
