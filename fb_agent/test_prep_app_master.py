import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from master import load_master
from prep.app_master import (MEASURED, NO_DATA, NO_RECENT_RECEIPT, build_app_master, ledger_usage, match_measured, read_standard_usage,
                             safety_days, write_master)

NA = pd.NA
ORG_COLS = ["발주처", "원거래처", "품목구분", "계정명", "품목코드_RMS", "품목코드_CK", "품목코드_매장", "품명", "규격", "환산단위", "당월입고수량",
            "당월입고중량_g", "당월입고금액", "실사재고수량", "실사재고중량_g", "리드타임_적용_일", "리드타임_출처", "입고내역_있음", "실사재고_있음"]


def item(supplier, kind, acct, code, name, unit, recv_qty=0.0, recv_g=0.0, stock_qty=0.0, stock_g=0.0, lead=NA, src=NO_DATA):
    return [supplier, supplier, kind, acct, code, "없음", "없음", name, "1kg/pk", unit, recv_qty, recv_g, 0.0, stock_qty, stock_g, lead, src, True, True]


ITEMS = pd.DataFrame([
    item("대풍농산", "식재료", "원재료", "F1", "양파", 1000.0, recv_qty=62, recv_g=62000.0, stock_qty=3, stock_g=3000.0),       # 이론사용 있음
    item("대풍농산", "식재료", "원재료", "F2", "당근", 1000.0, recv_qty=31, recv_g=31000.0, stock_qty=0, stock_g=0.0),         # 이론사용 없음, 입고만 있음 / 재고 0
    item("바이맥스", "소모품", "저장품", "S1", "냅킨", 1.0, recv_qty=62, recv_g=62.0),                                       # 소모품: 입고 있음, 재고 0
    item("바이맥스", "소모품", "저장품", "S2", "행주", 1.0, recv_qty=0, stock_qty=5.0, stock_g=5.0),                          # 재고만 있음
    item("바이맥스", "소모품", "저장품", "S3", "빨대", 1.0),                                                                 # 근거 없음
    item("CK", "식재료", "반제품", "F3", "게살", 500.0, recv_g=15500.0, stock_g=500.0, lead=1, src="품명 태그 대표값"),
    item("CK", "식재료", "반제품", "NO", "이름없는코드", 500.0, lead=1, src="품명 태그 대표값"),                                # RMS 코드 '없음'
    item("CK", "식재료", "반제품", "F4", "양파", 500.0, lead=2, src="품명 태그"),                                             # 이름 중복
], columns=ORG_COLS)
ITEMS.loc[ITEMS["품목코드_RMS"] == "NO", "품목코드_RMS"] = "없음"

SUPPLIERS = pd.DataFrame({
    "업체명": ["대풍농산", "바이맥스", "CK"], "업체유형": ["업체", "업체", "센트럴키친(CK)"], "취급구분": ["식재료", "소모품", "식재료"],
    "리드타임_적용_일": pd.array([NA, NA, 1], dtype="Int64"), "리드타임_출처": [NO_DATA, NO_DATA, "품명 태그 대표값"],
})
STD = pd.DataFrame({"코드": ["F1", "F3"], "이론사용_g": [31000.0, 0.0]})                     # 양파만 실제 이론사용
MEAS = {"(주)대풍농산": (3, "화목토")}                                                       # 구매청구 실측 (바이맥스는 실측 없음)


class Measured(unittest.TestCase):
    def test_names_match_through_company_markers_and_parentheses(self):
        m = {"신선농원(구드래)": (3, "월화"), "(주)가온에프엔비": (2, "수")}
        self.assertEqual(match_measured("구드래", m), (3, "월화"))
        self.assertEqual(match_measured("신선농원", m), (3, "월화"))
        self.assertEqual(match_measured("가온에프엔비", m), (2, "수"))
        self.assertIsNone(match_measured("없는업체", m))
        self.assertIsNone(match_measured("농원", m))                                       # 일부 글자만 같아서는 맞추지 않는다


