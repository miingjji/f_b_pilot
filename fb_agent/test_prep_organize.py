import unittest
from pathlib import Path

import pandas as pd

from prep.organize import (COLUMN_DOC, build_daily, build_menu, build_menu_rollup, build_supplier_items, build_suppliers,
                           d_notation, lead_times, normalize_supplier, split_tag, supplier_type, synthetic_lead_time)

REC_COLS = ["구분", "계정명", "품목코드_RMS", "품목코드_CK", "품목코드_매장", "거래처명", "품명", "규격", "과세면세", "단가_g", "단가",
            "환산단위", "당월발주", "차이", "당월합계_수량", "당월합계_중량_g", "당월합계_금액", "1일_수량", "1일_중량_g", "1일_금액",
            "2일_수량", "2일_중량_g", "2일_금액"]
CNT_COLS = ["계정명", "품목코드_RMS", "품목코드_CK", "품목코드_매장", "거래처명", "품명", "규격", "과세면세", "환산단위", "재고실사_수량", "재고실사_중량_g"]


def rec_row(kind, acct, rms, supplier, name, total, d1=(0, 0, 0), d2=(0, 0, 0), spec="1kg/pk", unit=1000):
    return [kind, acct, rms, "없음", "없음", supplier, name, spec, "과세", 0.01, 10.0, unit, 0.0, -total[0], *total, *d1, *d2]


REC = pd.DataFrame([
    rec_row("아워홈과세", "원재료", "R1", "아워홈", "[수D1/부D2]땅콩버터_510g/ea", (2, 1020, 10.2), d1=(1, 510, 5.1), d2=(1, 510, 5.1)),
    rec_row("아워홈과세", "원재료", "R2", "아워홈", "[수D1/부D1]백설탕_3kg/ea", (0, 0, 0)),
    rec_row("CK과세", "반제품", "R3", "CK", "게살_500g/pk", (4, 2000, 40.0), d1=(4, 2000, 40.0)),
    rec_row("CK", "저장품", "R4", "대만수입", "장갑_100ea", (1, 1, 5.0), d2=(1, 1, 5.0)),
    rec_row("쿠팡저장품과세", "저장품", "R5", "쿠팡저장품", "물병", (0, 0, 0)),
    rec_row("씨앤씨원재료과세", "원재료", "R6", "씨앤씨원재료", "고량주 [부산]", (0, 0, 0)),
    rec_row("바이맥스과세", "저장품", "R7", "바이맥스", "[부산]냅킨", (3, 3, 30.0), d1=(3, 3, 30.0)),
], columns=REC_COLS)


def cnt_row(acct, rms, supplier, name, qty, weight):
    return [acct, rms, "없음", "없음", supplier, name, "1kg", "과세", 1000, qty, weight]


CNT = pd.DataFrame([
    cnt_row("원재료", "R1", "아워홈", "[수D1/부D2]땅콩버터_510g/ea", 3.0, 1530.0),
    cnt_row("원재료", "R2", "아워홈", "[수D1/부D1]백설탕_3kg/ea", 0.0, 0.0),
    cnt_row("반제품", "R3", "대풍농산", "게살_500g/pk", 1.0, 500.0),                     # 원거래처는 대풍농산, 입고는 CK 경유
    cnt_row("저장품", "R4", "대만수입", "장갑_100ea", 2.0, 2.0),
    cnt_row("저장품", "R5", "쿠팡", "물병", 1.0, 1.0),
    cnt_row("원재료", "R6", "씨앤씨", "고량주 [부산]", 5.0, 5000.0),
    cnt_row("저장품", "없음", "바이맥스", "[부산]냅킨", 7.0, 7.0),                        # 코드 없음 -> 품명으로 연결
    cnt_row("원재료", "없음", "중구샘표", "양조간장_1.7l", 2.0, 3400.0),                  # 입고내역에 없음 (원거래처만)
], columns=CNT_COLS)


