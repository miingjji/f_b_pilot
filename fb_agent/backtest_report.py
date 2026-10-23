"""일 순매출 예측 기간별 백테스트 (24-01~26-09):  python backtest_report.py

기준선(최근 4주 같은 요일 평균) → 요일 중앙값 → 현재 v1(공휴일·계절·징검다리)을 같은 기간·같은 날로 비교한다.
기간: 2025 전체(작년=2024로 계절 보정), 2026-01~06, 2026-07~09(마지막에 한 번만 보는 보류 구간).
"""
from datetime import date

import numpy as np
import pandas as pd

import sales_forecast as sf

PERIODS = {"2025-01~06": (date(2025, 1, 1), date(2025, 6, 30)), "2025-07~12": (date(2025, 7, 1), date(2025, 12, 31)),
           "2026-01~06": (date(2026, 1, 1), date(2026, 6, 30)), "2026-07~09 (보류)": (date(2026, 7, 1), date(2026, 9, 30))}


def naive(h: pd.Series, target: date, horizon: int = 1) -> float | None:
    """같은 요일 최근 4번의 평균 (공휴일·계절 고려 없음)."""
    known = h[h.index <= target - pd.Timedelta(days=horizon)]
    same = known[[d.weekday() == target.weekday() for d in known.index]].tail(4)
    return float(same.mean()) if len(same) >= 2 else None


def run(h, fn, a, b):
    rows = [(d, v, fn(d)) for d, v in h[(h.index >= a) & (h.index <= b)].items()]
    r = pd.DataFrame([x for x in rows if x[2] is not None], columns=["date", "actual", "pred"])
    return r


def summarize(r):
    e = r["pred"] - r["actual"]
    return round(float(e.abs().sum() / r["actual"].sum() * 100), 1), round(float(e.sum() / r["actual"].sum() * 100), 1), len(r)


def main():
    h = sf.load_history()
    models = {"기준선: 같은 요일 4회 평균": lambda d: naive(h, d),
              "요일 중앙값(k=4)": lambda d: sf.forecast(h, d, holiday_rule=False, season_weight=0, adjust=()),
              "+공휴일=일요일형": lambda d: sf.forecast(h, d, season_weight=0, adjust=()),
              "v1 전체(계절·징검다리)": lambda d: sf.forecast(h, d)}
    out = []
    for name, fn in models.items():
        for p, (a, b) in PERIODS.items():
            w, bias, n = summarize(run(h, fn, a, b))
            out.append({"모델": name, "기간": p, "WAPE%": w, "편향%": bias, "n": n})
    t = pd.DataFrame(out)
    print(t.pivot(index="모델", columns="기간", values="WAPE%").reindex(models).to_string())
    print("\n편향(예측-실제)/실제 %:"); print(t.pivot(index="모델", columns="기간", values="편향%").reindex(models).to_string())
    return t


if __name__ == "__main__":
    main()
