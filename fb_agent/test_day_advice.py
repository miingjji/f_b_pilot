"""구매청구 발주일 후보의 '(권장)' 판단 (day_advice)."""
import unittest
from datetime import date, timedelta
from types import SimpleNamespace as NS

from views.purchase import day_advice

TODAY = date(2026, 10, 27)
DAYS = [TODAY + timedelta(days=i) for i in (0, 2, 4, 7, 9)]           # 발주 가능일 5개


def item(name, lead):
    return NS(name=name, lead_time_days=lead)


def rec(order_date, stockout):
    return NS(order_date=order_date, stockout_date=stockout)


class DayAdviceTest(unittest.TestCase):
    def test_recommends_last_safe_day_and_warns_later_days(self):
        a = item("A", 3)
        info = {"A": (0, rec(TODAY + timedelta(days=4), TODAY + timedelta(days=8)))}   # 4일째까지 발주해야 안전
        best, out = day_advice([a], DAYS, info)
        self.assertEqual(best, DAYS[2])                                                 # 4일째 = 마지막 안전 발주일
        self.assertEqual(out[DAYS[2]], "권장")
        self.assertNotIn(DAYS[0], out)                                                  # 더 빠른 날은 문구 없음
        self.assertEqual(out[DAYS[3]], "결품 2일 예상")                                  # 7일째 발주 → 10일째 입고, 소진 8일째
        self.assertEqual(out[DAYS[4]], "결품 4일 예상")

    def test_strictest_item_decides(self):
        a, b = item("A", 3), item("B", 3)
        info = {"A": (0, rec(DAYS[4], DAYS[4] + timedelta(days=5))), "B": (0, rec(DAYS[1], TODAY + timedelta(days=6)))}
        self.assertEqual(day_advice([a, b], DAYS, info)[0], DAYS[1])

    def test_urgent_item_recommends_earliest_day(self):
        a = item("A", 5)
        info = {"A": (0, rec(DAYS[0], TODAY + timedelta(days=1)))}                      # 이미 늦음: 가장 빠른 날 + 긴급
        best, out = day_advice([a], DAYS, info)
        self.assertEqual((best, out[DAYS[0]]), (DAYS[0], "권장"))

    def test_all_days_too_late_flags_fastest(self):
        a = item("A", 3)
        info = {"A": (0, rec(TODAY - timedelta(days=1), TODAY + timedelta(days=1)))}
        best, out = day_advice([a], DAYS, info)
        self.assertEqual((best, out[DAYS[0]]), (DAYS[0], "권장 · 가장 빠른 날"))

    def test_no_basis_no_advice(self):
        self.assertEqual(day_advice([item("A", 3)], DAYS, {"A": (0, rec(None, None))}), (None, {}))
        self.assertEqual(day_advice([], DAYS, {}), (None, {}))


if __name__ == "__main__":
    unittest.main()