class Names(unittest.TestCase):
    def test_split_tag(self):
        self.assertEqual(split_tag("[수D1/부D2]땅콩버터_510g/ea"), ("수D1/부D2", "땅콩버터_510g/ea"))
        self.assertEqual(split_tag("[부산]냅킨"), ("부산", "냅킨"))
        self.assertEqual(split_tag("고량주 [부산]"), ("", "고량주 [부산]"))            # 앞에 붙은 태그만 분리
        self.assertEqual(split_tag("그냥 이름"), ("", "그냥 이름"))

    def test_lead_times(self):
        self.assertEqual(lead_times("수D1/부D2"), (1, 2))
        self.assertEqual(lead_times("수D2/부D2"), (2, 2))
        self.assertIsNone(lead_times("부산"))
        self.assertIsNone(lead_times(""))

    def test_d_notation_in_names(self):
        cases = {"(D1)스틱슈거_5g*100ea/box": "D1", "(D2)특란_30ea/pk": "D2", "각얼음참조아(D-2)_BOX(3kg*5pk)": "D-2",
                 "닭다리살D-2(냉동,껍질유)_2kg/pk": "D-2", "통팥앙금(D-1,굿모닝서울)_5kg/pk": "D-1",
                 "군만두기계 1구(D-2000A)_ea": "",                       # 기계 모델명은 D 표기가 아님
                 "땅콩버터_510g/ea": "", "ADD-ON 소스": "", "HD1 카메라": ""}
        for name, want in cases.items():
            self.assertEqual(d_notation(name), want, name)

    def test_normalize_supplier_only_merges_known_suffix_variants(self):
        known = {"쿠팡", "씨앤씨", "CK", "아워홈"}
        self.assertEqual(normalize_supplier("쿠팡저장품", known), "쿠팡")
        self.assertEqual(normalize_supplier("씨앤씨원재료", known), "씨앤씨")
        self.assertEqual(normalize_supplier("아워홈", known), "아워홈")
        self.assertEqual(normalize_supplier("새업체저장품", known), "새업체저장품")       # 없는 이름으로 합치지 않음

    def test_supplier_type(self):
        self.assertEqual(supplier_type("CK"), "센트럴키친(CK)")
        self.assertEqual(supplier_type("인터넷구매"), "온라인 구매처")
        self.assertEqual(supplier_type("바이맥스"), "업체")


class SyntheticLeadTime(unittest.TestCase):
    def test_deterministic_and_within_realistic_ranges(self):
        for name in ("가나다", "바이맥스", "하나로축산", "새업체"):
            for kind in ("식재료", "소모품"):
                a = synthetic_lead_time(name, kind, "업체")
                self.assertEqual(a, synthetic_lead_time(name, kind, "업체"))               # 같은 입력은 항상 같은 값
        for name in [f"업체{i}" for i in range(60)]:
            self.assertTrue(1 <= synthetic_lead_time(name, "식재료", "업체") <= 3, name)
            self.assertTrue(2 <= synthetic_lead_time(name, "소모품", "업체") <= 5, name)

    def test_type_and_keyword_rules(self):
        self.assertEqual(synthetic_lead_time("CK", "식재료", "센트럴키친(CK)"), 1)
        self.assertIn(synthetic_lead_time("인터넷구매", "소모품", "온라인 구매처"), (2, 3))
        self.assertEqual(synthetic_lead_time("하나로축산", "식재료", "업체"), 1)                # 신선 식재료는 다음 날
        self.assertEqual(synthetic_lead_time("페스카꼬레아", "식재료", "업체"), 1)
        self.assertEqual(synthetic_lead_time("다와포장", "소모품", "업체"), 4)                   # 포장재는 길게
        self.assertEqual(synthetic_lead_time("대풍농산", "식재료", "원거래처(CK 경유 또는 입고 기록 없음)"), 1)

    def test_different_names_do_not_all_collapse_to_one_value(self):
        vals = {synthetic_lead_time(f"소모품업체{i}", "소모품", "업체") for i in range(40)}
        self.assertGreaterEqual(len(vals), 3)


