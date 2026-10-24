"""stock_sim: 동결한 재고 예측에서 기준일 아침 재고를 꺼내 마스터 기본단위로 바꾸는 규칙을 작은 합성 예측으로 확인한다."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import stock_sim


def make_forecast() -> Path:
    root = Path(tempfile.mkdtemp())
    d = root / "2026-09_출발"
    d.mkdir()
    pd.DataFrame({"월": ["2026-10"] * 3, "key": ["G", "C", "U"], "출발재고": [4.0, 7.0, 2.0]}).to_csv(d / "월별_예측.csv", index=False)
    days = pd.date_range("2026-10-01", "2026-10-05")
    rows = [{"일자": f"{x:%Y-%m-%d}", "key": k, "예상재고": q0 - i * s, "예상입고": 3.0 if (k == "C" and i in (2, 4)) else 0.0}      # 냅킨은 10-02, 10-04 에 3씩 입고
            for k, q0, s in (("G", 4.0, 0.5), ("C", 7.0, 1.0)) for i, x in enumerate(days, 1)]
    pd.DataFrame(rows).to_csv(d / "일별_예측.csv", index=False)
    return root


ITEMS = {"G": SimpleNamespace(name="간장 1kg", pk_weight_g=1000.0, current_stock=3000.0, lead_time_days=2),     # 중량 품목: 수불부 1 = 1,000 g
         "C": SimpleNamespace(name="냅킨", pk_weight_g=1.0, current_stock=5.0, lead_time_days=3),               # 개수 품목
         "U": SimpleNamespace(name="빨대", pk_weight_g=1.0, current_stock=None, lead_time_days=2)}              # 재고를 모르는 소모품


class SimStock(unittest.TestCase):
    def setUp(self):
        self.root = make_forecast()

    def test_morning_stock_is_the_previous_days_end_converted_to_base_units(self):
        s, info = stock_sim.sim_stock(date(2026, 10, 3), ITEMS, self.root)
        self.assertEqual(s, {"간장 1kg": 3000.0, "냅킨": 5.0})                  # 10-02 말: G 4 − 2×0.5 = 3 (=3,000g), C 7 − 2 = 5
        self.assertEqual((info["origin"], info["asof"], info["clamped"], info["items"]), (date(2026, 9, 30), date(2026, 10, 2), False, 2))

    def test_first_day_after_the_count_uses_the_counted_stock_and_unknown_items_stay_unknown(self):
        s, info = stock_sim.sim_stock(date(2026, 10, 1), ITEMS, self.root)
        self.assertEqual(s, {"간장 1kg": 4000.0, "냅킨": 7.0})                  # 빨대는 마스터에서 재고를 모르므로 값을 만들지 않는다
        self.assertEqual(info["asof"], date(2026, 9, 30))

    def test_no_forecast_before_or_on_the_count_day(self):
        self.assertEqual(stock_sim.sim_stock(date(2026, 9, 30), ITEMS, self.root), ({}, None))
        self.assertEqual(stock_sim.sim_stock(date(2026, 9, 1), ITEMS, self.root), ({}, None))
        self.assertEqual(stock_sim.sim_stock(date(2026, 10, 3), ITEMS, Path(tempfile.mkdtemp())), ({}, None))

    def test_dates_after_the_forecast_ends_reuse_the_last_day_and_say_so(self):
        s, info = stock_sim.sim_stock(date(2026, 11, 20), ITEMS, self.root)
        self.assertEqual((s["냅킨"], info["asof"], info["clamped"]), (2.0, date(2026, 10, 5), True))

    def test_newest_origin_before_the_day_wins(self):
        d = self.root / "2026-10_출발"
        d.mkdir()
        pd.DataFrame({"월": ["2026-11"], "key": ["C"], "출발재고": [9.0]}).to_csv(d / "월별_예측.csv", index=False)
        pd.DataFrame({"일자": ["2026-11-01"], "key": ["C"], "예상재고": [8.0], "예상입고": [0.0]}).to_csv(d / "일별_예측.csv", index=False)
        self.assertEqual(stock_sim.sim_stock(date(2026, 11, 2), ITEMS, self.root)[0], {"냅킨": 8.0})
        self.assertEqual(stock_sim.sim_stock(date(2026, 10, 31), ITEMS, self.root)[1]["origin"], date(2026, 9, 30))   # 10월 말 전에는 9월 출발 예측


class SimInbound(unittest.TestCase):
    def setUp(self):
        self.root = make_forecast()

    def test_on_order_is_the_expected_receipts_inside_the_lead_time_window(self):
        # 냅킨(리드 3일): 10-01 아침 → 10-01~03 에 도착 = 10-02 의 3. 10-02 아침 → 10-02~04 = 3 + 3
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 1), ITEMS, self.root), {"냅킨": 3.0})
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 2), ITEMS, self.root), {"냅킨": 6.0})
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 5), ITEMS, self.root), {})        # 5일 이후 입고는 없다

    def test_window_follows_each_items_lead_time_and_converts_units(self):
        items = {**ITEMS, "C": SimpleNamespace(name="냅킨", pk_weight_g=10.0, current_stock=5.0, lead_time_days=1)}
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 2), items, self.root), {"냅킨": 30.0})   # 리드 1일: 오늘 도착분만, 수량 × 10

    def test_nothing_without_a_usable_forecast_or_after_it_ends(self):
        self.assertEqual(stock_sim.sim_inbound(date(2026, 9, 30), ITEMS, self.root), {})
        self.assertEqual(stock_sim.sim_inbound(date(2026, 11, 20), ITEMS, self.root), {})
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 2), ITEMS, Path(tempfile.mkdtemp())), {})

    def test_items_without_lead_time_or_stock_are_skipped(self):
        items = {"C": SimpleNamespace(name="냅킨", pk_weight_g=1.0, current_stock=5.0, lead_time_days=None)}
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 2), items, self.root), {})
        items = {"C": SimpleNamespace(name="냅킨", pk_weight_g=1.0, current_stock=None, lead_time_days=3)}
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 2), items, self.root), {})


class OrderPlan(unittest.TestCase):
    def test_plan_window_and_origin(self):
        root = make_forecast()
        pd.DataFrame({"발주일": ["2026-10-02", "2026-10-10", "2026-10-30"], "입고예정일": ["2026-10-04", "2026-10-12", "2026-11-01"],
                      "품목코드": ["C", "C", "C"], "수량_발주단위": [3.0, 3.0, 3.0]}).to_csv(root / "2026-09_출발" / "발주일_예측.csv", index=False)
        t = stock_sim.sim_order_plan(date(2026, 10, 1), 14, root)
        self.assertEqual(list(t["발주일"]), [date(2026, 10, 2), date(2026, 10, 10)])          # 14일 창 [10-01, 10-15)
        self.assertEqual(len(stock_sim.sim_order_plan(date(2026, 10, 11), 30, root)), 1)
        self.assertIsNone(stock_sim.sim_order_plan(date(2026, 9, 30), 14, root))               # 출발일 이후여야 쓴다
        self.assertIsNone(stock_sim.sim_order_plan(date(2026, 10, 1), 14, Path(tempfile.mkdtemp())))


if __name__ == "__main__":
    unittest.main()
