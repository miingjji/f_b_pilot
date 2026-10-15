import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import unittest
from datetime import date, timedelta

import sample_data as sd
from agent import AgentContext, answer
from data import DEFAULT_CALENDAR
from insights import Alert, build_alerts, recommendations, sample_stock_g

D = date(2026, 10, 15)
STORES = ["강남점", "홍대점", "판교점"]       # 샘플 매장 (수원점은 실제 모드용 규모만 추가됨)


class Determinism(unittest.TestCase):
    def test_same_inputs_same_numbers(self):
        self.assertEqual(sd.day_sales("강남점", D), sd.day_sales("강남점", D))
        a, b = sd.daily_sales("강남점", D, 30), sd.daily_sales("강남점", D, 30)
        self.assertTrue(a.equals(b))

    def test_stores_differ_and_scale(self):
        sales = {s: sd.daily_sales(s, D, 60)["sales"].sum() for s in STORES}
        self.assertEqual(len(set(sales.values())), 3)
        self.assertLess(sales["홍대점"], sales["강남점"])       # 규모 0.8 < 1.0
        self.assertLess(sales["강남점"], sales["판교점"])       # 규모 1.0 < 1.2

    def test_weekend_is_busier_than_monday(self):
        df = sd.daily_sales("강남점", D, 90)
        by = df.groupby(df["date"].dt.weekday)["sales"].mean()
        self.assertGreater(by[5], by[0])


class Consistency(unittest.TestCase):
    def test_hourly_sums_close_to_day_total(self):
        for s in STORES:
            day = sd.day_sales(s, D)["sales"]
            hourly = sd.hourly_sales(s, D)["sales"].sum()
            self.assertAlmostEqual(hourly / day, 1.0, delta=0.02)

    def test_monthly_covers_requested_months(self):
        m = sd.monthly_sales("강남점", D, 12)
        self.assertEqual(len(m), 12)
        self.assertEqual(m["month"].iloc[-1], "2026-10")

    def test_menu_and_payment_shares_sum_to_100(self):
        t = sd.menu_table("강남점", D - timedelta(days=29), D)
        self.assertAlmostEqual(t["비중(%)"].sum(), 100, delta=0.2)
        p = sd.payment_share("강남점", D - timedelta(days=29), D)
        self.assertAlmostEqual(p["비중(%)"].sum(), 100, delta=0.2)
        self.assertEqual(set(p["결제수단"]), {n for n, _ in sd.PAYMENTS})

    def test_settlement_math(self):
        s = sd.settlement("강남점", D, 7)
        self.assertTrue(((s["총매출"] - s["할인"]) == s["순매출"]).all())
        ch = sd.settlement_by_channel("강남점", D)
        self.assertTrue(((ch["순매출"] - ch["수수료"]) == ch["입금예정액"]).all())

    def test_cancellation_types_and_sorting(self):
        c = sd.cancellations("강남점", D)
        self.assertTrue(set(c["유형"]) <= set(sd.CANCEL_TYPES))
        self.assertEqual(list(c["일시"]), sorted(c["일시"], reverse=True))


class Hr(unittest.TestCase):
    def test_schedule_shape_and_codes(self):
        df = sd.month_schedule("강남점", 2026, 10)
        self.assertEqual(df.shape, (len(sd.STAFF), 31))
        self.assertTrue(set(df.values.ravel()) <= set(sd.SHIFTS))

    def test_staffing_never_negative_and_min_two(self):
        df = sd.staffing_by_hour("강남점", D)
        self.assertTrue((df["적정 인력"] >= 2).all())
        self.assertTrue((df["배치 인력"] >= 0).all())

    def test_labor_ratio_is_in_realistic_range(self):
        df = sd.labor_cost("강남점", D, 30)
        total = df["labor"].sum() / df["sales"].sum() * 100
        self.assertTrue(15 < total < 40, f"L%={total:.1f}")

    def test_punch_hours_positive_and_only_on_work_days(self):
        p = sd.punch_records("강남점", D, 7)
        self.assertTrue((p["근무시간"] > 0).all())
        self.assertNotIn("휴무", set(p["근무"]))


class Alerts(unittest.TestCase):
    def recs(self, stock=None):
        return recommendations(stock or sample_stock_g(), D, DEFAULT_CALENDAR)

    def test_urgent_stock_becomes_high_alert_linking_to_auto_order(self):
        al = build_alerts("강남점", D, self.recs())
        high = [a for a in al if a.level == "high"]
        self.assertTrue(high)
        self.assertTrue(all(a.leaf == "po-auto" for a in high))

    def test_sorted_high_before_medium(self):
        order = {"high": 0, "medium": 1, "info": 2}
        for s in STORES:
            levels = [order[a.level] for a in build_alerts(s, D, self.recs())]
            self.assertEqual(levels, sorted(levels))

    def test_alert_targets_are_real_menu_leaves(self):
        from menu import has_leaf
        for s in STORES:
            for a in build_alerts(s, D, self.recs()):
                self.assertTrue(has_leaf(a.leaf), a)

    def test_plenty_of_stock_has_no_stock_alerts(self):
        big = {n: 10_000_000 for n in sample_stock_g()}
        self.assertFalse([a for a in build_alerts("강남점", D, self.recs(big)) if a.leaf == "po-auto"])


class AgentNewIntents(unittest.TestCase):
    def ctx(self, **kw):
        return AgentContext(D, [], {}, store="강남점", **kw)

    def test_lead_time_all_and_by_item(self):
        self.assertIn("A식자재", answer("거래처 리드타임 알려줘", self.ctx()))
        one = answer("짜사이 리드타임은?", self.ctx())
        self.assertIn("짜사이", one)
        self.assertNotIn("B유통", one)

    def test_schedule_with_and_without_data(self):
        self.assertIn("근무 정보가 아직 없어요", answer("오늘 근무 인원은?", self.ctx()))
        a = answer("인력 배치 부족한 시간대 있어?", self.ctx(staff_today=9, shortage_hours=["12시", "13시"]))
        self.assertIn("9명", a)
        self.assertIn("12시", a)

    def test_sales_question_vs_issue_question(self):
        c = self.ctx(sales_note="오늘 매출은 430만원")
        self.assertIn("430만원", answer("오늘 매출 어때?", c))
        self.assertNotIn("430만원", answer("매출 이슈 있어?", c))     # '이슈'는 일정 쪽 응답

    def test_existing_intents_still_win(self):
        self.assertIn("재고 정보가 없어요", answer("재고 현황", self.ctx()))


if __name__ == "__main__":
    unittest.main()
