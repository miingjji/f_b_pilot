import unittest
from datetime import date
from data import DEFAULT_CALENDAR, ITEMS
from converter import parse_count, to_boxes, to_grams, to_packs, unit_to_grams
from models import StoreCalendar
from reorder import is_order_day, recommend
from errors import InvalidInputError

WED = date(2026, 10, 14)   # 수요일
J = ITEMS["짜사이"]        # 1000g/PK, 10PK/BOX, 450g/일, A식자재(월수금, D+1)
CAL = DEFAULT_CALENDAR     # 일요일 휴무


class Conversion(unittest.TestCase):
    def test_units(self):
        self.assertEqual(to_grams(J, 2, 300), 2300)
        self.assertEqual(to_grams(J, 1, 0, boxes=1), 11000)
        self.assertEqual(unit_to_grams(J, 2, "kg"), 2000)
        self.assertEqual(unit_to_grams(J, 1, "박스"), 10000)
        self.assertEqual(to_packs(J, 2300)[:2], (2, 300))
        self.assertEqual(to_boxes(J, 12300), (1, 2, 300))

    def test_parse(self):
        self.assertEqual(parse_count(J, "1BOX 2pk 300g"), 12300)
        self.assertEqual(parse_count(ITEMS["청양고추"], "10EA"), 100)

    def test_invalid(self):
        for bad in ["-1pk", "3dozen", "abc", ""]:
            with self.assertRaises(InvalidInputError): parse_count(J, bad)
        with self.assertRaises(InvalidInputError): parse_count(J, "5EA")  # EA 미등록
        with self.assertRaises(InvalidInputError): to_grams(J, -1, 0)
        with self.assertRaises(InvalidInputError): to_grams(J, "a", 0)
        with self.assertRaises(InvalidInputError): recommend(J, -5, WED, CAL)


class Schedule(unittest.TestCase):
    def test_order_day_rules(self):
        self.assertTrue(is_order_day(J, WED, CAL))
        self.assertFalse(is_order_day(J, date(2026, 10, 15), CAL))  # 목: A업체 발주 불가

    def test_store_closed_date(self):
        cal = StoreCalendar(closed_dates=frozenset({date(2026, 10, 16)}))
        self.assertFalse(is_order_day(J, date(2026, 10, 16), cal))  # 금 휴무: 발주 불가
        self.assertFalse(is_order_day(J, WED, StoreCalendar(closed_dates=frozenset({date(2026, 10, 15)}))))  # 입고일 휴무

    def test_sunday_arrival_skipped(self):
        # C농산(월/목, D+3): 목 발주 -> 일 입고(휴무)라 불가
        self.assertFalse(is_order_day(ITEMS["청양고추"], date(2026, 10, 15), CAL))


class Status(unittest.TestCase):
    def test_urgent_zero_stock(self):
        r = recommend(J, 0, WED, CAL)
        self.assertEqual(r.status, "URGENT")
        self.assertEqual(r.order_date, WED)

    def test_urgent_no_safe_slot(self):
        # 600g -> 1.3일 -> 소진 수(+1=목), 안전기한 수 -> 수요일 발주는 목 입고라 늦음
        self.assertEqual(recommend(J, 600, WED, CAL).status, "URGENT")

    def test_order_now(self):
        r = recommend(J, 1200, WED, CAL)   # 소진 금(2일), 기한 목, 오늘 발주(목 입고)가 마지막
        self.assertEqual(r.status, "ORDER_NOW")
        self.assertEqual(r.order_date, WED)
        self.assertEqual(r.order_packs, 3)  # 450*(1+1+7)-1200=2850 -> 3PK

    def test_order_soon_waits_for_next_slot(self):
        r = recommend(J, 2000, WED, CAL)   # 4.4일 -> 소진 일(4일 후), 기한 토, 금 발주(토 입고) 가능
        self.assertEqual(r.status, "ORDER_SOON")
        self.assertEqual(r.order_date, date(2026, 10, 16))

    def test_ok(self):
        self.assertEqual(recommend(J, 10000, WED, CAL).status, "OK")

    def test_holiday_pushes_to_urgent(self):
        cal = StoreCalendar(closed_dates=frozenset({WED}))   # 오늘 휴무 -> 오늘 발주 불가
        self.assertEqual(recommend(J, 1200, WED, cal).status, "URGENT")

    def test_no_usage(self):
        self.assertEqual(recommend(ITEMS["춘장"], 100, WED, CAL).status, "NO_USAGE")


if __name__ == "__main__":
    unittest.main()