class SupplierItems(unittest.TestCase):
    def setUp(self):
        self.items = build_supplier_items(REC, CNT)
        self.by = self.items.set_index("품목코드_RMS")

    def test_all_receiving_items_plus_count_only_items(self):
        self.assertEqual(len(self.items), 8)                          # 입고내역 7 + 실사재고에만 있는 1 (코드 없는 '양조간장'은 품명 매칭 실패)
        self.assertEqual(int(self.items.isna().sum().sum()), 0)

    def test_tags_are_split_and_lead_times_parsed(self):
        r = self.by.loc["R1"]
        self.assertEqual((r["품명"], r["품명태그"], r["품명_원본"]), ("땅콩버터_510g/ea", "수D1/부D2", "[수D1/부D2]땅콩버터_510g/ea"))
        self.assertEqual((r["리드타임_수원점_일"], r["리드타임_부점_일"], r["리드타임_확인"]), (1, 2, "품명 태그"))
        self.assertEqual(self.by.loc["R1", "품명_D표기"], "없음")                       # [수D/부D] 태그는 태그 열에서 처리
        r6 = self.by.loc["R3"]
        self.assertEqual((r6["리드타임_수원점_일"], r6["리드타임_확인"]), (0, "정보 없음"))
        self.assertEqual(self.by.loc["R7", "품명태그"], "부산")                    # 위치 태그는 리드타임이 아님
        self.assertEqual(self.by.loc["R7", "리드타임_확인"], "정보 없음")

    def test_d_notation_is_kept_separately_and_not_treated_as_lead_time(self):
        rec = REC.copy()
        rec.loc[1, "품명"] = "얼음(D-2)_1kg"
        items = build_supplier_items(rec, CNT).set_index("품목코드_RMS")
        r = items.loc["R2"]
        self.assertEqual(r["품명_D표기"], "D-2")
        self.assertEqual((r["리드타임_수원점_일"], r["리드타임_확인"]), (0, "정보 없음"))   # D-n 은 점포별 리드타임이 아니라 의미 확인 전까지 보존만
        sup = build_suppliers(build_supplier_items(rec, CNT)).set_index("업체명")
        self.assertEqual((sup.loc["아워홈", "D표기_품목수"], sup.loc["아워홈", "D표기"]), (1, "D-2"))
        self.assertEqual(sup.loc["CK", "D표기"], "없음")

    def test_supplier_names_are_normalized_but_original_kept(self):
        self.assertEqual(self.by.loc["R5", "발주처"], "쿠팡")
        self.assertEqual(self.by.loc["R5", "발주처_원본표기"], "쿠팡저장품")
        self.assertEqual(self.by.loc["R6", "발주처"], "씨앤씨")

    def test_applied_lead_time_keeps_real_values_and_labels_synthetic_ones(self):
        r1 = self.by.loc["R1"]                                                        # 품명 태그가 있는 품목: 실제 값
        self.assertEqual((r1["리드타임_적용_일"], r1["리드타임_출처"]), (1, "품명 태그"))
        r2 = self.by.loc["R2"]                                                        # 같은 업체(아워홈)의 태그 품목 -> 자기 태그값
        self.assertEqual((r2["리드타임_적용_일"], r2["리드타임_출처"]), (1, "품명 태그"))
        r3 = self.by.loc["R3"]                                                        # CK: 태그 없음 -> 가상
        self.assertEqual((r3["리드타임_적용_일"], r3["리드타임_출처"]), (1, "가상"))
        self.assertEqual(r3["리드타임_수원점_일"], 0)                                   # 실제 값 열은 건드리지 않음
        self.assertEqual(r3["리드타임_확인"], "정보 없음")
        self.assertTrue((self.items["리드타임_적용_일"] >= 1).all())

    def test_untagged_item_of_a_tagged_supplier_uses_the_supplier_representative(self):
        rec = REC.copy()
        rec.loc[len(rec)] = rec_row("아워홈과세", "원재료", "R9", "아워홈", "소금_1kg", (0, 0, 0))
        cnt = CNT.copy()
        cnt.loc[len(cnt)] = cnt_row("원재료", "R9", "아워홈", "소금_1kg", 0.0, 0.0)
        r = build_supplier_items(rec, cnt).set_index("품목코드_RMS").loc["R9"]
        self.assertEqual((r["리드타임_적용_일"], r["리드타임_출처"]), (1, "업체 태그 대표값"))

    def test_ordering_route_and_origin_supplier(self):
        self.assertEqual(self.by.loc["R1", "발주경로"], "직접")
        self.assertEqual(self.by.loc["R3", "발주경로"], "CK경유")
        self.assertEqual((self.by.loc["R3", "발주처"], self.by.loc["R3", "원거래처"]), ("CK", "대풍농산"))
        self.assertEqual(self.by.loc["R4", "발주경로"], "CK경유")                  # 구분이 'CK'인 소모품
        self.assertEqual((self.by.loc["R4", "발주처"], self.by.loc["R4", "원거래처"]), ("대만수입", "대만수입"))

    def test_kind_and_receipt_numbers(self):
        self.assertEqual(self.by.loc["R1", "품목구분"], "식재료")
        self.assertEqual(self.by.loc["R4", "품목구분"], "소모품")
        r = self.by.loc["R1"]
        self.assertEqual((r["당월입고수량"], r["당월입고중량_g"], r["당월입고금액"], r["당월입고일수"]), (2, 1020, 10.2, 2))
        self.assertEqual(self.by.loc["R2", "당월입고일수"], 0)

    def test_stock_is_joined_by_code_and_by_name(self):
        self.assertEqual(self.by.loc["R1", "실사재고수량"], 3.0)
        self.assertTrue(self.items.loc[self.items["품명"] == "냅킨", "실사재고_있음"].iloc[0])      # 코드 없는 실사 행을 품명으로 연결
        self.assertEqual(self.items.loc[self.items["품명"] == "냅킨", "실사재고수량"].iloc[0], 7.0)

    def test_each_stock_row_is_used_once_even_when_names_repeat(self):
        """같은 품명의 입고 품목이 둘이어도 실사재고 한 행이 두 번 세어지면 안 된다 (코드 연결이 우선, 품명은 남은 행에만)."""
        rec = pd.DataFrame([rec_row("대풍농산과세", "원재료", "A1", "대풍농산", "소금_1kg", (0, 0, 0)),
                            rec_row("대풍농산과세", "원재료", "A2", "대풍농산", "소금_1kg", (0, 0, 0))], columns=REC_COLS)   # 이름이 같고 코드만 다름
        cnt = pd.DataFrame([cnt_row("원재료", "A1", "대풍농산", "소금_1kg", 5.0, 5000.0)], columns=CNT_COLS)
        items = build_supplier_items(rec, cnt).set_index("품목코드_RMS")
        self.assertEqual((items.loc["A1", "실사재고수량"], bool(items.loc["A1", "실사재고_있음"])), (5.0, True))
        self.assertEqual((items.loc["A2", "실사재고수량"], bool(items.loc["A2", "실사재고_있음"])), (0.0, False))     # 두 번 세지 않음
        self.assertEqual(float(items["실사재고수량"].sum()), 5.0)

    def test_name_match_fills_only_unused_count_rows(self):
        rec = pd.DataFrame([rec_row("대풍농산과세", "원재료", "A1", "대풍농산", "소금_1kg", (0, 0, 0)),
                            rec_row("대풍농산과세", "원재료", "A2", "대풍농산", "후추_1kg", (0, 0, 0))], columns=REC_COLS)
        cnt = pd.DataFrame([cnt_row("원재료", "A1", "대풍농산", "소금_1kg", 5.0, 5000.0),
                            cnt_row("원재료", "없음", "대풍농산", "후추_1kg", 2.0, 2000.0)], columns=CNT_COLS)    # 코드 없는 행은 품명으로
        items = build_supplier_items(rec, cnt).set_index("품목코드_RMS")
        self.assertEqual(float(items.loc["A2", "실사재고수량"]), 2.0)
        self.assertEqual(len(items), 2)                                                                          # 추가로 붙는 행 없음

    def test_count_only_item_is_appended_with_flags(self):
        r = self.items[self.items["품명"] == "양조간장_1.7l"].iloc[0]
        self.assertFalse(r["입고내역_있음"])
        self.assertEqual((r["발주처"], r["발주경로"], r["당월입고금액"]), ("중구샘표", "미확인", 0))


