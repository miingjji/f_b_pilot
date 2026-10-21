import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import re
import unittest

import menu
import views
from menu import RAILS, all_leaves, breadcrumb, get_leaf, has_leaf, rail_of, search

# 요구사항 명세의 중메뉴 → 소메뉴 (이 목록이 곧 계약: 빠지면 테스트가 실패)
SPEC = {
    "매출요약": ["월별집계", "일자별", "요일별", "시간대별", "실시간매출", "객단가 및 회전율", "누적대비일별매출", "매출비교", "일자별객수"],
    "메뉴매출분석": ["판매현황", "월별집계", "일자별", "시간대별"],
    "결제수단분석": ["신용카드", "간편결제", "현금"],
    "매출취소분석": ["매출취소", "매출변환", "주문/메뉴취소"],
    "매출정산": ["매출영수증", "매출영수증상세", "정산레포트", "정산레포트(PNC)", "연어입고"],
    "발주관리": ["구매청구", "구매청구 상세내역", "발주 리드타임 관리", "자동 발주 추천"],
    "입고관리": ["구매발주서 기준", "일반입고", "입고 상세내역", "반품"],
    "기타입출고": ["손망실 상세내역", "이체 상세내역", "이체요청"],
    "수불관리": ["수불현황", "매장별 재고입력", "매장별 재고입력 이력", "안전재고/소진율 예측"],
    "근태 및 스케줄": ["월간 근무 스케줄표", "파트타임/정직원 출퇴근 기록", "근무 교대 요청"],
    "인건비 분석": ["시간대별 적정 인력 배치", "매출 대비 인건비율(L%)"],
    "AI 운영 분석": ["매출 및 재고 리포트 요약", "이상징후 알림"],
    "Q&A 대화창": ["발주 추천", "리드타임 조회", "스케줄 조정 문의"],
}
SPEC_MAJORS = {"매출분석": ["매출요약", "메뉴매출분석", "결제수단분석", "매출취소분석", "매출정산"],
               "발주 및 재고관리": ["발주관리", "입고관리", "기타입출고", "수불관리"],
               "인력 및 스케줄 관리": ["근태 및 스케줄", "인건비 분석"],
               "F&B AI 에이전트": ["AI 운영 분석", "Q&A 대화창"]}
SPEC_RAILS = ["홈", "즐겨찾기", "매출", "구매/발주", "인력/스케줄", "설정/계정"]


def mids():
    return {mid.title: [lf.title for lf in mid.leaves] for r in RAILS for m in r.majors for mid in m.mids}


class Structure(unittest.TestCase):
    def test_rails_match_spec(self):
        self.assertEqual([r.label for r in RAILS], SPEC_RAILS)

    def test_majors_and_mids_match_spec(self):
        majors = {m.title: [mid.title for mid in m.mids] for r in RAILS for m in r.majors}
        for title, expected in SPEC_MAJORS.items():
            self.assertEqual(majors[title], expected)

    def test_every_spec_leaf_exists(self):
        have = mids()
        for mid, leaves in SPEC.items():
            missing = [t for t in leaves if t not in have[mid]]
            self.assertEqual(missing, [], f"{mid}에 빠진 소메뉴")

    def test_ids_are_unique_url_slugs(self):
        ids = [lf.id for lf in all_leaves()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r"[a-z0-9-]+", i) for i in ids))

    def test_every_leaf_has_a_renderer(self):
        missing = [lf.id for lf in all_leaves() if lf.view not in views.REGISTRY]
        self.assertEqual(missing, [], "렌더러가 없어 '준비 중'으로 떨어지는 소메뉴")

    def test_leaf_arg_variants_are_valid(self):
        from agent import TOPIC_QUESTIONS
        for lf in all_leaves():
            if lf.view == "ai.chat":
                self.assertIn(lf.arg, TOPIC_QUESTIONS)

    def test_lookup_helpers(self):
        self.assertEqual(breadcrumb("sales-daily"), ["매출분석", "매출요약", "일자별"])
        self.assertEqual(rail_of("po-auto").id, "purchase")
        self.assertEqual(get_leaf(menu.DEFAULT_LEAF).view, "home.dashboard")
        self.assertFalse(has_leaf("nope"))


class Search(unittest.TestCase):
    def ids(self, q):
        return {lf.id for lf in search(q)}

    def test_title_and_parent_names(self):
        self.assertEqual(self.ids("시간대"), {"sales-hourly", "menu-hourly", "hr-staffing"})
        self.assertIn("pay-card", self.ids("결제수단"))          # 중메뉴 이름으로
        self.assertIn("sales-monthly", self.ids("sales"))         # 대메뉴 영문명으로

    def test_all_tokens_must_match(self):
        self.assertEqual(self.ids("메뉴매출 일자"), {"menu-daily"})

    def test_choseong(self):
        self.assertTrue({"sales-daily", "menu-daily", "sales-customers"} & self.ids("ㅇㅈㅂ"))
        self.assertIn("sales-daily", self.ids("ㅇㅈㅂ"))

    def test_empty_and_no_match(self):
        self.assertEqual(search(""), [])
        self.assertEqual(search("   "), [])
        self.assertEqual(search("zzzz없는메뉴"), [])

    def test_case_and_spaces_ignored(self):
        self.assertIn("recv-by-po", self.ids("구매 발주서"))


if __name__ == "__main__":
    unittest.main()
