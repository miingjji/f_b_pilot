"""BOM 시험 ③ 월말 재고: 매출·BOM 으로 재고를 추적하면 기존 재고 시뮬레이션보다 월말 재고를 잘 맞히는가.

    cd fb_agent && FB_MASTER=real python experiments/bom_stock_tracking.py

각 달 m 에 대해 전월 말 실사 재고에서 출발한다.
  · 기존 시뮬레이션 = inventory_sim 이 전월 말에서 1개월 앞을 예측한 월말 재고 (매출·입고 모두 예측)
  · 출발 재고 그대로 = 전월 말 실사
  · 추적 = 전월 말 실사 + 그 달 실제 입고 − 사용량 (사용량 예측은 bom_monthly_usage.py 의 H1, H2, T, 평균)
대상: 2026-05 ~ 2026-09, 구매·입고 리스트의 그 달 입고가 수불부 입고내역과 5% 이내로 같고 시뮬레이션 대상인 품목(달마다 약 70~90개).
  구매·입고 리스트에는 CK(반제품) 등이 없어 이렇게 제한해야 입고를 믿을 수 있다.
오차 = Σ|예측 − 실제 월말 재고| × 단가 ÷ Σ|실제 월말 재고| × 단가 (재고 규모 대비), 달별 값의 평균.
기대 결과: 기존 시뮬레이션 26.1%, 출발 재고 그대로 34.9%, 추적 H1 66.7% / H2 52.2% / BOM 63.0% / 평균 46.9%.
월말 재고는 한 달 사용량의 약 38% 라 사용량 오차가 재고에서 약 3배로 커진다. 일 단위 재고는 정답 자료가 없어 검증하지 못했다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import bom_rate as B
import inventory_sim as I
import reorder_engine as RE

DATA = Path(__file__).resolve().parent.parent / "data" / "cleaned"
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


def main() -> int:
    L, book = I.load_ledger(), RE.load_book()
    price = L.meta["단가"]
    receipts = pd.read_csv(DATA / "2026" / "입고_정제.csv", encoding="utf-8-sig", dtype={"품목코드_RMS": str})
    receipts["월"] = receipts["입고일자"].str[:7]
    daily = pd.read_csv(DATA / "매출" / "일자별.csv", encoding="utf-8-sig")
    rev = daily.groupby(daily["날짜"].str[:7])["순매출"].sum()
    listed = lambda m: receipts[receipts["월"] == m].groupby("품목코드_RMS")["입고수량"].sum().astype(float).reindex(L.counts.index).fillna(0.0)
    rows = []
    for m in MONTHS:
        origin = I.add_month(m, -1)
        hist = L.months[: L.months.index(origin) + 1][-3:]
        mine, ledger = listed(m), L.receipts[m]
        trusted = ((mine - ledger).abs() <= 0.05 * ledger.abs() + 1e-6) & (ledger > 0)          # 그 달 입고를 리스트로 믿을 수 있는 품목
        f, res, _ = I.run_origin(L, origin, 1, I.Params(), None, book)
        sim_close = I.month_table(f, res, origin, 1).set_index("key")["예상월말재고"]
        close = L.counts[m]
        idx = pd.Index(sorted(k for k in trusted[trusted].index if k in set(res.sim_keys) and pd.notna(close.get(k))))
        ratio, unit = B.item_ratio(L, origin)
        theory = B.theory_g(m).reindex(L.counts.index).fillna(0.0)
        recent = L.consumption[hist].clip(lower=0)
        h1 = recent.mean(axis=1)
        h2 = recent.sum(axis=1) / float(rev.reindex(hist).sum()) * float(rev[m])
        t = (theory * ratio / unit).where((theory > 0) & unit.notna(), h2)
        w = price.reindex(idx).fillna(price.median())
        wape = lambda pred: float(((pred.reindex(idx) - close.reindex(idx)).abs() * w).sum() / (close.reindex(idx).abs() * w).sum())
        start = L.counts[origin]
        for name, pred in (("기존 시뮬레이션", sim_close), ("출발 재고 그대로", start), ("추적 H1 매출 모름", start + mine - h1), ("추적 H2 습관 × 매출", start + mine - h2),
                           ("추적 BOM", start + mine - t), ("추적 평균(H2, BOM)", start + mine - (t + h2) / 2)):
            rows.append({"월": m, "방법": name, "품목": len(idx), "오차": wape(pred)})
    r = pd.DataFrame(rows)
    print(f"{MONTHS[0]} ~ {MONTHS[-1]}, 월말 재고 오차(재고 규모 대비, 달별 평균), 품목 {r['품목'].min()}~{r['품목'].max()}개")
    for name, v in r.groupby("방법", sort=False)["오차"].mean().items():
        print(f"  {name:20s} {v:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
