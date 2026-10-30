"""BOM 시험 ② 발주 수량: 실제 판매량과 BOM 을 완벽히 안다고 해도 발주량을 맞힐 수 있는가.

    cd fb_agent && FB_MASTER=real python experiments/bom_order_qty.py

가정: 한 번의 발주량 = 그 발주가 도착한 날부터 다음 발주가 도착하기 전날까지 쓴 양.
  · 습관 오라클   = 최근 3개월 (소비 ÷ 매출) × 그 기간의 실제 매출
  · BOM 오라클    = 그 달 BOM 이론 사용량 × 품목별 보정비율 ÷ 환산단위, 일별 배분은 그날 매출 비율 (일별 메뉴 판매가 아니다)
  · 기준선        = 직전 4회 발주량의 중앙값 (엔진이 쓰던 평소 주문량)
대상: 2026-01~09 에 도착한 발주 중 BOM 이 있는 품목(약 88개)의 5,028건. 금액 가중과 수량 기준(엔진 평가와 같은 방식)을 함께 낸다.
기대 결과: 기준선 33.0% / 31.7%, 습관 오라클 60.2% / 65.0%, BOM 오라클 60.4% / 63.5% (금액 가중 / 수량 기준), 다음 발주까지 3일 이하 75.8%.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import bom_rate as B
import inventory_sim as I
import reorder_engine as RE

START, END = date(2026, 1, 1), date(2026, 9, 30)


def build_rows() -> pd.DataFrame:
    L, book = I.load_ledger(), RE.load_book()
    fac = I.po_factors(L, book, "2026-09")                       # 발주단위 → 수불부 단위
    price = L.meta["단가"]
    daily = book.daily
    rev_m = daily.groupby([f"{d:%Y-%m}" for d in daily.index]).sum()
    orders = book.orders[book.orders["품목코드_RMS"].isin(fac)]
    ratios = {}
    rows = []
    for key, g in orders.groupby("품목코드_RMS"):
        g = g.sort_values("도착").reset_index(drop=True)
        if len(g) < 6 or key not in L.counts.index:
            continue
        for i in range(4, len(g) - 1):
            arrive, nxt = g.at[i, "도착"], g.at[i + 1, "도착"]
            if not (START <= arrive <= END) or nxt > END or nxt <= arrive:
                continue
            q = g.at[i, "수량"] / fac[key]                       # 실제 발주량
            base = float(np.median([g.at[j, "수량"] for j in range(i - 4, i)])) / fac[key]
            days = [arrive + timedelta(days=x) for x in range((nxt - arrive).days)]
            month = f"{arrive:%Y-%m}"
            origin = I.add_month(month, -1)
            hist = [m for m in L.months if m <= origin][-3:]
            if len(hist) < 3 or origin not in L.months:
                continue
            habit = L.consumption.loc[key, hist].clip(lower=0).sum() / float(rev_m.reindex(hist).sum()) * sum(float(daily.get(d, 0.0)) for d in days)
            if origin not in ratios:
                ratios[origin] = B.item_ratio(L, origin)
            ratio, unit = ratios[origin]
            bom, theory = np.nan, 0.0
            for d in days:
                m = f"{d:%Y-%m}"
                if m not in rev_m.index:
                    theory = np.nan
                    break
                theory += B.theory_g(m).get(key, 0.0) * float(daily.get(d, 0.0)) / float(rev_m[m])
            if theory and theory > 0 and unit.get(key) and ratio.get(key):
                bom = theory * ratio[key] / unit[key]
            rows.append(dict(key=key, q=q, base=base, habit=habit, bom=bom, days=(nxt - arrive).days, w=price.get(key, np.nan)))
    return pd.DataFrame(rows)


def wape(col: str, d: pd.DataFrame, weighted: bool) -> float:
    w = d["w"] if weighted else 1.0
    return float(((d[col] - d["q"]).abs() * w).sum() / (d["q"] * w).sum())


def main() -> int:
    d = build_rows().dropna(subset=["bom"]).copy()
    d["w"] = d["w"].fillna(d["w"].median())
    print(f"발주 {len(d):,}건 / 품목 {d['key'].nunique()}개 (BOM 이 있는 품목, {START}~{END})")
    print(f"다음 발주까지 3일 이하인 발주: {(d['days'] <= 3).sum():,}건 = {(d['days'] <= 3).mean():.1%}")
    print(f"{'방법':26s} {'금액 가중':>9s} {'수량 기준':>9s}")
    for name, col in (("직전 4회 중앙값(기준선)", "base"), ("습관 × 실제 매출(오라클)", "habit"), ("BOM × 실제 판매(오라클)", "bom")):
        print(f"{name:26s} {wape(col, d, True):9.1%} {wape(col, d, False):9.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
