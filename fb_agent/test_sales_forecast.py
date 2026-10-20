"""sales_forecast: 일유형·예측·범위. 예측이 미래 값을 쓰지 않는지(누수)도 확인한다."""
import unittest
from datetime import date, timedelta

import pandas as pd

import sales_forecast as sf


def weekly(start: date, weeks: int, by_dow: dict) -> pd.Series:
    days = [start + timedelta(days=i) for i in range(weeks * 7)]
    return pd.Series([float(by_dow[d.weekday()]) for d in days], index=days)


class DayType(unittest.TestCase):
    def test_weekday_holiday_is_sunday_type_but_saturday_stays(self):
        self.assertEqual(sf.day_type(date(2026, 5, 5)), 6)       # 화요일 어린이날
        self.assertEqual(sf.day_type(date(2026, 10, 6)), 1)      # 평범한 화요일
        self.assertEqual(sf.day_type(date(2026, 6, 6)), 5)       # 토요일 현충일은 토요일형 그대로

    def test_labor_day_behaves_like_a_holiday(self):
        self.assertEqual(sf.day_type(date(2026, 5, 1)), 6)

    def test_constitution_day_2026_is_a_holiday_but_2025_was_not(self):
        self.assertEqual(sf.day_type(date(2026, 7, 17)), 6)      # 금요일 제헌절 (2026 부터 공휴일)
        self.assertEqual(sf.day_type(date(2025, 7, 17)), 3)      # 2025 는 평범한 목요일

    def test_designated_temporary_holidays_are_listed(self):
        for d in (date(2025, 1, 27), date(2025, 6, 3)):
            self.assertEqual(sf.day_type(d), 6, d)               # 월·화요일이지만 일요일형
        for d in (date(2025, 5, 2), date(2025, 10, 10), date(2026, 5, 4)):
            self.assertLess(sf.day_type(d), 5, d)                # 지정 안 됨 (후보였을 뿐)

    def test_eve_is_weekday_before_holiday_or_closure(self):
        self.assertTrue(sf.is_eve(date(2026, 5, 4)))             # 월 → 5/5 어린이날
        self.assertFalse(sf.is_eve(date(2026, 5, 5)))
        self.assertFalse(sf.is_eve(date(2026, 5, 2)))            # 토요일


class Bridge(unittest.TestCase):
    def test_bridge_days_are_found_from_the_calendar(self):
        for d in (date(2026, 5, 4), date(2025, 10, 10), date(2025, 1, 31), date(2027, 9, 13)):
            self.assertTrue(sf.is_bridge(d), d)                  # 양옆이 쉬는 날
        for d in (date(2026, 5, 5), date(2026, 5, 6), date(2026, 10, 3), date(2026, 10, 2)):
            self.assertFalse(sf.is_bridge(d), d)                 # 공휴일 자체, 연휴 다음날, 토요일, 한쪽만 쉬는 날

    def test_unconfirmed_monday_does_not_count_as_a_day_off(self):
        self.assertFalse(sf.is_off(date(2026, 10, 26)))          # 휴점 미확정


class LearnedBoost(unittest.TestCase):
    def setUp(self):
        days = [date(2025, 1, 2) + timedelta(days=i) for i in range(360)]
        self.h = pd.Series(100.0, index=days)
        for d in (date(2025, 1, 31), date(2025, 5, 2), date(2025, 6, 2), date(2025, 10, 10)):
            self.h[d] = 150.0                                    # 징검다리 평일만 평소의 1.5배

    def test_boost_is_the_median_ratio_once_three_are_known(self):
        self.assertEqual(sf.learned_boost(self.h, date(2025, 5, 31), "bridge"), 1.0)          # 2번뿐이라 아직 1.0
        self.assertAlmostEqual(sf.learned_boost(self.h, date(2025, 6, 30), "bridge"), 1.5)

    def test_boost_ignores_days_after_the_cut(self):
        a = sf.learned_boost(self.h, date(2025, 6, 30), "bridge")
        h2 = self.h.copy()
        h2[date(2025, 10, 10)] = 9999.0                          # cut 이후의 값은 영향이 없어야 한다
        self.assertEqual(sf.learned_boost(h2, date(2025, 6, 30), "bridge"), a)

    def test_forecast_multiplies_a_bridge_day_and_keeps_normal_days(self):
        self.assertAlmostEqual(sf.forecast(self.h, date(2025, 10, 10), season_weight=0, adjust=("bridge",)), 150.0)
        self.assertAlmostEqual(sf.forecast(self.h, date(2025, 10, 10), season_weight=0, adjust=()), 100.0)
        self.assertAlmostEqual(sf.forecast(self.h, date(2025, 10, 14), season_weight=0), 100.0)   # 평범한 화요일

    def test_bridge_days_do_not_inflate_the_next_weeks_base(self):
        h = self.h.copy()
        self.assertAlmostEqual(sf.forecast(h, date(2025, 6, 9), season_weight=0, adjust=("bridge",)), 100.0)   # 6/2 징검다리 월요일이 기준에서 빠짐


