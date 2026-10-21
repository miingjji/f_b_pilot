"""store_calendar: 휴점 캘린더 규칙 (고정 휴점·월요일 미확정·실적 휴점이 모두 설명되는지)."""
import unittest
from datetime import date
from pathlib import Path

import store_calendar as sc

HAS_DATA = bool(list((Path(__file__).resolve().parent / "data" / "cleaned").glob("20*/매출일자별_정제.csv")))


class FixedRules(unittest.TestCase):
    def test_new_year_seollal_and_chuseok_with_eve(self):
        self.assertEqual(set(sc.fixed_closures(2026)), {date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17), date(2026, 9, 24), date(2026, 9, 25)})
        self.assertEqual(set(sc.fixed_closures(2025)), {date(2025, 1, 1), date(2025, 1, 28), date(2025, 1, 29), date(2025, 10, 5), date(2025, 10, 6)})

    def test_status_confirmed_open_and_unconfirmed_monday(self):
        self.assertEqual(sc.status(date(2027, 1, 1)), ("휴점", "신정"))
        self.assertEqual(sc.status(date(2026, 10, 27))[0], "영업")                  # 화요일
        self.assertEqual(sc.status(date(2026, 10, 26))[0], "미확정")                # 확정 휴점이 아닌 월요일

    def test_store_calendar_has_only_confirmed_dates_in_range(self):
        cal = sc.store_calendar(date(2026, 12, 1), date(2027, 2, 28))
        self.assertFalse(cal.is_open(date(2027, 1, 1)))
        self.assertTrue(cal.is_open(date(2026, 12, 7)))                           # 월요일이지만 미확정이라 열려 있다고 본다
        self.assertTrue(cal.is_open(date(2026, 11, 30)))                          # 범위 밖


@unittest.skipUnless(HAS_DATA, "정제된 일자별 매출이 없음")
class AgainstData(unittest.TestCase):
    def test_every_observed_closure_is_explained(self):
        self.assertNotIn("기타 무매출", sc.observed_closures().values())          # 고정 규칙이나 월요일로 모두 설명된다

    def test_fixed_closures_were_really_closed(self):
        obs = sc.observed_closures()
        for y in (2025, 2026):
            for d in sc.fixed_closures(y):
                if min(obs) <= d <= max(obs):
                    self.assertIn(d, obs, f"{d} 은 고정 휴점인데 매출이 있다")

    def test_monday_closure_rate_is_about_one_in_six(self):
        self.assertTrue(0.10 <= sc.monday_closure_rate() <= 0.25, sc.monday_closure_rate())


if __name__ == "__main__":
    unittest.main()
