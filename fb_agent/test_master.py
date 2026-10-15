import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from converter import normalize_unit, parse_count, to_boxes, to_grams, unit_to_grams
from data import DEFAULT_CALENDAR, ITEMS, ITEMS_BY_CODE, SAMPLE_COUNTS, SUPPLIERS
from errors import InvalidInputError
from importer import TEMPLATE_CSV, parse_inventory_file
from insights import build_table, recommendations, sample_stock_g, stock_from_table
from master import ITEM_COLUMNS, item_rows, load_items, load_master, load_suppliers, to_json
from menu import STORES
from models import Item, Supplier, fmt_amount
from reorder import recommend, safety_stock

WED = date(2026, 10, 14)

# 요구사항 2번: 매장 소모품 및 위생용품 (이름에 포함되어야 하는 키워드)
SUPPLIES = {
    "포장·용기": ["용기(대)", "용기(중)", "용기(소)", "냅킨", "물티슈", "빨대(종이)", "빨대(플라스틱)", "테이크아웃 컵", "컵 뚜껑", "종이쇼핑백"],
    "주방/홀 위생용품": ["위생장갑(니트릴)", "위생장갑(비닐)", "니트릴 고무장갑", "롤비닐", "주방세제", "락스", "키친타월", "수세미", "종이호일"],
    "지류·기타": ["영수증 감열지", "홀 행주", "주방 행주", "쓰레기봉투(50L)", "쓰레기봉투(100L)"],
}
EXISTING_FOOD = {"단무지", "춘장", "짜사이", "청양고추"}