class Forecast(unittest.TestCase):
    def setUp(self):
        self.h = weekly(date(2026, 3, 2), 8, {0: 100, 1: 200, 2: 200, 3: 200, 4: 300, 5: 500, 6: 400})

    def test_same_weekday_median(self):
        self.assertEqual(sf.forecast(self.h, date(2026, 4, 28), season_weight=0), 200)     # 화요일
        self.assertEqual(sf.forecast(self.h, date(2026, 5, 2), season_weight=0), 500)      # 토요일

    def test_weekday_holiday_uses_sunday_history(self):
        self.assertEqual(sf.forecast(self.h, date(2026, 5, 5), season_weight=0), 400)      # 화요일 어린이날 → 일요일형
        self.assertEqual(sf.forecast(self.h, date(2026, 5, 5), season_weight=0, holiday_rule=False), 200)

    def test_does_not_use_future_values(self):
        h2 = self.h.copy()
        h2[date(2026, 4, 28)] = 10_000.0                                                   # 예측 대상 날의 '실제'
        self.assertEqual(sf.forecast(h2, date(2026, 4, 28), season_weight=0), 200)
        h3 = h2.copy()
        h3[date(2026, 4, 27)] = 99_999.0                                                   # 전날은 horizon=1 이면 알 수 있다
        self.assertEqual(sf.forecast(h3, date(2026, 4, 28), horizon=1, season_weight=0), 200)   # 요일이 다른 날은 영향 없음
        h4 = self.h.copy()
        h4[date(2026, 4, 21)] = 1000.0                                                      # 정확히 7일 전 같은 요일
        self.assertGreater(sf.forecast(h4, date(2026, 4, 28), horizon=1, season_weight=0), 200 - 1)
        self.assertEqual(sf.forecast(h4, date(2026, 4, 28), horizon=7, season_weight=0), 200)  # 7일 전 시점엔 아직 모른다

    def test_too_little_history_returns_none(self):
        self.assertIsNone(sf.forecast(self.h, date(2026, 3, 3), season_weight=0))

    def test_season_ratio_is_clipped_and_weighted(self):
        h = weekly(date(2025, 3, 3), 60, {k: 100 for k in range(7)})                      # 2026-04-26 까지 매일 100
        bump = [d for d in h.index if date(2025, 4, 30) <= d <= date(2025, 5, 13)]          # 작년 '다음 2주'만 10배
        h.loc[bump] = 1000.0
        target = date(2026, 4, 28)
        self.assertAlmostEqual(sf.forecast(h, target, season_weight=1.0), 100 * 1.33)       # 5.5배는 1.33 으로 자름
        self.assertAlmostEqual(sf.forecast(h, target, season_weight=0.5), 100 * 1.33 ** 0.5)
        self.assertEqual(sf.forecast(h, target, season_weight=0), 100)


class Bands(unittest.TestCase):
    def test_fit_and_apply(self):
        bt = pd.DataFrame({"actual": [80., 100., 120., 90., 110.], "pred": [100.] * 5, "group": ["평일"] * 5})
        b = sf.fit_bands(bt)
        self.assertLess(b["평일"][0], 1.0)
        self.assertGreater(b["평일"][1], 1.0)
        self.assertAlmostEqual(sf.wape(bt), 12.0)                # |차이| 합 60 ÷ 실제 합 500

if __name__ == "__main__":
    unittest.main()
