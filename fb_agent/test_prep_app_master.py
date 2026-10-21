import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from master import load_master
from prep.app_master import (build_app_master, order_weekdays, read_standard_usage, safety_days, write_master)

NA = pd.NA
ORG_COLS = ["발주처", "원거래처", "품목구분", "계정명", "품목코드_RMS", "품목코드_CK", "품목코드_매장", "품명", "규격", "환산단위", "당월입고수량",
            "당월입고중량_g", "당월입고금액", "실사재고수량", "실사재고중량_g", "리드타임_적용_일", "리드타임_출처", "입고내역_있음", "실사재고_있음"]


def item(supplier, kind, acct, code, name, unit, recv_qty=0.0, recv_g=0.0, stock_qty=0.0, stock_g=0.0, lead=1, src="가상"):
    return [supplier, supplier, kind, acct, code, "없음", "없음", name, "1kg/pk", unit, recv_qty, recv_g, 0.0, stock_qty, stock_g, lead, src, True, True]


ITEMS = pd.DataFrame([
    item("대풍농산", "식재료", "원재료", "F1", "양파", 1000.0, recv_qty=62, recv_g=62000.0, stock_qty=3, stock_g=3000.0),       # 이론사용 있음
    item("대풍농산", "식재료", "원재료", "F2", "당근", 1000.0, recv_qty=31, recv_g=31000.0, stock_qty=0, stock_g=0.0),         # 이론사용 없음, 입고만 있음 / 재고 0
    item("바이맥스", "소모품", "저장품", "S1", "냅킨", 1.0, recv_qty=62, recv_g=62.0, lead=3),                               # 소모품: 입고 있음, 재고 0
    item("바이맥스", "소모품", "저장품", "S2", "행주", 1.0, recv_qty=0, stock_qty=5.0, stock_g=5.0, lead=3),                  # 재고만 있음
    item("바이맥스", "소모품", "저장품", "S3", "빨대", 1.0, lead=3),                                                         # 근거 없음
    item("CK", "식재료", "반제품", "F3", "게살", 500.0, recv_g=15500.0, stock_g=500.0, lead=1),
    item("CK", "식재료", "반제품", "NO", "이름없는코드", 500.0, lead=1),                                                      # RMS 코드 '없음'
    item("CK", "식재료", "반제품", "F4", "양파", 500.0, lead=2),                                                              # 이름 중복
], columns=ORG_COLS)
ITEMS.loc[ITEMS["품목코드_RMS"] == "NO", "품목코드_RMS"] = "없음"

SUPPLIERS = pd.DataFrame({
    "업체명": ["대풍농산", "바이맥스", "CK"], "업체유형": ["업체", "업체", "센트럴키친(CK)"], "취급구분": ["식재료", "소모품", "식재료"],
    "리드타임_적용_일": [1, 3, 1], "리드타임_출처": ["가상", "가상", "가상"],
})
STD = pd.DataFrame({"코드": ["F1", "F3"], "이론사용_g": [31000.0, 0.0]})                     # 양파만 실제 이론사용


class Weekdays(unittest.TestCase):
    def test_properties_hold_for_many_names_and_leads(self):
        for lead in (1, 2, 3, 4, 5):
            for name in [f"업체{i}" for i in range(30)]:
                for kind, stype in (("식재료", "업체"), ("소모품", "업체")):
                    days = order_weekdays(name, lead, stype, kind)
                    idx = ["월화수목금토일".index(c) for c in days]
                    self.assertTrue(days and idx == sorted(set(idx)), (name, lead, days))
                    self.assertTrue(all(d <= 5 and (d + lead) % 7 != 6 for d in idx), (name, lead, days))   # 일요일 휴무라 일요일 입고가 되는 요일은 제외

    def test_counts_follow_rules_and_are_deterministic(self):
        self.assertEqual(len(order_weekdays("하나로축산", 1, "업체", "식재료")), 3)
        self.assertEqual(len(order_weekdays("롯데칠성", 2, "업체", "식재료")), 2)
        self.assertEqual(len(order_weekdays("다와포장", 4, "업체", "소모품")), 1)
        self.assertEqual(len(order_weekdays("CK", 1, "센트럴키친(CK)", "식재료")), 5)               # 월~금 (토 발주는 일요일 입고)
        self.assertEqual(len(order_weekdays("인터넷구매", 2, "온라인 구매처", "소모품")), 5)
        self.assertEqual(order_weekdays("가나다", 3, "업체", "소모품"), order_weekdays("가나다", 3, "업체", "소모품"))

    def test_different_suppliers_get_different_patterns(self):
        pats = {order_weekdays(f"식재료업체{i}", 1, "업체", "식재료") for i in range(30)}
        self.assertGreaterEqual(len(pats), 3)


class Policy(unittest.TestCase):
    def test_safety_days_grow_with_lead_time(self):
        self.assertEqual([safety_days(n) for n in (1, 2, 3, 4, 5)], [1, 1, 2, 2, 3])


