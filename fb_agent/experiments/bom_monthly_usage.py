"""BOM 시험 ① 한 달 사용량: 그 달 판매량을 알 때 BOM 이 사용량 오차를 줄이는가.

    cd fb_agent && FB_MASTER=real python experiments/bom_monthly_usage.py

각 달 m 에 대해 전월 말까지의 자료로 품목별 한 달 사용량(전월 말 실사 + 당월 입고 − 당월 말 실사)을 예측하고 실제와 견준다. 입고는 실제값.
  · H1 = 최근 3개월 평균 소비 (그 달 매출을 모른다)
  · H2 = 최근 3개월 (소비 ÷ 매출) × 그 달 실제 매출
  · T  = 그 달 BOM 이론 사용량 × 품목별 보정비율 ÷ 환산단위 (BOM 이 없는 품목은 H2)
  · BL = (H2 + T) ÷ 2
대상: 2025-07 ~ 2026-09, 최근 3개월 안에 재고·입고가 있던 품목. 오차 = Σ|예측 − 실제| × 단가 ÷ Σ실제 × 단가 (금액 가중), 달별 값의 평균.
기대 결과: H1 25.5%, H2 20.8%, T 18.1%, BL 17.0% — 개선의 대부분은 BOM 이 아니라 '그 달 매출을 아는 것'(25.5 → 20.8)이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import bom_rate as B
import inventory_sim as I

FIRST, LAST = "2025-07", "2026-09"


def main() -> int:
    L = I.load_ledger()
    rev = I.SalesPlan(I.month_end(L.months[-1])).monthly_actual(L.months[-1])      # 월별 실제 POS 순매출
    cons, price = L.consumption, L.meta["단가"]
    rows = []
    for m in [x for x in L.months if FIRST <= x <= LAST]:
        origin = I.add_month(m, -1)
        ms = L.months[: L.months.index(origin) + 1]
        hist = ms[-3:]
        recent = cons[hist].clip(lower=0)
        h1 = recent.mean(axis=1)
        h2 = recent.sum(axis=1) / float(rev.reindex(hist).sum()) * float(rev[m])
        ratio, unit = B.item_ratio(L, origin)
        theory = B.theory_g(m).reindex(L.counts.index).fillna(0.0)
        has = (theory > 0) & unit.notna()
        t = (theory * ratio / unit).where(has, h2)
        actual = cons[m].clip(lower=0)
        active = ((L.counts[hist] > 0) | (L.receipts[hist] > 0)).any(axis=1)
        idx = actual.index[active & actual.notna()]
        w = price.reindex(idx).fillna(price.median())
        for name, pred in (("H1 최근 3개월 평균(매출 모름)", h1), ("H2 습관 × 그 달 실제 매출", h2), ("T  BOM × 그 달 실제 판매", t), ("BL 평균(H2, T)", (t + h2) / 2)):
            p, a = pred.reindex(idx).fillna(0), actual.reindex(idx)
            rows.append({"월": m, "방법": name, "소비WAPE": float(((p - a).abs() * w).sum() / (a * w).sum())})
    r = pd.DataFrame(rows)
    print(f"{FIRST} ~ {LAST} ({r['월'].nunique()}개월), 한 달 사용량 오차(금액 가중, 달별 평균)")
    for name, v in r.groupby("방법")["소비WAPE"].mean().items():
        print(f"  {name:28s} {v:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
