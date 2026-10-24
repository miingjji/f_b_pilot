import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import unittest
from datetime import date, timedelta

from agent import AgentContext, answer
TOPIC_BASE_ORDER = ["지금 발주해야 할 품목은?", "재고 현황 요약", "발주 입고 일정 알려줘"]
from calendar_data import (GROUP_LIMIT, Event, build_events, cell_width, chars_per_line, derived_events, max_cell_events,
                           new_event, row_height, visible_events)
from data import DEFAULT_CALENDAR, ITEMS
from errors import InvalidInputError
from insights import master_stock_g, recommendations
from models import StoreCalendar
from reorder import Recommendation

THU = date(2026, 10, 15)  # 목요일
CAL = StoreCalendar(closed_weekdays=frozenset({6}))    # 일요일 휴무 (달력·일정 계산을 시험하는 용도; 실제 기본 달력은 일요일도 영업)


class Events(unittest.TestCase):
    def test_new_event_validation(self):
        e = new_event(THU, "event", "  시식회 ", " 3시 ")
        self.assertEqual((e.title, e.detail, e.deletable), ("시식회", "3시", True))
        for bad in [dict(title="  "), dict(title=""), dict(category="order"), dict(category="closed")]:
            with self.assertRaises(InvalidInputError):
                new_event(THU, bad.get("category", "event"), bad.get("title", "x"))

    def test_closed_days_from_calendar(self):
        sun = date(2026, 10, 18)
        evs = derived_events([], CAL, THU, THU + timedelta(days=7))
        self.assertEqual({e.day for e in evs if e.category == "closed"}, {sun})
        extra = StoreCalendar(frozenset(), frozenset({THU}))
        self.assertEqual([e.day for e in derived_events([], extra, THU, THU)], [THU])

    def test_order_events_only_for_actionable_status(self):
        recs = recommendations(master_stock_g(), THU, CAL)
        evs = derived_events(recs, CAL, THU, THU + timedelta(days=30))
        orders = [e for e in evs if e.category == "order"]
        actionable = [r for r in recs if r.status in ("URGENT", "ORDER_NOW", "ORDER_SOON")]
        self.assertTrue(actionable)
        self.assertEqual(len(orders), 2 * len([r for r in actionable if r.order_date and r.arrival_date]))
        self.assertTrue(all(any(n in e.title for n in ITEMS) for e in orders))   # 품목명은 공백·괄호를 포함할 수 있음

    def test_build_events_range_and_order(self):
        custom = [Event(THU, "b", "staff"), Event(THU, "a", "event"), Event(THU + timedelta(days=40), "far", "event")]
        by_day = build_events(custom, [], CAL, THU, THU + timedelta(days=6))
        self.assertEqual([e.title for e in by_day[THU]], ["a", "b"])   # 분류 순서: event < staff
        self.assertNotIn(THU + timedelta(days=40), by_day)


def rec(item, supplier, order, arrival, status="URGENT", packs=2):
    return Recommendation(item, supplier, status, 1.0, order, order, arrival, packs, 0, "메시지")