class Suppliers(unittest.TestCase):
    def setUp(self):
        self.items = build_supplier_items(REC, CNT)
        self.sup = build_suppliers(self.items).set_index("업체명")

    def test_one_row_per_supplier_including_origin_only_suppliers(self):
        self.assertEqual(set(self.sup.index), {"아워홈", "CK", "대만수입", "쿠팡", "씨앤씨", "바이맥스", "대풍농산", "중구샘표"})
        self.assertEqual(self.sup.loc["중구샘표", "업체유형"], "원거래처(CK 경유 또는 입고 기록 없음)")
        self.assertEqual(self.sup.loc["대풍농산", "발주처_품목수"], 0)
        self.assertEqual(self.sup.loc["대풍농산", "원거래처_품목수"], 1)

    def test_lead_time_summary_from_tags(self):
        s = self.sup.loc["아워홈"]
        self.assertEqual((s["리드타임_수원점"], s["리드타임_부점"], s["리드타임_확인"], s["태그품목수"]), ("D1", "D1~D2", "품명 태그", 2))
        self.assertEqual(self.sup.loc["CK", "리드타임_수원점"], "정보 없음")

    def test_applied_lead_time_and_source_per_supplier(self):
        s = self.sup
        self.assertEqual((s.loc["아워홈", "리드타임_적용_일"], s.loc["아워홈", "리드타임_출처"]), (1, "품명 태그 대표값"))
        for name in ("CK", "대만수입", "쿠팡", "씨앤씨", "바이맥스", "대풍농산", "중구샘표"):
            self.assertEqual(s.loc[name, "리드타임_출처"], "가상", name)
            self.assertTrue(1 <= s.loc[name, "리드타임_적용_일"] <= 5, name)
        self.assertEqual(s.loc["CK", "리드타임_적용_일"], 1)
        self.assertEqual(s.loc["바이맥스", "리드타임_수원점"], "정보 없음")                # 실제 값 열은 그대로

    def test_kind_accounts_and_totals(self):
        s = self.sup.loc["아워홈"]
        self.assertEqual((s["취급구분"], s["품목수"], s["당월입고금액"]), ("식재료", 2, 10.2))
        self.assertEqual(self.sup.loc["CK", "업체유형"], "센트럴키친(CK)")
        self.assertEqual(self.sup.loc["쿠팡", "표기_변형"], "쿠팡저장품")
        self.assertEqual(self.sup.loc["바이맥스", "취급구분"], "소모품")

    def test_no_missing_values(self):
        self.assertEqual(int(self.sup.isna().sum().sum()), 0)


