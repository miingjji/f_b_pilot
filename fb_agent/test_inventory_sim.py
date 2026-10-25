"""inventory_sim: 소비·입고·재고 순환, 이미 발주한 입고, 동결과 검증을 작은 합성 자료로 확인한다 (실제 수불부·모델 파일에 의존하지 않는다)."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import inventory_sim as sim

MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04"]


class Cal:
    """월요일이 휴점인 달력."""
    @staticmethod
    def is_closed(d):
        return d.weekday() == 0


class Plan:
    """영업일마다 매출 1,000 (월요일 휴점). SalesPlan 의 최소 대역."""
    sc = Cal

    def day(self, d):
        return 0.0 if self.sc.is_closed(d) else 1000.0

    def monthly_actual(self, upto):
        return pd.Series({m: 26000.0 for m in MONTHS if m <= upto})


def ledger(counts: dict, receipts: dict, daily: dict | None = None) -> sim.Ledger:
    c = pd.DataFrame(counts, index=MONTHS).T
    r = pd.DataFrame(receipts, index=MONTHS).T
    meta = pd.DataFrame({"품명": [f"품목{k}" for k in c.index], "규격": "1kg", "거래처": "S", "계정": "원재료", "단가": 1000.0}, index=c.index)
    return sim.Ledger(c, r, daily or {}, meta, MONTHS)


def fitted(rate=0.002, level=10.0, Q=5.0, days=(1,), start=10.0, keys=("A",)) -> pd.DataFrame:
    f = pd.DataFrame({"rate": rate, "level": level, "Q": Q, "start": start}, index=list(keys))
    for i in range(7):
        f[f"w{i}"] = i in days
    return f


class Dates(unittest.TestCase):
    def test_month_arithmetic(self):
        self.assertEqual(sim.month_end("2026-02"), date(2026, 2, 28))
        self.assertEqual(sim.month_end("2026-12"), date(2026, 12, 31))
        self.assertEqual((sim.add_month("2026-11", 3), sim.add_month("2026-01", -1)), ("2027-02", "2025-12"))


class Fit(unittest.TestCase):
    def test_rate_is_consumption_per_sales_over_recent_months(self):
        # A: 매달 10 소비 (기초 10 + 입고 10 − 기말 10), 매출은 달마다 26,000
        L = ledger({"A": [10, 10, 10, 10], "D": [3, 3, 3, 3]}, {"A": [0, 10, 10, 10], "D": [0, 0, 0, 0]},
                   {"A": [(date(2026, 4, 7), 10.0), (date(2026, 3, 3), 10.0)]})
        f = sim.fit_items(L, "2026-04", Plan(), sim.Params(k_rate=2, k_event=3))
        self.assertAlmostEqual(f.loc["A", "rate"], 20 / 52000)
        self.assertEqual(f.loc["D", "rate"], 0)                      # 소비 없는 품목
        self.assertTrue(np.isnan(f.loc["D", "Q"]))                   # 입고가 없으니 입고 단위도 없다
        self.assertEqual((f.loc["A", "Q"], f.loc["A", "start"]), (10.0, 10.0))
        self.assertTrue(f.loc["A", "w1"] and not f.loc["A", "w2"])   # 화요일(1)에만 입고

    def test_only_ck_receives_on_sundays(self):
        sunday = [(date(2026, 4, 5), 3.0), (date(2026, 4, 12), 3.0), (date(2026, 4, 7), 3.0)]          # 일·일·화 입고 (일요일이 3분의 2)
        L = ledger({"A": [10, 10, 10, 10], "B": [10, 10, 10, 10]}, {"A": [0, 10, 10, 10], "B": [0, 10, 10, 10]}, {"A": sunday, "B": sunday})
        L.meta.loc["B", "거래처"] = "CK"
        f = sim.fit_items(L, "2026-04", Plan(), sim.Params(k_event=3))
        self.assertFalse(f.loc["A", "w6"])                           # 외부 업체는 일요일 입고가 없다
        self.assertTrue(f.loc["A", "w1"])
        self.assertTrue(f.loc["B", "w6"])                            # CK 는 일요일에도 입고

    def test_level_starts_when_the_item_is_first_used(self):
        # 1·2월에는 재고도 입고도 없다가 3월부터 쓰기 시작: 평소 수준은 쓰기 전의 0 을 빼고 본다 (기존: 0·0·8·6 의 중앙값 3, 이제: 8·6 의 중앙값 7)
        L = ledger({"A": [0, 0, 8, 6]}, {"A": [0, 0, 10, 10]}, {"A": [(date(2026, 4, 7), 10.0)]})
        self.assertEqual(sim.fit_items(L, "2026-04", Plan(), sim.Params(level_since_start=False)).loc["A", "level"], 3.0)
        self.assertEqual(sim.fit_items(L, "2026-04", Plan(), sim.Params()).loc["A", "level"], 7.0)

    def test_item_with_no_consumption_last_month_stops(self):
        # 2·3월에는 소비가 있었지만 4월(출발 달)에는 0: 끝난 시즌 품목으로 보고 소비 0
        L = ledger({"A": [10, 10, 10, 10], "B": [10, 10, 10, 6]}, {"A": [0, 10, 10, 0], "B": [0, 10, 10, 6]})
        f = sim.fit_items(L, "2026-04", Plan(), sim.Params(k_rate=3))
        self.assertEqual(f.loc["A", "rate"], 0.0)
        self.assertGreater(f.loc["B", "rate"], 0.0)
        self.assertGreater(sim.fit_items(L, "2026-04", Plan(), sim.Params(k_rate=3, stop_if_last_zero=False)).loc["A", "rate"], 0.0)

    def test_data_after_the_origin_is_not_used(self):
        L = ledger({"A": [10, 10, 10, 50]}, {"A": [0, 10, 10, 90]}, {"A": [(date(2026, 4, 7), 90.0)]})
        f = sim.fit_items(L, "2026-03", Plan(), sim.Params(k_rate=3))
        self.assertAlmostEqual(f.loc["A", "rate"], 20 / 52000)       # 4월(입고 90)이 소비 속도에 새지 않는다
        self.assertTrue(np.isnan(f.loc["A", "Q"]))


class Simulate(unittest.TestCase):
    ORIGIN = date(2026, 3, 31)

    def run_sim(self, f, end=date(2026, 4, 30), **kw):
        return sim.simulate(f, Plan(), self.ORIGIN, end, **kw)

    def test_stock_follows_consumption_and_receipts(self):
        r = self.run_sim(fitted(start=40.0, level=1.0))
        s, c, rc = r.stock["A"].to_numpy(), r.cons["A"].to_numpy(), r.receipts["A"].to_numpy()
        prev = np.r_[40.0, s[:-1]]
        self.assertTrue(np.allclose(s, np.maximum(prev - c + rc, 0)))
        self.assertAlmostEqual(r.cons["A"].sum(), 0.002 * 1000 * 26)  # 4월 영업일 26일 × 매출 1,000 × 속도
        self.assertEqual(r.cons.loc[date(2026, 4, 6), "A"], 0)       # 월요일 휴점은 소비 없음

    def test_receipts_come_only_on_receiving_weekdays_and_open_days(self):
        r = self.run_sim(fitted(start=0.0, level=10.0, days=(0, 1)))
        got = [d for d, q in r.receipts["A"].items() if q > 0]
        self.assertTrue(got and all(d.weekday() == 1 for d in got))   # 월요일은 쉬어서 화요일만

    def test_loop_closes_stock_back_toward_the_usual_level(self):
        r = self.run_sim(fitted(start=0.0, level=12.0, Q=5.0, days=(1, 3, 5)), lumps="cont")
        self.assertGreater(r.stock["A"].iloc[-1], 4.0)                # 비어 있던 재고가 입고로 채워진다
        self.assertLess(r.stock["A"].max(), 12.0 + 0.002 * 1000 * 4)  # 평소 수준을 크게 넘지 않는다
        low = self.run_sim(fitted(start=200.0, level=12.0, days=(1, 3, 5)))
        self.assertEqual(low.receipts["A"].sum(), 0)                  # 재고가 넉넉하면 입고하지 않는다

    def test_rounds_to_receiving_units(self):
        r = self.run_sim(fitted(start=0.0, level=12.0, Q=5.0, days=(1,)), lumps="round")
        self.assertTrue(all(abs(q / 5 - round(q / 5)) < 1e-9 for q in r.receipts["A"]))

    def test_scheduled_receipt_arrives_and_replaces_an_order(self):
        base = self.run_sim(fitted(start=3.0, level=10.0, days=(1, 3, 5)))
        sched = pd.DataFrame({"key": ["A"], "date": [date(2026, 4, 1)], "qty": [20.0]})
        r = self.run_sim(fitted(start=3.0, level=10.0, days=(1, 3, 5)), scheduled=sched)
        self.assertGreaterEqual(r.receipts.loc[date(2026, 4, 1), "A"], 20.0)
        self.assertLess(r.receipts.loc[date(2026, 4, 2):, "A"].sum(), base.receipts.loc[date(2026, 4, 2):, "A"].sum())   # 이미 들어올 입고만큼 덜 주문한다

    def test_dormant_items_are_not_simulated(self):
        f = pd.concat([fitted(keys=("A",)), fitted(rate=0.0, keys=("B",)), fitted(Q=np.nan, keys=("C",))])
        r = self.run_sim(f)
        self.assertEqual(r.sim_keys, ["A"])


class Tables(unittest.TestCase):
    def test_month_table_carries_dormant_items_and_sums_flows(self):
        f = pd.concat([fitted(start=20.0, keys=("A",)), fitted(rate=0.0, start=7.0, keys=("B",))])
        res = sim.simulate(f, Plan(), date(2026, 3, 31), date(2026, 4, 30))
        t = sim.month_table(f, res, "2026-03", 1).set_index("key")
        self.assertEqual((t.loc["B", "예상월말재고"], t.loc["B", "예상입고"], bool(t.loc["B", "시뮬레이션"])), (7.0, 0.0, False))
        self.assertAlmostEqual(t.loc["A", "예상소비"], res.cons["A"].sum())
        self.assertAlmostEqual(t.loc["A", "예상월말재고"], res.stock["A"].iloc[-1])

    def test_score_weights_by_price(self):
        price = pd.Series({"a": 1000.0, "b": 1.0})
        s = sim.score(pd.Series({"a": 10.0, "b": 0.0}), pd.Series({"a": 10.0, "b": 10.0}), price)
        self.assertAlmostEqual(s["WAPE_금액"], 10 / 10010)            # 비싼 품목이 맞으면 금액 오차는 작다
        self.assertAlmostEqual(s["WAPE_수량"], 10 / 20)


class Orders(unittest.TestCase):
    """발주일 예측: 입고일에서 업체 발주 요일·리드타임·휴점을 거꾸로 맞춘다. 2026-04: 6·13·20·27일(월)이 휴점."""
    LEADS = {w: 2 for w in range(7)}
    closed = staticmethod(lambda d: d.weekday() == 0)

    @staticmethod
    def next_open(d):
        while d.weekday() == 0:
            d += timedelta(days=1)
        return d

    def day_for(self, arrival, weekdays, leads=None):
        return sim.order_date_for(arrival, weekdays, leads or self.LEADS, self.closed, self.next_open)

    def test_order_date_is_arrival_minus_lead_on_an_order_weekday(self):
        self.assertEqual(self.day_for(date(2026, 4, 9), {1, 3}), date(2026, 4, 7))     # 목 입고 = 화 발주 + 2일
        self.assertEqual(self.day_for(date(2026, 4, 11), {1, 3}), date(2026, 4, 9))    # 토 입고 = 목 발주 + 2일

    def test_closed_days_push_the_arrival_so_an_earlier_order_day_is_used(self):
        # 토(4/4) 발주는 월(4/6, 휴점)에 도착해야 하니 화(4/7)로 밀린다 → 4/7 입고는 토 발주(4/4)
        self.assertEqual(self.day_for(date(2026, 4, 7), {5}), date(2026, 4, 4))
        self.assertIsNone(self.day_for(date(2026, 4, 7), set()))                       # 발주 요일이 없으면 없다

    def test_falls_back_to_the_latest_order_that_arrives_in_time(self):
        self.assertEqual(self.day_for(date(2026, 4, 10), {1}), date(2026, 4, 7))       # 정확히 맞는 날은 없고 화(4/7) 발주(4/9 입고)가 가장 늦은 안전한 날

    def test_orders_exclude_pipeline_receipts_and_items_without_purchase_history(self):
        days = [date(2026, 4, d) for d in (1, 2, 3)]
        rc = pd.DataFrame({"A": [4.0, 2.0, 0.0], "B": [1.0, 0.0, 0.0], "C": [5.0, 5.0, 0.0]}, index=days)
        sched = pd.DataFrame({"key": ["A"], "date": [date(2026, 4, 1)], "qty": [4.0]})       # A 의 4/1 입고는 이미 발주한 것
        fn = lambda k, a: a - timedelta(days=1)                                                # 발주일 = 입고 전날
        t = sim.orders_from_receipts(rc, sched, {"A": 1.0, "B": 2.0}, date(2026, 3, 31), fn)  # C 는 구매청구 이력이 없어 제외
        self.assertEqual([(r.품목코드, r.발주일, r.입고예정일, r.수량_발주단위) for r in t.itertuples()], [("A", date(2026, 4, 1), date(2026, 4, 2), 2.0)])   # B 의 4/1 입고는 3/31 발주라 출발 전

    def test_orders_before_the_origin_day_are_dropped(self):
        days = [date(2026, 4, d) for d in (1, 3)]
        rc = pd.DataFrame({"A": [1.0, 2.0]}, index=days)
        fn = lambda k, a: a - timedelta(days=2)                                                # 4/1 입고 → 3/30 발주(출발 전) 제외, 4/3 입고 → 4/1 발주
        t = sim.orders_from_receipts(rc, None, {"A": 2.0}, date(2026, 3, 31), fn)
        self.assertEqual([(r.발주일, r.입고예정일, r.수량_수불부, r.수량_발주단위) for r in t.itertuples()], [(date(2026, 4, 1), date(2026, 4, 3), 2.0, 4.0)])


class Frozen(unittest.TestCase):
    def test_frozen_forecast_is_not_overwritten(self):
        out = Path(tempfile.mkdtemp())
        (out / "2026-09_출발").mkdir()
        with self.assertRaises(FileExistsError):
            sim.forecast("2026-09", out_dir=out)

    def test_verify_compares_the_frozen_forecast_with_the_actual_month(self):
        out = Path(tempfile.mkdtemp())
        d = out / "2026-03_출발"
        d.mkdir()
        pd.DataFrame({"월": ["2026-04"] * 2, "key": ["A", "B"], "시뮬레이션": [True, False], "출발재고": [10.0, 5.0],
                      "예상월말재고": [12.0, 5.0], "예상입고": [20.0, 0.0], "예상소비": [20.0, 0.0]}).to_csv(d / "월별_예측.csv", index=False)
        L = ledger({"A": [9, 10, 10, 14], "B": [5, 5, 5, 5]}, {"A": [0, 10, 10, 22], "B": [0, 0, 0, 0]})
        R = sim.verify("2026-04", out_dir=out, L=L).set_index(["범위", "대상", "방법"])
        self.assertAlmostEqual(R.loc[("시뮬레이션 품목", "월말 재고", "시뮬레이션"), "WAPE_수량"], 2 / 14)    # |12 − 14| / 14
        self.assertAlmostEqual(R.loc[("시뮬레이션 품목", "월말 재고", "출발재고 그대로"), "WAPE_수량"], 4 / 14)
        self.assertAlmostEqual(R.loc[("시뮬레이션 품목", "월 소비", "시뮬레이션"), "WAPE_수량"], 2 / 18)     # 실제 소비 = 10 + 22 − 14 = 18
        self.assertEqual(R.loc[("전체 품목", "월말 재고", "시뮬레이션"), "n"], 2)
        self.assertTrue((d / "검증_2026-04_품목별.csv").exists() and (d / "검증_2026-04_요약.csv").exists())

    def test_verify_orders_matches_plan_to_actual_purchase_requests(self):
        from types import SimpleNamespace
        out = Path(tempfile.mkdtemp())
        d = out / "2026-03_출발"
        d.mkdir()
        pd.DataFrame({"발주일": ["2026-04-07", "2026-04-14", "2026-04-21"], "품목코드": ["A", "A", "B"]}).to_csv(d / "발주일_예측.csv", index=False)
        g = lambda days: pd.DataFrame({"청구일자": days})
        book = SimpleNamespace(orders=pd.DataFrame({"청구일자": [date(2026, 4, 30)]}),
                               by_item={("A", "a", ""): g([date(2026, 4, 7), date(2026, 4, 15), date(2026, 4, 30)]), ("B", "b", ""): g([date(2026, 4, 28)])})
        R = sim.verify_orders("2026-04", out_dir=out, book=book).set_index("허용 오차(일)")
        self.assertEqual((R.loc[0, "예측 발주"], R.loc[0, "실제 발주"]), (3, 4))
        self.assertAlmostEqual(R.loc[0, "정밀도"], 1 / 3)       # 같은 날: 4/7 만 맞음
        self.assertAlmostEqual(R.loc[1, "정밀도"], 2 / 3)       # ±1일: 4/14↔4/15 도 맞음
        self.assertAlmostEqual(R.loc[1, "재현율"], 2 / 4)
        mid = SimpleNamespace(orders=pd.DataFrame({"청구일자": [date(2026, 4, 15)]}), by_item=book.by_item)                 # 구매청구가 4/15 까지만 있다
        M = sim.verify_orders("2026-04", out_dir=out, book=mid).set_index("허용 오차(일)")
        self.assertEqual(M.loc[0, "비교 기간"], "2026-04-01~2026-04-15")                                                   # 그 날까지만 견준다
        self.assertEqual((M.loc[0, "예측 발주"], M.loc[0, "실제 발주"]), (2, 2))                                            # 예측 4/7·4/14, 실제 4/7·4/15 (4/21·4/28·4/30 은 기간 밖)
        self.assertAlmostEqual(M.loc[0, "정밀도"], 1 / 2)
        self.assertAlmostEqual(M.loc[1, "재현율"], 1.0)
        early = SimpleNamespace(orders=pd.DataFrame({"청구일자": [date(2026, 3, 31)]}), by_item={})
        with self.assertRaises(FileNotFoundError):
            sim.verify_orders("2026-04", out_dir=out, book=early)                              # 구매청구가 그 달에 닿지 않으면 비교하지 않는다

    def test_verify_po_receipts_compares_expected_receipts_with_actual_arrivals(self):
        from types import SimpleNamespace
        out = Path(tempfile.mkdtemp())
        d = out / "2026-03_출발"
        d.mkdir()
        pd.DataFrame({"일자": ["2026-04-02", "2026-04-09", "2026-04-20"], "key": ["A", "A", "A"], "예상입고": [4.0, 4.0, 4.0]}).to_csv(d / "일별_예측.csv", index=False)
        L = ledger({"A": [1, 1, 1, 1]}, {"A": [0, 10, 20, 10]})                                                         # 발주단위와 같은 단위 (비율 1: 2월 10, 3월 20)
        orders = pd.DataFrame({"품목코드_RMS": ["A", "A", "A", "A", "A", "A"],
                               "도착": [date(2026, 2, 10), date(2026, 3, 10), date(2026, 3, 20), date(2026, 4, 2), date(2026, 4, 8), date(2026, 4, 20)],
                               "수량": [10.0, 10.0, 10.0, 6.0, 6.0, 6.0], "청구일자": [date(2026, 2, 8)] * 3 + [date(2026, 4, 1)] * 3})
        book = SimpleNamespace(orders=orders.assign(청구일자=[date(2026, 2, 8), date(2026, 3, 8), date(2026, 3, 18), date(2026, 3, 30), date(2026, 4, 6), date(2026, 4, 15)]))
        R = sim.verify_po_receipts("2026-04", out_dir=out, book=book, L=L).set_index("방법")
        self.assertEqual(R.loc["시뮬레이션", "예측 합"], 8.0)                                                              # 4/2 와 4/9 의 예상 입고 4+4 (4/20 은 구매청구가 4/15 까지라 비교 밖)
        self.assertEqual(R.loc["시뮬레이션", "실제 입고 합"], 12.0)                                                         # 4/2 6 + 4/8 6 (4/20 은 비교 밖)
        self.assertAlmostEqual(R.loc["시뮬레이션", "WAPE"], 4 / 12)
        self.assertAlmostEqual(R.loc["시뮬레이션", "편향"], -4 / 12)

    def test_verify_waits_for_the_month_to_exist(self):
        L = ledger({"A": [1, 1, 1, 1]}, {"A": [0, 0, 0, 0]})
        with self.assertRaises(FileNotFoundError):
            sim.verify("2026-05", L=L)


if __name__ == "__main__":
    unittest.main()