class AppMaster(unittest.TestCase):
    def setUp(self):
        self.items, self.sup, self.info = build_app_master(ITEMS, SUPPLIERS, STD)

    def test_units_follow_conversion_factor(self):
        a = self.items[self.items["품목코드"] == "F1"].iloc[0]
        self.assertEqual((a["기본단위"], a["PK당수량"], a["BOX당PK"]), ("g", 1000, 1))
        s = self.items[self.items["품목코드"] == "S1"].iloc[0]
        self.assertEqual((s["기본단위"], s["PK당수량"], s["EA당수량"]), ("개", 1, 1))

    def test_usage_from_standard_usage_then_receipts_then_none(self):
        by = self.items.set_index("품목코드")
        self.assertEqual((by.loc["F1", "일소비량"], by.loc["F1", "일소비량_출처"]), (1000.0, "표준사용량"))      # 31000g / 31일
        self.assertEqual((by.loc["F2", "일소비량"], by.loc["F2", "일소비량_출처"]), (1000.0, "입고 기반 추정"))   # 31000g / 31일
        self.assertEqual((by.loc["S1", "일소비량"], by.loc["S1", "일소비량_출처"]), (2.0, "입고 기반 추정"))      # 62개 / 31일
        self.assertEqual((by.loc["S3", "일소비량"], by.loc["S3", "일소비량_출처"]), (0.0, "근거 없음"))
        self.assertEqual(by.loc["F3", "일소비량_출처"], "입고 기반 추정")                                       # 이론사용 0이면 입고로

    def test_stock_real_for_food_synthetic_for_uncounted_supplies(self):
        by = self.items.set_index("품목코드")
        self.assertEqual((by.loc["F1", "현재재고량"], by.loc["F1", "재고_출처"]), (3000.0, "실사재고"))
        self.assertEqual((by.loc["F2", "현재재고량"], by.loc["F2", "재고_출처"]), (0.0, "실사재고"))           # 식재료의 0은 실제 값
        s1 = by.loc["S1"]                                                                                      # 소모품 재고 0 + 사용 있음 -> 가상 재고
        self.assertEqual(s1["재고_출처"], "가상")
        self.assertTrue(2.0 * 10 <= s1["현재재고량"] <= 2.0 * 30)                                              # 일소비 × 10~30일
        self.assertEqual((by.loc["S2", "현재재고량"], by.loc["S2", "재고_출처"]), (5.0, "실사재고"))             # 센 재고는 실제
        self.assertEqual((by.loc["S3", "현재재고량"], by.loc["S3", "재고_출처"]), (0.0, "실사재고"))             # 쓰지 않는 소모품 0

    def test_stock_only_item_gets_synthetic_usage(self):
        r = self.items[self.items["품목코드"] == "S2"].iloc[0]
        self.assertEqual(r["일소비량_출처"], "가상")
        self.assertAlmostEqual(r["일소비량"], round(5.0 / 30, 4), places=4)

    def test_safety_stock_follows_lead_time(self):
        by = self.items.set_index("품목코드")
        self.assertEqual(by.loc["F1", "안전재고량"], 1000.0 * 1)             # D1 -> 1일치
        self.assertEqual(by.loc["S1", "안전재고량"], 2.0 * 2)               # D3 -> 2일치
        self.assertEqual(by.loc["S3", "안전재고량"], 0.0)

    def test_names_and_codes_are_unique_and_valid(self):
        self.assertEqual(self.items["품목명"].is_unique, True)
        self.assertEqual(self.items["품목코드"].is_unique, True)
        self.assertEqual(sorted(self.items[self.items["품목명"].str.startswith("양파")]["품목명"]), ["양파 (F1)", "양파 (F4)"])   # 중복 이름은 코드로 구분
        nocode = self.items[self.items["품목명"].str.contains("이름없는코드")].iloc[0]
        self.assertTrue(nocode["품목코드"].startswith("NC-"))                              # RMS 코드가 없는 품목은 임시 코드

    def test_lead_time_override_only_when_item_differs_from_supplier(self):
        raw = ITEMS.copy()
        raw.loc[raw["품목코드_RMS"] == "F1", ["리드타임_적용_일", "리드타임_출처"]] = [2, "품명 태그"]
        items, _, _ = build_app_master(raw, SUPPLIERS, STD)
        by = items.set_index("품목코드")
        self.assertEqual(by.loc["F1", "리드타임"], 2)                                        # 업체 기본(1)과 다르면 품목 값
        self.assertTrue(pd.isna(by.loc["F2", "리드타임"]) or by.loc["F2", "리드타임"] == "")   # 같으면 비움(업체 기본값 사용)

    def test_suppliers_table(self):
        s = self.sup.set_index("거래처명")
        self.assertEqual(set(s.index), {"대풍농산", "바이맥스", "CK"})
        self.assertEqual((s.loc["바이맥스", "기본리드타임"], s.loc["바이맥스", "발주요일_출처"]), (3, "가상"))
        self.assertTrue(all(c in "월화수목금토" for c in "".join(s["발주요일"])))

    def test_info_counts_sources(self):
        self.assertEqual(self.info["일소비량_출처"]["표준사용량"], 1)
        self.assertEqual(self.info["items"], len(ITEMS))

    def test_output_loads_with_the_app_master_loader(self):
        out = Path(tempfile.mkdtemp())
        write_master(self.items, self.sup, out)
        suppliers, items = load_master(out)
        self.assertEqual(len(items), len(ITEMS))
        self.assertEqual(set(suppliers), {"대풍농산", "바이맥스", "CK"})
        onion = items[self.items[self.items["품목코드"] == "F1"].iloc[0]["품목명"]]
        self.assertEqual((onion.base_unit, onion.daily_usage_g, onion.current_stock, onion.safety_stock_g), ("g", 1000.0, 3000.0, 1000.0))
        self.assertEqual(onion.lead_time_days, 1)
        nap = items[self.items[self.items["품목코드"] == "S1"].iloc[0]["품목명"]]
        self.assertEqual((nap.base_unit, nap.ea_weight_g, nap.lead_time_days), ("개", 1, 3))

    def test_no_missing_values_in_outputs(self):
        self.assertEqual(int(self.items.drop(columns=["리드타임"]).isna().sum().sum()), 0)
        self.assertEqual(int(self.sup.isna().sum().sum()), 0)


