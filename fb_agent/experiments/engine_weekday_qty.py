"""발주 수량 기준: '같은 요일 최근 3회 중앙값'이 이전 방식보다 실제 발주량을 더 잘 맞히는가.

    cd fb_agent
    FB_MASTER=real python experiments/engine_weekday_qty.py                       # 2025-01 ~ 2026-10-29, 약 10분
    FB_MASTER=real python experiments/engine_weekday_qty.py --start 2024-04-01    # README 의 2024-04~2026-10 값, 약 15분

현재 엔진으로 영업일마다 추천을 다시 만들고(reorder_engine.replay) 실제 발주한 건의 수량을 네 방식과 견준다.
  · 이전 엔진      = 직전 4회 주문량 중앙값 × 매출 규모비^β  (같은 요일 기준으로 바꾸기 전 공식)
  · 직전 4회       = 직전 4회 주문량 중앙값
  · 같은 요일(현재) = 오늘과 같은 요일의 최근 3회 중앙값 (2회 미만이면 직전 4회)
  · 같은 요일 × 규모비 = 위 값에 규모비^β 를 곱한 것 (곱하면 오히려 나빠지는지 확인)
오차(WAPE) = Σ|실제 수량 − 추천 수량| ÷ Σ실제 수량 (엔진 평가와 같은 수량 기준). 모든 방식은 그 발주일 이전 기록만 쓴다.
기대 결과: 2026-01~09(공식 검증 --eval 과 같은 5,271건) 이전 엔진 31.1% / 직전 4회 32.3% / 현재 26.0% / 같은 요일 × 규모비 31.8%.
  2025-01 이후(12,572건) 이전 엔진 32.2% → 현재 26.5%, 같은 요일 × 규모비 33.1%. 2025-01 이후 22개월 모두 개선(중앙값 5.2%p, 최소 1.1%p, 최대 12.1%p).
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import reorder_engine as RE


def rounded(x: pd.Series, unit: pd.Series) -> pd.Series:
    """엔진과 같은 반올림: kg 는 0.1, 그 밖은 1 단위 (최소 한 단위)."""
    step = np.where(unit.isin(["킬로그램", "kg"]), 0.1, 1.0)
    return pd.Series(np.maximum(step, np.round(x / step) * step), index=x.index)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-10-29")
    a = ap.parse_args()
    e = RE.Engine()
    R = RE.replay(e, date.fromisoformat(a.start), date.fromisoformat(a.end))
    reg = R[R["상태"].isin(["발주", "보류"])]
    h = reg[reg["실제발주"]].dropna(subset=["실제수량"]).copy()
    h["날짜"] = pd.to_datetime(h["날짜"])
    scale = h["규모비"].astype(float).fillna(1.0)
    beta = np.where(scale < 1, e.beta_down, e.beta_up)
    h["이전 엔진"] = rounded(h["직전4회수량"] * scale ** beta, h["단위"])
    h["직전 4회"] = rounded(h["직전4회수량"], h["단위"])
    h["같은 요일(현재)"] = h["권장수량"]
    h["같은 요일 × 규모비"] = rounded(h["기준수량"] * scale ** beta, h["단위"])
    methods = ["이전 엔진", "직전 4회", "같은 요일(현재)", "같은 요일 × 규모비"]
    wape = lambda d, c: float((d["실제수량"] - d[c]).abs().sum() / d["실제수량"].sum())

    def show(label: str, d: pd.DataFrame) -> None:
        print(f"{label}: 실제 발주 {len(d):,}건 | " + " | ".join(f"{c} {wape(d, c):.1%}" for c in methods))

    show(f"{a.start} ~ {a.end}", h)
    sub = h[(h["날짜"] >= "2026-01-01") & (h["날짜"] <= "2026-09-30")]
    if len(sub):
        show("2026-01-01 ~ 2026-09-30 (공식 검증 구간)", sub)
    month = h.groupby(h["날짜"].dt.to_period("M").astype(str)).apply(lambda d: wape(d, "이전 엔진") - wape(d, "같은 요일(현재)"))
    month = month[month.index >= "2025-01"]
    print(f"월별 개선 폭(이전 엔진 − 현재), 2025-01 이후 {len(month)}개월: 개선된 달 {(month > 0).sum()}개월, 중앙값 {month.median() * 100:.1f}%p, 최소 {month.min() * 100:.1f}%p, 최대 {month.max() * 100:.1f}%p")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