def write_csv(path: Path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class Dataset(unittest.TestCase):
    def test_all_requested_supplies_exist_under_their_category(self):
        for mid, keywords in SUPPLIES.items():
            names = [n for n, it in ITEMS.items() if it.mid == mid]
            for k in keywords:
                self.assertTrue(any(k in n for n in names), f"[{mid}] '{k}' 없음")
            self.assertEqual(len(names), len(keywords), f"[{mid}] 요구하지 않은 품목이 섞임: {names}")

    def test_new_food_ingredients_are_not_added(self):
        """요구사항 1번(식자재 확충)은 적용하지 않기로 했다: 식자재는 기존 4개뿐."""
        food = {n for n, it in ITEMS.items() if it.major == "식자재"}
        self.assertEqual(food, EXISTING_FOOD)
        for absent in ("양파", "삼겹살", "우유", "치킨스톡", "간장", "에스프레소 원두"):
            self.assertNotIn(absent, ITEMS)

    def test_every_item_has_all_required_fields(self):
        codes = set()
        for it in ITEMS.values():
            self.assertTrue(it.code and it.code not in codes, it.name)
            codes.add(it.code)
            self.assertIn(it.major, ("식자재", "소모품"))
            self.assertTrue(it.mid and "/PK" in it.spec, it.name)
            self.assertGreaterEqual(it.safety_stock_g, 0)
            self.assertGreaterEqual(it.current_stock, 0)
            self.assertGreaterEqual(it.lead_time_days, 0)
            self.assertTrue(it.supplier.name)
        self.assertEqual(len(ITEMS_BY_CODE), len(ITEMS))

    def test_export_has_requested_columns_in_order(self):
        row = item_rows(ITEMS.values())[0]
        self.assertEqual(list(row)[:4], ["품목코드", "품목명", "대분류", "중분류"])
        for col in ("기본규격/단위", "안전재고량", "현재재고량", "리드타임(일)", "거래처"):
            self.assertIn(col, row)
        import json
        self.assertEqual(len(json.loads(to_json(ITEMS.values()))), len(ITEMS))

    def test_existing_items_keep_their_original_values(self):
        j = ITEMS["짜사이"]
        self.assertEqual((j.pk_weight_g, j.box_pk, j.daily_usage_g, j.supplier.name, j.lead_time_days), (1000, 10, 450, "A식자재", 1))
        self.assertEqual(SAMPLE_COUNTS["짜사이"][:2], (0, 1))
        self.assertEqual(ITEMS["청양고추"].ea_weight_g, 10)
        self.assertEqual(ITEMS["춘장"].daily_usage_g, 0)
        self.assertEqual(SUPPLIERS["C농산"].lead_time_days, 3)

    def test_supplies_use_count_and_volume_units(self):
        self.assertEqual(ITEMS["냅킨"].base_unit, "장")
        self.assertEqual(ITEMS["주방세제"].base_unit, "ml")
        self.assertEqual(ITEMS["주방용 키친타월"].base_unit, "롤")
        self.assertEqual(ITEMS["냅킨"].spec, "500장/PK · 10PK/BOX")
        self.assertEqual(ITEMS["주방세제"].spec, "4L/PK · 4PK/BOX")

    def test_sample_stock_varies_by_store_but_first_store_is_master(self):
        base = sample_stock_g(STORES[0])
        self.assertEqual(base, {n: float(it.current_stock) for n, it in ITEMS.items()})
        self.assertNotEqual(sample_stock_g(STORES[1]), base)
        self.assertEqual(sample_stock_g(STORES[1]), sample_stock_g(STORES[1]))     # 결정적

    def test_sample_status_is_mixed_not_all_urgent(self):
        recs = recommendations(sample_stock_g(STORES[0]), WED, DEFAULT_CALENDAR)
        st = [r.status for r in recs]
        self.assertGreaterEqual(st.count("OK"), len(st) // 2)
        self.assertGreaterEqual(st.count("URGENT"), 1)


class Units(unittest.TestCase):
    def test_volume_and_count_inputs(self):
        self.assertEqual(parse_count(ITEMS["주방세제"], "2L"), 2000)
        self.assertEqual(parse_count(ITEMS["주방세제"], "1PK 500ml"), 4500)
        self.assertEqual(parse_count(ITEMS["냅킨"], "1BOX 2PK 30장"), 5000 + 1000 + 30)
        self.assertEqual(unit_to_grams(ITEMS["냅킨"], 1, "CTN"), 5000)
        self.assertEqual(parse_count(ITEMS["종이쇼핑백"], "10개"), 10)

    def test_wrong_unit_for_item_is_rejected(self):
        for item, text in (("냅킨", "1kg"), ("냅킨", "300g"), ("주방세제", "1kg"), ("락스", "5g"), ("짜사이", "1L"), ("짜사이", "300ml")):
            with self.assertRaises(InvalidInputError, msg=f"{item} {text}"):
                parse_count(ITEMS[item], text)

    def test_to_grams_counts_loose_in_base_unit(self):
        n = ITEMS["냅킨"]
        self.assertEqual(to_grams(n, packs=2, loose_g=30, boxes=1), 5000 + 1000 + 30)
        self.assertEqual(to_boxes(n, 6030), (1, 2, 30))     # 5000(BOX) + 2×500(PK) + 30
        with self.assertRaises(InvalidInputError):
            to_grams(n, 0, -1)

    def test_formatting(self):
        self.assertEqual(fmt_amount(1800, "ml"), "1.8L")
        self.assertEqual(fmt_amount(500, "ml"), "500ml")
        self.assertEqual(fmt_amount(5000, "g"), "5kg")
        self.assertEqual(fmt_amount(100, "장"), "100장")
        self.assertEqual(ITEMS["냅킨"].fmt(900), "900장")
        self.assertEqual(normalize_unit("카톤"), "BOX")


class Recommend(unittest.TestCase):
    def supplier(self, lead=1):
        return Supplier("T", frozenset(range(6)), lead)

    def item(self, **kw):
        base = dict(name="x", pk_weight_g=100, daily_usage_g=10, supplier=self.supplier(), box_pk=1, base_unit="개", ea_weight_g=1)
        return Item(**{**base, **kw})

    def test_safety_stock_defaults_and_override(self):
        self.assertEqual(safety_stock(self.item()), 10)                          # 일 소비량 × 1일
        self.assertEqual(safety_stock(self.item(safety_stock_g=55)), 55)
        self.assertEqual(safety_stock(self.item(safety_stock_g=55), safety_days=2), 20)   # 명시 인자가 우선

    def test_larger_safety_stock_orders_more_and_earlier(self):
        small, big = self.item(safety_stock_g=10), self.item(safety_stock_g=300)
        a, b = recommend(small, 500, WED, DEFAULT_CALENDAR), recommend(big, 500, WED, DEFAULT_CALENDAR)
        self.assertGreaterEqual(b.order_packs, a.order_packs)
        self.assertLessEqual(b.order_date or WED, a.order_date or WED)

    def test_item_lead_time_overrides_supplier(self):
        self.assertEqual(self.item().lead_time_days, 1)
        self.assertEqual(self.item(lead_time_override=4).lead_time_days, 4)
        r = recommend(self.item(lead_time_override=4), 100, WED, DEFAULT_CALENDAR)
        self.assertGreaterEqual((r.arrival_date - r.order_date).days, 4)

    def test_huge_stock_does_not_overflow_dates(self):
        r = recommend(self.item(daily_usage_g=1), 10**12, WED, DEFAULT_CALENDAR)
        self.assertEqual(r.status, "OK")

    def test_validation(self):
        for kw in (dict(base_unit="kg"), dict(safety_stock_g=-1), dict(current_stock=-1), dict(lead_time_override=-1)):
            with self.assertRaises(InvalidInputError, msg=str(kw)):
                self.item(**kw)


class Loader(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write_csv(self.tmp / "suppliers.csv", ["거래처명", "발주요일", "기본리드타임", "취급분야"],
                  [["갑", "월수금", 2, ""], ["을", "화", 5, ""]])
        self.header = ITEM_COLUMNS

    def items(self, rows):
        write_csv(self.tmp / "items.csv", self.header, rows)
        return load_items(load_suppliers(self.tmp / "suppliers.csv"), self.tmp / "items.csv")

    def row(self, **over):
        base = {"품목코드": "C1", "품목명": "냅킨", "대분류": "소모품", "중분류": "포장", "기본단위": "장", "PK당수량": 500, "BOX당PK": 10,
                "EA당수량": "", "일소비량": 900, "안전재고량": 3600, "현재재고량": 10000, "리드타임": "", "거래처": "갑"}
        base.update(over)
        return [base[c] for c in self.header]

    def test_valid_row_and_defaults(self):
        it = self.items([self.row()])["냅킨"]
        self.assertEqual((it.ea_weight_g, it.lead_time_days, it.base_unit), (1, 2, "장"))   # 개수 품목 EA=1, 리드타임=거래처 기본
        self.assertEqual(self.items([self.row(리드타임=7)])["냅킨"].lead_time_days, 7)      # 품목별 리드타임 우선
        g = self.items([self.row(기본단위="g", EA당수량="")])["냅킨"]
        self.assertEqual(g.ea_weight_g, 0)                                                  # g·ml 품목은 EA 미지원이 기본

    def test_errors_name_the_row_and_reason(self):
        cases = [
            ([self.row(), self.row(품목명="다른")], "코드가 중복"),
            ([self.row(), self.row(품목코드="C2")], "품목명이 중복"),
            ([self.row(거래처="병")], "등록되지 않은 거래처"),
            ([self.row(기본단위="kg")], "기본단위"),
            ([self.row(PK당수량="abc")], "숫자가 아닙니다"),
            ([self.row(PK당수량=0)], "0보다 커야"),
            ([self.row(안전재고량=-1)], "음수"),
            ([self.row(리드타임="1.5")], "정수"),
            ([self.row(일소비량="")], "비어 있습니다"),
            ([self.row(품목코드="")], "필수"),
        ]
        for rows, msg in cases:
            with self.assertRaises(InvalidInputError, msg=msg) as cm:
                self.items(rows)
            self.assertIn(msg, str(cm.exception))
            self.assertIn("행", str(cm.exception))

    def test_missing_column_empty_file_and_bad_supplier_rows(self):
        write_csv(self.tmp / "items.csv", ["품목코드", "품목명"], [["a", "b"]])
        with self.assertRaises(InvalidInputError):
            load_items(load_suppliers(self.tmp / "suppliers.csv"), self.tmp / "items.csv")
        with self.assertRaises(InvalidInputError):
            self.items([])
        write_csv(self.tmp / "suppliers.csv", ["거래처명", "발주요일", "기본리드타임", "취급분야"], [["갑", "월X", 1, ""]])
        with self.assertRaises(InvalidInputError):
            load_suppliers(self.tmp / "suppliers.csv")

    def test_cp949_file_is_readable(self):
        (self.tmp / "suppliers.csv").write_bytes("거래처명,발주요일,기본리드타임,취급분야\n갑,월,1,\n".encode("cp949"))
        self.assertIn("갑", load_suppliers(self.tmp / "suppliers.csv"))

    def test_shipped_master_loads(self):
        suppliers, items = load_master()
        self.assertEqual(set(suppliers), {i.supplier.name for i in items.values()})


class TableAndImport(unittest.TestCase):
    def test_table_roundtrip_matches_stock(self):
        stock = sample_stock_g(STORES[0])
        back, errors = stock_from_table(build_table(stock))
        self.assertEqual(errors, [])
        for n, g in stock.items():
            self.assertAlmostEqual(back[n], g, places=1, msg=n)

    def test_bad_cell_is_reported_per_item(self):
        t = build_table(sample_stock_g(STORES[0]))
        t.loc[t["품목"] == "냅킨", "PK"] = -1
        stock, errors = stock_from_table(t)
        self.assertEqual([e[0] for e in errors], ["냅킨"])
        self.assertNotIn("냅킨", stock)

    def test_template_covers_every_item_and_roundtrips(self):
        r = parse_inventory_file("t.csv", TEMPLATE_CSV.encode("utf-8"), ITEMS)
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.missing, [])
        for n, it in ITEMS.items():
            self.assertAlmostEqual(r.grams[n], it.current_stock, places=1, msg=n)

    def test_import_by_item_code_and_loose_in_base_unit(self):
        r = parse_inventory_file("a.csv", "품목코드,BOX,PK,낱개\nS-PKG-004,1,2,30\nF-CHN-003,0,1,300\n".encode(), ITEMS)
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.grams["냅킨"], 5000 + 1000 + 30)
        self.assertEqual(r.grams["짜사이"], 1300)

    def test_name_wins_over_code_and_unknown_code_is_reported(self):
        r = parse_inventory_file("a.csv", "품목코드,품목명,PK\nZZZ,냅킨,2\nS-XXX,,1\n".encode(), ITEMS)
        self.assertEqual(r.grams, {"냅킨": 1000})
        self.assertEqual(len(r.errors), 1)

    def test_text_memo_with_supply_units(self):
        r = parse_inventory_file("memo.txt", "냅킨 2PK 30장\n주방세제: 1.5L\n".encode(), ITEMS)
        self.assertEqual(r.grams, {"냅킨": 1030, "주방세제": 1500})


if __name__ == "__main__":
    unittest.main()