class StandardUsage(unittest.TestCase):
    def test_reads_total_column_by_anchor(self):
        rows = [
            [NA] * 4,
            [NA, "표준사용량 (g)", NA, NA, NA, NA, NA, NA, "구분", NA, NA, "합계"],
            [NA] * 8 + ["상품명 통일", "메뉴A", "메뉴B"],
            [NA] * 8 + ["판매량", "2", "3"],
            [NA, "계정명", NA, "품목코드(RMS)", NA, "거래처명", "규격", "품명", NA, "표준사용량(g)", "표준사용량(g)"],
            ["기본제공 재료", "원재료", "0", "F1", "x", "CK", "1kg", "양파", NA, "100", "50", "150"],
            [NA, "원재료", "0", "F2", "x", "CK", "1kg", "당근", NA, "0", "0", "0"],
            [NA, "원재료", "0", "없음", "x", "CK", "1kg", "무코드", NA, "5", "5", "10"],
        ]
        raw = pd.DataFrame([r + [NA] * (12 - len(r)) for r in rows], dtype=object)
        std = read_standard_usage(raw)
        self.assertEqual(dict(zip(std["코드"], std["이론사용_g"])), {"F1": 150.0, "F2": 0.0})   # 코드 없는 행은 제외

    def test_missing_anchor_raises(self):
        with self.assertRaises(ValueError):
            read_standard_usage(pd.DataFrame([[NA, "아무거나"]], dtype=object))


REAL = Path(__file__).resolve().parent / "data" / "f_b_menu_data.md"


@unittest.skipUnless(REAL.exists(), "실제 데이터 파일이 없으면 건너뜀")
class RealFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from prep.app_master import build_from_markdown
        cls.items, cls.sup, cls.info = build_from_markdown(REAL)

    def test_counts_and_sources(self):
        self.assertEqual(len(self.items), 903)
        self.assertEqual(len(self.sup), 45)
        self.assertEqual(self.info["일소비량_출처"]["표준사용량"], 148)
        self.assertEqual(sum(self.info["일소비량_출처"].values()), 903)
        self.assertTrue(self.items["품목명"].is_unique and self.items["품목코드"].is_unique)

    def test_loads_in_the_app_master_loader(self):
        out = Path(tempfile.mkdtemp())
        write_master(self.items, self.sup, out)
        suppliers, items = load_master(out)
        self.assertEqual((len(items), len(suppliers)), (903, 45))
        active = [i for i in items.values() if i.daily_usage_g > 0]
        src = self.info["일소비량_출처"]
        self.assertEqual(len(active), src["표준사용량"] + src["입고 기반 추정"] + src.get("가상", 0))   # 근거 없는 품목은 소비 없음(0)
        self.assertEqual(src["표준사용량"], 148)
        self.assertTrue(all(i.safety_stock_g is not None and i.current_stock is not None for i in items.values()))

    def test_real_stock_is_kept_for_food(self):
        food = self.items[self.items["대분류"] == "식재료"]
        self.assertTrue((food["재고_출처"] == "실사재고").all())
        self.assertGreater(float(food["현재재고량"].sum()), 1_000_000)               # 실사재고 시트의 총 중량 1,214,559.9g 중 식재료 몫
        self.assertLessEqual(float(food["현재재고량"].sum()), 1214559.9 + 0.1)


if __name__ == "__main__":
    unittest.main()
