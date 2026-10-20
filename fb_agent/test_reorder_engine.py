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


if __name__ == "__main__":
    unittest.main()
