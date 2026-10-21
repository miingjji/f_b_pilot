"""reorder_engine: 확률 모델 계산, 시즌 판정, 추천 규칙을 작은 합성 자료로 확인한다 (실제 자료·저장된 모델 파일에 의존하지 않는다)."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import reorder_engine as re_

K = ("0001", "대파", "1kg")


def make_book(orders_by_item: dict, start=date(2025, 1, 1), end=date(2025, 12, 31)) -> re_.Book:
    """orders_by_item: {키: [(청구일, 수량), ...]}. 모든 주문은 1일 뒤 도착, 거래처는 'S'. 매출은 매일 300만 원."""
    rows = []
    for key, orders in orders_by_item.items():
        for d, q in orders:
            rows.append(dict(거래처="S", 품목코드_RMS=key[0], 품명=key[1], 규격=key[2], 발주단위="팩", 청구일자=d, 수량=float(q), 도착=d + timedelta(days=1)))
    o = pd.DataFrame(rows)
    lines = o.assign(리드=1)[["거래처", "청구일자", "리드"]]
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    daily = pd.Series(3_000_000.0, index=days)
    by_item = {k: g.sort_values("청구일자").reset_index(drop=True) for k, g in o.groupby(re_.K)}
    return re_.Book(o, lines, daily, by_item)


def every(start: date, end: date, step: int, q: float, skip_sunday=True):
    d, out = start, []
    while d <= end:
        if not (skip_sunday and d.weekday() == 6):
            out.append((d, q))
        d += timedelta(days=step)
    return out


class Logistic(unittest.TestCase):
    def test_fit_learns_a_clear_signal(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(2000, 2))
        y = (x[:, 0] + 0.3 * rng.normal(size=2000) > 0).astype(float)
        w = re_.fit_logistic(x, y)
        self.assertGreater(w[1], 1.0)
        self.assertLess(abs(w[2]), 0.3)

    def test_auc_perfect_random_and_reversed(self):
        y = np.array([0, 0, 1, 1])
        self.assertEqual(re_.auc(y, np.array([.1, .2, .8, .9])), 1.0)
        self.assertEqual(re_.auc(y, np.array([.9, .8, .2, .1])), 0.0)
        self.assertAlmostEqual(re_.auc(y, np.array([.5, .5, .5, .5])), 0.5)

    def test_precision_recall_f1(self):
        p, r, f = re_.prf(np.array([1, 1, 0, 0]), np.array([1, 0, 1, 0]))
        self.assertEqual((p, r), (0.5, 0.5))
        self.assertAlmostEqual(f, 0.5)

    def test_model_roundtrip_and_threshold(self):
        rng = np.random.default_rng(1)
        rows = pd.DataFrame(rng.normal(size=(500, len(re_.FEATURES))), columns=re_.FEATURES)
        rows["실제발주"] = (rows["gapratio"] > 0).astype(float)
        m = re_.TimingModel.fit(rows, {"학습기간": "test"})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            m.save(path)
            m2 = re_.TimingModel.load(path)
        feat = {f: 0.0 for f in re_.FEATURES}
        self.assertAlmostEqual(m.prob(feat), m2.prob(feat))
        self.assertGreater(m2.prob({**feat, "gapratio": 2.0}), m2.prob({**feat, "gapratio": -2.0}))
        self.assertIsNone(re_.TimingModel.load(Path(d) / "없음.json"))


class SeasonAndRules(unittest.TestCase):
    def test_season_states_for_a_summer_item(self):
        summer = [(date(2025, 5, 3) + timedelta(days=3 * i), 2) for i in range(40) if date(2025, 5, 3) + timedelta(days=3 * i) <= date(2025, 8, 30)]
        e = re_.Engine(book=make_book({K: summer}, end=date(2027, 12, 31)), hist=pd.Series(dtype=float), model=None)
        g = e.b.by_item[K]
        self.assertEqual(e.season_state(g, date(2025, 8, 20)), "")                          # 1년치 이력이 아직 없다 (비수기 달이 4개월 미만)
        g2 = pd.concat([g, g.assign(청구일자=[d + timedelta(days=365) for d in g["청구일자"]])], ignore_index=True)
        self.assertEqual(e.season_state(g2, date(2026, 7, 1)), "성수기")                    # 최근 45일 주문 있음
        self.assertEqual(e.season_state(g2, date(2026, 10, 15)), "비수기")                  # 작년 이맘때도 없었음
        self.assertEqual(e.season_state(g2, date(2027, 5, 1)), "시즌 시작 예상")             # 작년 5월엔 주문이 있었음

    def test_regular_item_every_three_days_waits_then_orders(self):
        daily_item = ("0002", "쌀", "20kg")
        book = make_book({K: every(date(2025, 6, 2), date(2025, 12, 14), 3, 2), daily_item: every(date(2025, 6, 2), date(2025, 12, 20), 1, 1)})
        e = re_.Engine(book=book, hist=pd.Series(3_000_000.0, index=list(book.daily.index)), model=None)
        last = book.by_item[K]["청구일자"].iloc[-1]
        not_sunday = lambda d: d if d.weekday() != 6 else d + timedelta(days=1)
        early = not_sunday(last + timedelta(days=1))
        due = not_sunday(last + timedelta(days=3))
        self.assertEqual(e.recommend_item(K, early)["상태"], "보류")                           # 평소 주기(3일)의 절반도 안 지남
        self.assertEqual(e.recommend_item(K, due)["상태"], "발주")                             # 평소 주기가 지남
        self.assertGreaterEqual((due - last).days, 3)

    def test_quantity_is_the_usual_order_size_and_rounds_to_whole_packs(self):
        book = make_book({K: every(date(2025, 6, 2), date(2025, 12, 19), 2, 3)})
        hist = pd.Series(3_000_000.0, index=list(book.daily.index))
        r = re_.Engine(book=book, hist=hist, model=None).recommend_item(K, date(2025, 12, 20))
        self.assertEqual(r["기준수량"], 3.0)
        self.assertEqual(r["권장수량"] % 1, 0)
        self.assertAlmostEqual(r["규모비"], 1.0, delta=0.15)                                 # 매출이 평소와 같으면 규모비 ≈ 1
        self.assertEqual(r["권장수량"], 3.0)

    def test_on_hand_overrides_the_habit_rule(self):
        book = make_book({K: every(date(2025, 6, 2), date(2025, 12, 19), 2, 3)})
        hist = pd.Series(3_000_000.0, index=list(book.daily.index))
        e = re_.Engine(book=book, hist=hist, model=None)
        self.assertEqual(e.recommend_item(K, date(2025, 12, 20), on_hand=0.0)["상태"], "발주")
        self.assertEqual(e.recommend_item(K, date(2025, 12, 20), on_hand=999.0)["상태"], "보류")

    def test_rare_items_are_not_regular(self):
        book = make_book({K: [(date(2025, 3, 3), 1), (date(2025, 9, 1), 1)], ("0002", "쌀", "20kg"): every(date(2025, 6, 2), date(2025, 12, 19), 1, 1)})
        e = re_.Engine(book=book, hist=pd.Series(3_000_000.0, index=list(book.daily.index)), model=None)
        self.assertEqual(e.recommend_item(K, date(2025, 12, 20))["상태"], "불규칙")

    def test_day_after_data_ends_is_not_treated_as_zero_sales(self):
        book = make_book({K: every(date(2025, 6, 2), date(2025, 12, 19), 1, 1)}, end=date(2025, 12, 10))
        e = re_.Engine(book=book, hist=pd.Series(3_000_000.0, index=list(book.daily.index)), model=None)
        self.assertEqual(e.day_sales(date(2025, 12, 20), date(2025, 12, 15)), e.fc(date(2025, 12, 20), date(2025, 12, 15)))   # 자료가 끝난 뒤는 예측
        self.assertEqual(e.day_sales(date(2025, 12, 20), date(2025, 12, 5)), 3_000_000.0)                                    # 자료가 있으면 실제


class StockFromCounts(unittest.TestCase):
    def setUp(self):
        self.book = make_book({K: every(date(2025, 6, 2), date(2025, 12, 19), 2, 3)})
        self.hist = pd.Series(3_000_000.0, index=list(self.book.daily.index))

    def engine(self, counts):
        return re_.Engine(book=self.book, hist=self.hist, model=None, counts=counts)

    def test_estimate_is_count_plus_arrivals_minus_expected_use(self):
        e = self.engine({K[0]: [(date(2025, 12, 10), 6.0)]})
        D = date(2025, 12, 13)
        r = e.recommend_item(K, D, use_stock=True)
        g = self.book.by_item[K]
        got = float(g[(g["도착"] > date(2025, 12, 10)) & (g["도착"] < D)]["수량"].sum())
        rate = float(g[(g["청구일자"] >= D - timedelta(days=re_.WINDOW)) & (g["청구일자"] < D)]["수량"].sum()) / sum(3_000_000.0 for _ in range(re_.WINDOW))
        self.assertAlmostEqual(r["재고"], max(0.0, 6.0 + got - rate * 3_000_000.0 * 2), places=6)   # 실사 다음 날(12-11)부터 전날(12-12)까지 2일

    def test_old_count_is_not_used(self):
        e = self.engine({K[0]: [(date(2025, 11, 30), 6.0)]})
        r = e.recommend_item(K, date(2025, 12, 20), use_stock=True)
        self.assertTrue(np.isnan(r["재고"]))
        self.assertEqual(r["상태"], e.recommend_item(K, date(2025, 12, 20))["상태"])           # 습관 판단 그대로

    def test_use_stock_off_changes_nothing(self):
        e = self.engine({K[0]: [(date(2025, 12, 18), 0.0)]})
        D = date(2025, 12, 20)
        a, b = e.recommend_item(K, D), e.recommend_item(K, D, use_stock=False)
        self.assertEqual((a["상태"], a["사유"]), (b["상태"], b["사유"]))
        self.assertTrue(np.isnan(a["재고"]))

    def test_stock_resolves_long_cycle_items(self):
        long_item = ("0003", "카레", "1kg")
        book = make_book({long_item: every(date(2025, 3, 3), date(2025, 12, 14), 20, 4), K: every(date(2025, 6, 2), date(2025, 12, 19), 2, 3)})
        hist = pd.Series(3_000_000.0, index=list(book.daily.index))
        D = date(2025, 12, 17)
        r0 = re_.Engine(book=book, hist=hist, model=None, counts={}).recommend_item(long_item, D)
        self.assertEqual(r0["상태"], "재고 확인")
        low = re_.Engine(book=book, hist=hist, model=None, counts={"0003": [(date(2025, 12, 15), 0.0)]}).recommend_item(long_item, D, use_stock=True)
        high = re_.Engine(book=book, hist=hist, model=None, counts={"0003": [(date(2025, 12, 15), 999.0)]}).recommend_item(long_item, D, use_stock=True)
        self.assertEqual((low["상태"], high["상태"]), ("발주", "보류"))

    def test_ample_stock_flags_a_habit_order(self):
        # 모델이 없으면 확률이 없어 주의를 붙이지 않는다 → 간단한 모델로 확률을 만든다
        feat = re_.FEATURES
        rows = pd.DataFrame(np.zeros((40, len(feat))), columns=feat)
        rows["gapratio"] = np.r_[np.zeros(20), np.ones(20) * 2]
        rows["실제발주"] = np.r_[np.zeros(20), np.ones(20)]
        model = re_.TimingModel.fit(rows)
        last = self.book.by_item[K]["청구일자"].iloc[-1]
        D = last + timedelta(days=3) if (last + timedelta(days=3)).weekday() != 6 else last + timedelta(days=4)
        E = D - timedelta(days=1)
        e = re_.Engine(book=self.book, hist=self.hist, model=model, counts={K[0]: [(E, 500.0)]})
        r = e.recommend_item(K, D, use_stock=True)
        self.assertEqual(r["상태"], "발주")                                                   # 판단은 습관 그대로
        self.assertEqual(r["재고주의"], "재고 넉넉")
        self.assertIn("재고가 넉넉할 수 있음", r["사유"])


class LoadCounts(unittest.TestCase):
    def write_month(self, root: Path, ym: str, count_qty: float, receipt_qty: float, code="0001"):
        d = root / ym[:4] / ym
        d.mkdir(parents=True)
        pd.DataFrame({"품목코드_RMS": [code, "없음"], "재고실사_수량": [count_qty, 5.0]}).to_csv(d / "실사재고_정제.csv", index=False)
        pd.DataFrame({"품목코드_RMS": [code], "당월합계_수량": [receipt_qty]}).to_csv(d / "입고내역_정제.csv", index=False)

    def book_with(self, per_month: dict):
        orders = []
        for ym, q in per_month.items():
            orders.append((date(int(ym[:4]), int(ym[5:]), 10), q))
        return make_book({K: orders}, start=date(2025, 1, 1), end=date(2025, 12, 31))

    def test_factor_from_order_vs_receipt_and_month_end_dates(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for ym in ("2025-01", "2025-02", "2025-03"):
                self.write_month(root, ym, 3.0, 10.0)
            counts = re_.load_counts(self.book_with({"2025-01": 5, "2025-02": 5, "2025-03": 5}), root)
        self.assertEqual([d for d, _ in counts["0001"]], [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)])
        self.assertEqual([q for _, q in counts["0001"]], [1.5, 1.5, 1.5])                    # 주문 5 : 수불부 입고 10 → 환산 0.5
        self.assertNotIn("없음", counts)

    def test_unstable_ratio_drops_the_item(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for ym, r in (("2025-01", 10.0), ("2025-02", 2.0), ("2025-03", 7.0)):
                self.write_month(root, ym, 3.0, r)
            counts = re_.load_counts(self.book_with({"2025-01": 5, "2025-02": 5, "2025-03": 5}), root)
        self.assertEqual(counts, {})

    def test_no_ledger_directory(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(re_.load_counts(self.book_with({"2025-01": 5}), Path(t) / "없음"), {})


if __name__ == "__main__":
    unittest.main()
