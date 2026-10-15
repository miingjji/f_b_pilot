import unittest
from datetime import date, timedelta

from agent import AgentContext, answer
from calendar_data import (Event, build_events, cell_width, chars_per_line, derived_events, max_cell_events,
                           new_event, row_height, sample_events, visible_events)
from data import DEFAULT_CALENDAR, ITEMS
from errors import InvalidInputError
from insights import recommendations, sample_stock_g
from models import StoreCalendar

THU = date(2026, 10, 15)  # 목요일
CAL = DEFAULT_CALENDAR    # 일요일 휴무


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
        recs = recommendations(sample_stock_g(), THU, CAL)
        evs = derived_events(recs, CAL, THU, THU + timedelta(days=30))
        orders = [e for e in evs if e.category == "order"]
        actionable = [r for r in recs if r.status in ("URGENT", "ORDER_NOW", "ORDER_SOON")]
        self.assertTrue(actionable)
        self.assertEqual(len(orders), 2 * len([r for r in actionable if r.order_date and r.arrival_date]))
        self.assertTrue(all(e.title.split()[1] in ITEMS for e in orders))

    def test_build_events_range_and_order(self):
        custom = [Event(THU, "b", "staff"), Event(THU, "a", "event"), Event(THU + timedelta(days=40), "far", "event")]
        by_day = build_events(custom, [], CAL, THU, THU + timedelta(days=6))
        self.assertEqual([e.title for e in by_day[THU]], ["a", "b"])   # 분류 순서: event < staff
        self.assertNotIn(THU + timedelta(days=40), by_day)

    def test_samples_relative_to_today(self):
        s = sample_events(THU)
        self.assertTrue(all(e.sample and e.deletable for e in s))
        self.assertEqual(len({e.id for e in s}), len(s))


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


class AgentAnswers(unittest.TestCase):
    def ctx(self):
        recs = recommendations(sample_stock_g(), THU, CAL)
        ev = build_events(sample_events(THU), recs, CAL, THU, THU + timedelta(days=14))
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

    def test_stock_without_data(self):
        self.assertIn("재고 정보가 없어요", answer("재고 현황", AgentContext(THU)))


if __name__ == "__main__":
    unittest.main()