class Policy(unittest.TestCase):
    def test_safety_days_grow_with_lead_time(self):
        self.assertEqual([safety_days(n) for n in (1, 2, 3, 4, 5)], [1, 1, 2, 2, 3])


class AppMaster(unittest.TestCase):
    def setUp(self):
        self.items, self.sup, self.info = build_app_master(ITEMS, SUPPLIERS, STD, measured=MEAS)

    def test_units_follow_conversion_factor(self):
        a = self.items[self.items["품목코드"] == "F1"].iloc[0]
        self.assertEqual((a["기본단위"], a["PK당수량"], a["BOX당PK"]), ("g", 1000, 1))
        s = self.items[self.items["품목코드"] == "S1"].iloc[0]
        self.assertEqual((s["기본단위"], s["PK당수량"], s["EA당수량"]), ("개", 1, 1))

    def test_usage_from_ledger_then_standard_usage_then_receipts_else_zero(self):
        by = self.items.set_index("품목코드")
        self.assertEqual((by.loc["F1", "일소비량"], by.loc["F1", "일소비량_출처"]), (1000.0, "표준사용량"))      # 31000g / 31일
        self.assertEqual((by.loc["F2", "일소비량"], by.loc["F2", "일소비량_출처"]), (1000.0, "입고 기반 추정"))   # 31000g / 31일
        self.assertEqual((by.loc["S1", "일소비량"], by.loc["S1", "일소비량_출처"]), (2.0, "입고 기반 추정"))      # 62개 / 31일
        self.assertEqual((by.loc["S3", "일소비량"], by.loc["S3", "일소비량_출처"]), (0.0, NO_RECENT_RECEIPT))     # 관측된 소비가 없다 (모르는 것이 아니라 0)
        self.assertEqual((by.loc["S2", "일소비량"], by.loc["S2", "일소비량_출처"]), (0.0, NO_RECENT_RECEIPT))   # 재고만 있어도 소비를 만들지 않는다
        self.assertEqual(by.loc["F3", "일소비량_출처"], "입고 기반 추정")                                       # 이론사용 0이면 입고로

    def test_ledger_usage_beats_standard_usage_and_counts_months(self):
        items, _, _ = build_app_master(ITEMS, SUPPLIERS, STD, measured=MEAS, usage_hist={"F1": (50.0, 50000.0, 7), "S2": (3.0, 3.0, 1)})
        by = items.set_index("품목코드")
        self.assertEqual((by.loc["F1", "일소비량"], by.loc["F1", "일소비량_출처"], by.loc["F1", "일소비량_입고월수"]), (50000.0, "수불부 12개월 실적", 7))
        self.assertEqual((by.loc["S2", "일소비량"], by.loc["S2", "일소비량_출처"]), (3.0, "수불부 12개월 실적"))     # 개수 품목은 수량 기준

    def test_stock_is_real_and_unknown_for_uncounted_supplies(self):
        by = self.items.set_index("품목코드")
        self.assertEqual((by.loc["F1", "현재재고량"], by.loc["F1", "재고_출처"]), (3000.0, "실사재고"))
        self.assertEqual((by.loc["F2", "현재재고량"], by.loc["F2", "재고_출처"]), (0.0, "실사재고"))           # 식재료의 0은 실제 값
        self.assertEqual((by.loc["S1", "현재재고량"], by.loc["S1", "재고_출처"]), ("", NO_DATA))               # 쓰는 소모품이 0으로만 잡힘 -> 모름
        self.assertEqual((by.loc["S2", "현재재고량"], by.loc["S2", "재고_출처"]), (5.0, "실사재고"))             # 센 재고는 실제
        self.assertEqual((by.loc["S3", "현재재고량"], by.loc["S3", "재고_출처"]), (0.0, "실사재고"))             # 쓰는 근거가 없는 소모품 0은 그대로

    def test_safety_stock_needs_usage_and_lead_time(self):
        by = self.items.set_index("품목코드")
        self.assertEqual(by.loc["F1", "안전재고량"], 1000.0 * 2)             # 실측 D3 -> 2일치
        self.assertEqual(by.loc["F3", "안전재고량"], 15500.0 / 31 * 1)       # 태그 D1 -> 1일치
        self.assertEqual(by.loc["S1", "안전재고량"], "")                    # 바이맥스는 리드타임을 모른다
        self.assertEqual(by.loc["F4", "안전재고량"], 0.0)                   # 소비가 관측되지 않은 품목은 0

    def test_names_and_codes_are_unique_and_valid(self):
        self.assertEqual(self.items["품목명"].is_unique, True)
        self.assertEqual(self.items["품목코드"].is_unique, True)
        self.assertEqual(sorted(self.items[self.items["품목명"].str.startswith("양파")]["품목명"]), ["양파 (F1)", "양파 (F4)"])   # 중복 이름은 코드로 구분
        nocode = self.items[self.items["품목명"].str.contains("이름없는코드")].iloc[0]
        self.assertTrue(nocode["품목코드"].startswith("NC-"))                              # RMS 코드가 없는 품목은 임시 코드

    def test_lead_time_sources_tag_then_measured_then_blank(self):
        by = self.items.set_index("품목코드")
        self.assertEqual(by.loc["F4", "리드타임"], 2)                                        # 품명 태그 D2, CK 기본(1)과 다르면 품목 값
        self.assertEqual(by.loc["F4", "리드타임_출처"], "품명 태그")
        self.assertEqual((by.loc["F1", "리드타임"], by.loc["F1", "리드타임_출처"]), ("", MEASURED))   # 업체 실측(3)을 그대로 쓰니 품목 값은 비움
        self.assertEqual((by.loc["S1", "리드타임"], by.loc["S1", "리드타임_출처"]), ("", NO_DATA))

    def test_suppliers_table(self):
        s = self.sup.set_index("거래처명")
        self.assertEqual(set(s.index), {"대풍농산", "바이맥스", "CK"})
        self.assertEqual((s.loc["대풍농산", "기본리드타임"], s.loc["대풍농산", "발주요일"], s.loc["대풍농산", "발주요일_출처"]), (3, "화목토", MEASURED))
        self.assertEqual((s.loc["바이맥스", "기본리드타임"], s.loc["바이맥스", "발주요일"], s.loc["바이맥스", "발주요일_출처"]), ("", "", NO_DATA))
        self.assertEqual((s.loc["CK", "기본리드타임"], s.loc["CK", "리드타임_출처"], s.loc["CK", "발주요일"]), (1, "품명 태그 대표값", ""))

    def test_info_counts_sources(self):
        self.assertEqual(self.info["일소비량_출처"]["표준사용량"], 1)
        self.assertEqual(self.info["items"], len(ITEMS))

    def test_no_invented_values_remain(self):
        for df in (self.items, self.sup):
            self.assertFalse(df.astype(str).apply(lambda c: c.str.contains("가상")).any().any())

    def test_output_loads_with_the_app_master_loader(self):
        out = Path(tempfile.mkdtemp())
        write_master(self.items, self.sup, out)
        suppliers, items = load_master(out)
        self.assertEqual(len(items), len(ITEMS))
        self.assertEqual(set(suppliers), {"대풍농산", "바이맥스", "CK"})
        onion = items[self.items[self.items["품목코드"] == "F1"].iloc[0]["품목명"]]
        self.assertEqual((onion.base_unit, onion.daily_usage_g, onion.current_stock, onion.safety_stock_g), ("g", 1000.0, 3000.0, 2000.0))
        self.assertEqual(onion.lead_time_days, 3)
        self.assertEqual(suppliers["대풍농산"].order_days_label, "화/목/토")
        nap = items[self.items[self.items["품목코드"] == "S1"].iloc[0]["품목명"]]
        self.assertEqual((nap.base_unit, nap.ea_weight_g, nap.lead_time_days, nap.usage_known, nap.current_stock), ("개", 1, None, True, None))
        straw = items[self.items[self.items["품목코드"] == "S3"].iloc[0]["품목명"]]
        self.assertEqual((straw.usage_known, straw.daily_usage_g), (True, 0.0))
        self.assertEqual((suppliers["바이맥스"].lead_time_days, suppliers["바이맥스"].order_days_label, suppliers["바이맥스"].has_schedule), (None, "데이터 없음", False))

    def test_usage_is_never_blank(self):
        self.assertTrue((self.items["일소비량"] != "").all())
        self.assertEqual(int(self.sup.isna().sum().sum()), 0)