def sales_row(day, rcpt, cancel, code, name, price, qty, net, guests=0, gtotal=0, big="음식", mid="면", small="면"):
    return [day, rcpt, cancel, guests, guests, big, mid, small, code, name, "과세", price, qty, price * qty, 0, price * qty, net, 0, net if gtotal else 0]


SALES = pd.DataFrame([
    sales_row("2025-12-01", 1, "정상", "M1", "샤오롱바오", 8000, 2, 1000, guests=2, gtotal=1),
    sales_row("2025-12-01", 1, "정상", "M2", "콜라", 0, 1, 0),
    sales_row("2025-12-01", 2, "매출취소", "M1", "샤오롱바오", 8000, -1, -500, guests=1, gtotal=1),
    sales_row("2025-12-02", 3, "메뉴정정", "M1", "샤오롱바오", 8000, 1, 500, guests=1, gtotal=1),            # 제외
    sales_row("2025-12-02", 4, "주문취소", "해당없음", "해당없음", 0, 0, 0, guests=1, gtotal=1),               # 제외
    sales_row("2025-12-02", 5, "정상", "M3", "우육면", 5000, 1, 300, guests=1, gtotal=1),
    sales_row("2025-12-02", 5, "정상", "M3", "우육면", 5000, 1, 300),
    sales_row("2025-12-02", 5, "정상", "M3", "우육면", 6000, 1, 400),
], columns=["매출일자", "영수증번호", "취소구분", "객수", "객수_합계", "대분류명", "중분류명", "소분류명", "메뉴코드", "메뉴명", "과/면세", "단가", "수량",
            "총매출", "할인", "실매출", "순매출", "부가세", "순매출_합계"])

PROD = pd.DataFrame({
    "상품코드": ["M1", "M3", "M9", "M1"],
    "상품명": ["샤오롱바오", "우육면", "안팔린메뉴", "샤오롱바오"],
    "상품명통일": ["샤오롱바오(4)", "우육면", "안팔린", "샤오롱바오(4)"],
    "판매수량": [1, 3, 0, 1],
    "판매금액": [500, 1000, 0, 500],
    "조회_BOM유무": ["1 EA", "1EA", "미기재", "1 EA"],
    "중복행": [False, False, False, True],
})