class GroupedOrderEvents(unittest.TestCase):
    """품목이 수백 개여도 달력이 읽히도록 같은 업체·같은 날짜의 발주/입고는 한 줄로 묶는다."""

    def orders(self, recs):
        return [e for e in derived_events(recs, CAL, THU, THU + timedelta(days=10)) if e.category == "order"]

    def test_small_groups_stay_per_item(self):
        recs = [rec(f"품목{i}", "A사", THU, THU + timedelta(days=1)) for i in range(GROUP_LIMIT)]
        ev = self.orders(recs)
        self.assertEqual(len(ev), 2 * GROUP_LIMIT)                                 # 발주 + 입고
        self.assertTrue(any(e.title == "발주 품목0 2PK" for e in ev))

    def test_large_group_becomes_one_event_per_kind(self):
        recs = [rec(f"품목{i}", "CK", THU, THU + timedelta(days=1)) for i in range(GROUP_LIMIT + 3)]
        ev = self.orders(recs)
        self.assertEqual(sorted(e.title for e in ev), [f"발주 CK {GROUP_LIMIT + 3}개 품목", f"입고 CK {GROUP_LIMIT + 3}개 품목"])
        detail = next(e for e in ev if e.title.startswith("발주")).detail
        self.assertIn("품목0", detail)
        self.assertIn("외 1개", detail)                                              # 5개까지 이름을 보이고 나머지는 개수로
        self.assertFalse(any(e.deletable for e in ev))

    def test_groups_are_per_supplier_and_per_date(self):
        recs = [rec(f"가{i}", "CK", THU, THU + timedelta(days=1)) for i in range(5)]
        recs += [rec(f"나{i}", "B사", THU, THU + timedelta(days=1)) for i in range(2)]                 # 다른 업체는 따로
        recs += [rec("다", "CK", THU + timedelta(days=2), THU + timedelta(days=3))]                    # 같은 업체라도 날짜가 다르면 따로
        titles = sorted(e.title for e in self.orders(recs))
        self.assertIn("발주 CK 5개 품목", titles)
        self.assertIn("발주 나0 2PK", titles)
        self.assertIn("발주 다 2PK", titles)

    def test_non_actionable_items_are_ignored(self):
        recs = [rec(f"품목{i}", "CK", THU, THU + timedelta(days=1), status="OK") for i in range(10)]
        self.assertEqual(self.orders(recs), [])

    def test_master_stock_orders_match_actionable_recommendations(self):
        recs = recommendations(master_stock_g(), THU, CAL)
        ev = [e for e in derived_events(recs, CAL, THU, THU + timedelta(days=30)) if e.category == "order"]
        actionable = [r for r in recs if r.status in ("URGENT", "ORDER_NOW", "ORDER_SOON")]
        self.assertEqual(len(ev), 2 * len([r for r in actionable if r.order_date and r.arrival_date]))


class CellLayout(unittest.TestCase):
    def ev(self, title):
        return Event(THU, title, "event")

    def test_wider_cells_fit_more_text_and_events(self):
        narrow, wide = cell_width(790), cell_width(1140)
        self.assertLess(chars_per_line(narrow), chars_per_line(wide))
        self.assertEqual((max_cell_events(narrow), max_cell_events(wide)), (2, 3))
        self.assertGreaterEqual(chars_per_line(cell_width(100)), 3)   # 아주 좁아도 최소 3자

    def test_visible_events_overflow_shows_more_line(self):
        evs = [self.ev(str(i)) for i in range(5)]
        self.assertEqual(visible_events(evs[:2], 2), (evs[:2], 0))
        kept, hidden = visible_events(evs, 2)
        self.assertEqual((len(kept), hidden), (1, 4))        # 1개 + '+4건'
        kept, hidden = visible_events(evs, 3)
        self.assertEqual((len(kept), hidden), (2, 3))

    def test_row_height_follows_content(self):
        empty = row_height([([], 0, False)], 8)
        short = row_height([([self.ev("가나")], 0, False)], 8)
        long_ = row_height([([self.ev("가" * 30)], 0, False)], 8)
        self.assertEqual(empty, 100)
        self.assertLess(empty, short)
        self.assertLess(short, long_)                          # 긴 제목은 줄 수가 늘어 더 높음
        self.assertLessEqual(row_height([([self.ev("가" * 500)] * 3, 9, True)], 3), 320)  # 상한

    def test_row_height_uses_tallest_day(self):
        a = ([self.ev("가")], 0, False)
        b = ([self.ev("가"), self.ev("나")], 0, False)
        self.assertEqual(row_height([a, b], 8), row_height([b], 8))

    def test_empty_week_is_shorter_than_busy_week(self):
        busy = row_height([([self.ev("가나다라마바사"), self.ev("아자차카타파하")], 1, True)], 5)
        self.assertGreater(busy, row_height([([], 0, False)], 5))