class LedgerUsage(unittest.TestCase):
    def month(self, root, ym, recv, stock):
        d = root / ym[:4] / ym
        d.mkdir(parents=True)
        pd.DataFrame([{"품목코드_RMS": c, "당월합계_수량": q, "당월합계_중량_g": q * 1000} for c, q in recv.items()]).to_csv(d / "입고내역_정제.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([{"품목코드_RMS": c, "재고실사_수량": q, "재고실사_중량_g": q * 1000} for c, q in stock.items()]).to_csv(d / "실사재고_정제.csv", index=False, encoding="utf-8-sig")

    def test_consumption_is_receipts_plus_stock_decrease(self):
        root = Path(tempfile.mkdtemp())
        self.month(root, "2025-12", {"A": 0, "B": 0, "C": 0}, {"A": 10, "B": 2, "C": 0})          # 기초 실사 (직전 달 말)
        self.month(root, "2026-01", {"A": 20, "B": 0, "C": 5}, {"A": 8, "B": 2, "C": 5})
        self.month(root, "2026-02", {"A": 10, "B": 0, "C": 0}, {"A": 6, "B": 2, "C": 5})
        use = ledger_usage(root, months=2)
        days = 31 + 28
        self.assertAlmostEqual(use["A"][0], (30 + 10 - 6) / days)                                 # 입고 30 + 기초 10 − 기말 6
        self.assertAlmostEqual(use["A"][1], (30 + 10 - 6) * 1000 / days)
        self.assertEqual(use["A"][2], 2)                                                           # 입고한 달 수
        self.assertNotIn("B", use)                                                                 # 입고가 없으면 소비를 만들지 않는다
        self.assertAlmostEqual(use["C"][0], 5 / days)                                              # 재고가 늘어 음수면 입고량만

    def test_too_few_months_gives_nothing(self):
        root = Path(tempfile.mkdtemp())
        self.month(root, "2026-01", {"A": 1}, {"A": 1})
        self.assertEqual(ledger_usage(root, months=12), {})


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
        cls.items, cls.sup, cls.info = build_from_markdown(REAL, ledger_history=False)          # 2025-12 한 달 파일 기준 (표준사용량 148개)

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
        active = [i for i in items.values() if i.usage_known and i.daily_usage_g > 0]
        src = self.info["일소비량_출처"]
        self.assertEqual(len(active), sum(n for k, n in src.items() if k != NO_RECENT_RECEIPT))
        self.assertTrue(all(i.usage_known for i in items.values()))                          # 수불부가 있으면 소비는 항상 값이 있다(없으면 0)
        self.assertNotIn("가상", set(self.info["일소비량_출처"]) | set(self.info["재고_출처"]) | set(self.info["리드타임_출처"]))

    def test_real_stock_is_kept_for_food(self):
        food = self.items[self.items["대분류"] == "식재료"]
        self.assertTrue((food["재고_출처"] == "실사재고").all())
        self.assertGreater(float(food["현재재고량"].sum()), 1_000_000)               # 실사재고 시트의 총 중량 1,214,559.9g 중 식재료 몫
        self.assertLessEqual(float(food["현재재고량"].sum()), 1214559.9 + 0.1)


if __name__ == "__main__":
    unittest.main()