class Menu(unittest.TestCase):
    def setUp(self):
        self.menu = build_menu(SALES, PROD)
        self.by = self.menu.set_index("메뉴코드")

    def test_sales_basis_is_normal_plus_sales_cancel_only(self):
        r = self.by.loc["M1"]
        self.assertEqual((r["판매수량"], r["순매출"]), (1, 500))                       # 2 + (-1), 메뉴정정(+500)은 제외
        self.assertEqual(r["제외된_취소정정수량"], 1)

    def test_catalog_includes_unsold_and_cancel_only_codes_are_not_menus(self):
        self.assertEqual(set(self.by.index), {"M1", "M2", "M3", "M9"})                 # 해당없음(메뉴 없는 취소)은 제외, 중복행은 한 번만
        self.assertEqual((self.by.loc["M9", "판매수량"], self.by.loc["M9", "대분류"]), (0, "미확인"))

    def test_price_basis_and_sources(self):
        self.assertEqual((self.by.loc["M1", "판매가"], self.by.loc["M1", "가격출처"]), (8000, "매출입력 단가"))
        self.assertEqual((self.by.loc["M2", "판매가"], self.by.loc["M2", "가격출처"]), (0, "구성품(단가 0)"))
        self.assertEqual((self.by.loc["M3", "판매가"], self.by.loc["M3", "단가종류수"], self.by.loc["M3", "최고단가"]), (5000, 2, 6000))
        self.assertEqual((self.by.loc["M9", "판매가"], self.by.loc["M9", "가격출처"]), (0, "미확인(이번 달 판매 없음)"))

    def test_reconciles_with_product_sheet(self):
        self.assertEqual(self.by.loc["M1", "판매및할인_일치"], "일치")
        self.assertEqual(self.by.loc["M3", "판매및할인_일치"], "일치")                  # 수량 3 / 금액 1000
        self.assertEqual(self.by.loc["M2", "판매및할인_일치"], "판매및할인에 없음")
        self.assertEqual(self.by.loc["M9", "판매및할인_일치"], "일치")                  # 둘 다 0

    def test_unified_name_and_share(self):
        self.assertEqual(self.by.loc["M1", "통합메뉴명"], "샤오롱바오(4)")
        self.assertEqual(self.by.loc["M2", "통합메뉴명"], "콜라")                       # 판매및할인에 없으면 메뉴명
        self.assertAlmostEqual(self.menu["순매출비중"].sum(), 100.0, places=2)
        self.assertEqual(list(self.menu["순매출"]), sorted(self.menu["순매출"], reverse=True))

    def test_no_missing_values(self):
        self.assertEqual(int(self.menu.isna().sum().sum()), 0)

    def test_rollup_groups_by_unified_name(self):
        roll = build_menu_rollup(self.menu).set_index("통합메뉴명")
        self.assertEqual((roll.loc["샤오롱바오(4)", "메뉴코드수"], roll.loc["샤오롱바오(4)", "순매출"]), (1, 500))
        self.assertEqual(roll["순매출"].sum(), self.menu["순매출"].sum())


class Daily(unittest.TestCase):
    def test_per_day_totals(self):
        d = build_daily(SALES).set_index("매출일자")
        self.assertEqual(list(d.index), ["2025-12-01", "2025-12-02"])
        self.assertEqual((d.loc["2025-12-01", "메뉴판매수량"], d.loc["2025-12-01", "순매출"]), (2, 500))          # 정상 2 + 매출취소 -1 ... + 콜라 1
        self.assertEqual(d.loc["2025-12-02", "순매출"], 1000)                                                  # M3 세 줄: 300+300+400 (메뉴정정·주문취소 제외)
        self.assertEqual(d.loc["2025-12-01", "요일"], "월")
        self.assertEqual(int(d.isna().sum().sum()), 0)


class Docs(unittest.TestCase):
    def test_every_output_column_is_documented(self):
        items = build_supplier_items(REC, CNT)
        tables = {"업체별_품목": items, "업체_마스터": build_suppliers(items), "메뉴_마스터": build_menu(SALES, PROD),
                  "통합메뉴_매출": build_menu_rollup(build_menu(SALES, PROD)), "일자별_매출": build_daily(SALES)}
        for name, df in tables.items():
            missing = [c for c in df.columns if c not in COLUMN_DOC[name]]
            self.assertEqual(missing, [], f"{name}: 설명 없는 열")