EVENTS = [Event(THU, "오전 재고 실사", "event", "주방·창고 합동 실사", "e0"), Event(THU + timedelta(days=1), "신메뉴 시식회", "event", "오후 3시", "e1"),
          Event(THU + timedelta(days=2), "홀 직원 1명 결근 예정", "staff", "대체 인력 필요", "e2"),
          Event(THU - timedelta(days=2), "점심 매출 전주 대비 -18%", "sales", "공사로 유입 감소", "e3")]       # 테스트용 일정 (앱은 일정을 만들어 넣지 않는다)


class AgentAnswers(unittest.TestCase):
    def ctx(self):
        recs = recommendations(master_stock_g(), THU, CAL)
        ev = build_events(EVENTS, recs, CAL, THU, THU + timedelta(days=14))
        return AgentContext(THU, recs, ev)

    def test_order_question(self):
        self.assertIn("발주가 필요한", answer("지금 발주해야 할 품목은?", self.ctx()))

    def test_no_orders_needed(self):
        recs = recommendations({n: 10_000_000 for n in ITEMS}, THU, CAL)
        self.assertIn("없어요", answer("발주 필요한 거 있어?", AgentContext(THU, recs, {})))

    def test_week_schedule_and_today(self):
        c = self.ctx()
        self.assertIn("오전 재고 실사", answer("오늘 일정", c))
        self.assertIn("신메뉴 시식회", answer("이번 주 일정 알려줘", c))

    def test_staff_sales_issue_filter(self):
        a = answer("인력 이슈 있어?", self.ctx())
        self.assertIn("결근", a)
        self.assertNotIn("시식회", a)

    def test_closed_days_and_fallback(self):
        self.assertIn("10/18", answer("휴무일 언제야", self.ctx()))
        self.assertIn("답변할 수 없는", answer("메뉴 추천해줘", AgentContext(THU)))
        self.assertEqual(answer("  ", self.ctx()), "질문을 입력해 주세요.")

    def many(self, n):
        recs = [Recommendation(f"품목{i:02d}", "CK", "URGENT", float(i), THU, THU, THU + timedelta(days=1), 1, 0, "m") for i in range(n)]
        return AgentContext(THU, recs, {})

    def test_long_order_list_is_capped_with_total_count(self):
        a = answer("지금 발주해야 할 품목은?", self.many(30))
        self.assertIn("30개", a)
        self.assertEqual(a.count("\n- **"), 8)                                      # 상위 8개만 나열
        self.assertIn("외 22개", a)
        self.assertIn("자동 발주 추천", a)                                            # 전체를 볼 곳 안내
        short = answer("지금 발주해야 할 품목은?", self.many(3))
        self.assertEqual(short.count("\n- **"), 3)
        self.assertNotIn("외 ", short)

    def test_stock_summary_shows_counts_and_the_most_urgent(self):
        ctx = self.many(30)
        ctx.recs += [Recommendation(f"여유{i}", "CK", "OK", 90.0, THU, None, None, 0, 0, "m") for i in range(5)]
        ctx.recs += [Recommendation(f"무소비{i}", "CK", "NO_USAGE", None, None, None, None, 0, 0, "m") for i in range(7)]
        a = answer("재고 현황 요약", ctx)
        self.assertIn("전체 42개", a)
        for part in ("긴급 30", "양호 5", "소비 없음 7"):
            self.assertIn(part, a)
        self.assertEqual(a.count("\n- **"), 8)
        self.assertIn("품목00", a)                                                   # 잔여일이 가장 짧은 품목부터

    def test_topic_hint_uses_a_real_item(self):
        from agent import topic_questions
        from models import Item, Supplier
        s = Supplier("T", frozenset({0}), 1)
        items = {"가": Item("가", 1, 0, s), "나": Item("나", 1, 5, s)}
        q = topic_questions(items)
        self.assertIn("나 리드타임은?", q["리드타임 조회"])                              # 소비가 있는 첫 품목
        self.assertEqual(q["발주 추천"], TOPIC_BASE_ORDER)

    def test_stock_without_data(self):
        self.assertIn("재고 정보가 없어요", answer("재고 현황", AgentContext(THU)))


if __name__ == "__main__":
    unittest.main()
