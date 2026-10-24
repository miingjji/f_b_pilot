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


ITEMS = {"G": SimpleNamespace(name="간장 1kg", pk_weight_g=1000.0, current_stock=3000.0, lead_time_days=2, box_pk=1.0, base_unit="g"),     # 중량 품목: 수불부 1 = 1,000 g
         "C": SimpleNamespace(name="냅킨", pk_weight_g=1.0, current_stock=5.0, lead_time_days=3, box_pk=1.0, base_unit="개"),               # 개수 품목
         "U": SimpleNamespace(name="빨대", pk_weight_g=1.0, current_stock=None, lead_time_days=2, box_pk=1.0, base_unit="개")}              # 재고를 모르는 소모품


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


def make_requests(rows) -> Path:
    """구매청구 정제본 흉내: rows = (코드, 청구일, 납기일, 입고일 또는 None, 발주수량, 입고수량)."""
    root = Path(tempfile.mkdtemp())
    (root / "2026").mkdir()
    pd.DataFrame([{"청구일자": c, "납기일자": n, "입고일자": r or "미입고", "품목코드_RMS": k, "규격": "1kg/pk", "발주단위": "팩", "발주수량": q, "입고단위": "팩", "입고수량": g}
                  for k, c, n, r, q, g in rows]).to_csv(root / "2026" / "구매청구_정제.csv", index=False)
    return root


class ActualFlows(unittest.TestCase):
    """구매청구에 기록된 실제 입고·오는 중인 주문으로 시뮬레이션을 바로잡는다. 냅킨(C): 개수 품목, 간장(G): 1kg/pk 중량 품목(1 PK = 1,000g).
    예측: 냅킨은 10-02·10-04 에 3씩 입고, 재고 10-01 6 → 10-04 3. 간장은 입고 없음, 재고 10-04 2."""

    def setUp(self):
        self.fc = make_forecast()
        self.cl = make_requests([
            ("C", "2026-09-29", "2026-10-02", "2026-10-02", 3, 2),      # 10-02 에 (예상 3 대신) 2 도착
            ("C", "2026-10-03", "2026-10-06", None, 4, 0),              # 10-03 청구, 10-06 도착 예정 = 오는 중
            ("G", "2026-10-02", "2026-10-03", "2026-10-03", 1, 1),      # 간장은 예상 입고가 없었는데 1 PK 도착
        ])

    def test_actual_flows_split_arrived_and_in_transit(self):
        f = stock_sim.actual_flows(ITEMS, date(2026, 9, 30), date(2026, 10, 3), self.cl)
        self.assertEqual(f["arrived"], {"냅킨": 2.0, "간장 1kg": 1000.0})                     # 입고수량 → 기본단위 (1kg/pk → 1,000g)
        self.assertEqual(f["transit"], {"냅킨": 4.0})                                          # 10-04 아침: 10-03 청구, 10-06 도착 예정
        early = stock_sim.actual_flows(ITEMS, date(2026, 9, 30), date(2026, 10, 3), self.cl, placed_by=date(2026, 10, 2))
        self.assertEqual(early["transit"], {})                                                 # 10-02 까지 청구한 것만 보면 오는 중인 주문이 없다
        self.assertEqual((f["last_request"], f["last_receipt"], f["po_items"]), (date(2026, 10, 3), date(2026, 10, 3), {"냅킨", "간장 1kg"}))
        self.assertIsNone(stock_sim.actual_flows(ITEMS, date(2026, 9, 30), date(2026, 10, 3), Path(tempfile.mkdtemp())))   # 정제본이 없으면 None

    def test_actual_receipts_replace_simulated_receipts_in_the_stock(self):
        sim, info = stock_sim.sim_stock(date(2026, 10, 5), ITEMS, self.fc, Path(tempfile.mkdtemp()))        # 구매청구 정제본 없음 = 시뮬레이션 그대로
        adj, info2 = stock_sim.sim_stock(date(2026, 10, 5), ITEMS, self.fc, self.cl)
        self.assertEqual((sim["냅킨"], sim["간장 1kg"], info["actual_until"]), (3.0, 2000.0, None))
        # 실제 입고가 기록된 마지막 날(10-03)까지: 냅킨 3 − 시뮬레이션 누적 입고 3(10-02) + 실제 2 = 2, 간장 2,000 − 0 + 1,000 = 3,000
        self.assertEqual((adj["냅킨"], adj["간장 1kg"]), (2.0, 3000.0))
        self.assertEqual((info2["actual_until"], info2["actual_items"]), (date(2026, 10, 3), 2))

    def test_items_without_any_actual_flow_keep_the_simulation(self):
        cl = make_requests([("C", "2026-06-01", "2026-06-03", "2026-06-03", 1, 1)])           # 구매청구 이력은 있지만 10월 흐름이 없다 (휴면 의심)
        adj, info = stock_sim.sim_stock(date(2026, 10, 5), ITEMS, self.fc, cl)
        self.assertEqual((adj["냅킨"], info["actual_until"]), (3.0, None))

    def test_in_transit_orders_replace_simulated_inbound_for_purchase_items(self):
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 4), ITEMS, self.fc, self.cl), {"냅킨": 4.0})   # 실제 오는 중 4 (시뮬레이션 10-04 의 3 이 아니다)
        none = Path(tempfile.mkdtemp())
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 4), ITEMS, self.fc, none), {"냅킨": 3.0})        # 구매청구 정제본이 없으면 시뮬레이션: 10-04~10-06 입고 3
        later = make_requests([("C", "2026-09-29", "2026-10-02", "2026-10-02", 3, 2)])                          # 구매청구가 10-02 까지만 기록
        self.assertEqual(stock_sim.sim_inbound(date(2026, 10, 4), ITEMS, self.fc, later), {"냅킨": 3.0})        # 전날(10-03) 청구가 비어 있으면 시뮬레이션을 쓴다


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