REAL = Path(__file__).resolve().parent / "data" / "f_b_menu_data.md"


@unittest.skipUnless(REAL.exists(), "실제 데이터 파일이 없으면 건너뜀")
class RealFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from prep.organize import build_all
        cls.tables, cls.info = build_all(REAL)

    def test_menu_matches_product_sheet_everywhere(self):
        m = self.tables["메뉴_마스터"]
        both = m[m["판매및할인_일치"] != "판매및할인에 없음"]
        self.assertTrue((both["판매및할인_일치"] == "일치").all(), both[both["판매및할인_일치"] != "일치"].head())
        self.assertEqual(int(m["판매수량"].sum()), 27787)
        self.assertEqual(int(m["순매출"].sum()), 169804335)

    def test_daily_total_equals_menu_total_and_31_days(self):
        d = self.tables["일자별_매출"]
        self.assertEqual(len(d), 31)
        self.assertEqual(int(d["순매출"].sum()), 169804335)
        self.assertEqual(int(d["객수"].sum()), 7578)

    def test_supplier_items_counts(self):
        it = self.tables["업체별_품목"]
        self.assertGreaterEqual(len(it), 894)
        self.assertEqual(int(it["입고내역_있음"].sum()), 894)
        self.assertAlmostEqual(float(it["실사재고중량_g"].sum()), 1214559.9, places=1)                    # 실사재고 시트 합계와 같아야 함(중복 집계 금지)
        self.assertEqual(round(float(it["당월입고금액"].sum()), 4), 48880256.4209)
        tagged = it[it["리드타임_확인"] == "품명 태그"]
        self.assertEqual(len(tagged), 35)
        self.assertEqual(set(tagged["발주처"]), {"아워홈"})

    def test_every_supplier_and_item_has_an_applied_lead_time_with_source(self):
        sup, it = self.tables["업체_마스터"], self.tables["업체별_품목"]
        self.assertEqual(len(sup), 45)
        self.assertTrue(sup["리드타임_적용_일"].between(1, 5).all())
        self.assertEqual(set(sup.loc[sup["리드타임_출처"] == "품명 태그 대표값", "업체명"]), {"아워홈"})      # 실제 근거가 있는 업체는 한 곳
        self.assertEqual(int((sup["리드타임_출처"] == "가상").sum()), 44)
        self.assertTrue(it["리드타임_적용_일"].between(1, 5).all())
        self.assertEqual(int((it["리드타임_출처"] == "품명 태그").sum()), 35)
        self.assertEqual(set(it["리드타임_출처"]), {"품명 태그", "업체 태그 대표값", "가상"})
        self.assertEqual(int((it["리드타임_확인"] == "품명 태그").sum()), 35)                      # 실제 값 열은 그대로
        self.assertTrue(it.loc[it["리드타임_출처"] == "가상", "리드타임_수원점_일"].eq(0).all())

    def test_synthetic_values_are_stable_across_runs(self):
        from prep.organize import build_all
        again, _ = build_all(REAL)
        pd.testing.assert_frame_equal(self.tables["업체_마스터"], again["업체_마스터"])

    def test_self_checks_pass_and_unlisted_menus_are_reported(self):
        self.assertTrue(all(c["ok"] for c in self.info["checks"]), self.info["checks"])
        self.assertEqual(len(self.info["checks"]), 4)
        m = self.tables["메뉴_마스터"]
        only = m[m["판매및할인_일치"] == "판매및할인에 없음"]
        self.assertEqual((len(only), int(only["판매수량"].sum()), int(only["순매출"].sum())), (33, 663, 0))   # 세트 구성품: 수량만 있고 금액 0
        self.assertTrue(any("판매및할인에 없는 메뉴 33개" in n for n in self.info["notes"]))

    def test_no_missing_anywhere(self):
        for name, df in self.tables.items():
            self.assertEqual(int(df.isna().sum().sum()), 0, name)
            self.assertFalse((df.astype(str) == "").any().any(), name)


if __name__ == "__main__":
    unittest.main()
