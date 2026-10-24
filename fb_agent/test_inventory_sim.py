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

    def test_verify_waits_for_the_month_to_exist(self):
        L = ledger({"A": [1, 1, 1, 1]}, {"A": [0, 0, 0, 0]})
        with self.assertRaises(FileNotFoundError):
            sim.verify("2026-05", L=L)


if __name__ == "__main__":
    unittest.main()
