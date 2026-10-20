"""일 매출(순매출) 예측 v1 (Streamlit 비의존).  실행:  python sales_forecast.py   (백테스트 결과 출력)

예측 = 같은 일유형 최근 k일(영업일) 중앙값 × 전년동기 계절 보정
  · 일유형: 요일(월~일). 평일 공휴일은 일요일형으로 본다 (평일 공휴일 오차 71% → 13%).
  · 계절 보정: 작년 같은 시기 수준 ÷ 작년 '최근 4주' 수준. 1에서 멀어질수록 의심스러워 [0.75, 1.33]로 자르고 season_weight 제곱으로 줄인다.
  · 징검다리 평일(양옆이 주말·공휴일·확정 휴점인 평일)과 연휴 직전 평일은 일요일형이 아니라 '과거 실제 배율'을 곱한다 (adjust).
    배율은 예측하는 날 이전의 같은 종류 날들이 평소(직전 같은 요일 4일 중앙값)보다 얼마나 높았는지의 중앙값이다. 3번 미만이면 1.0.
    이런 날은 평소 기준(같은 요일 최근 4일)을 만들 때 뺀다 (그날이 다음 주 기준을 부풀리지 않게).
  · 영업한다는 가정의 값이다. 휴점은 store_calendar 가 알려 주고, 휴점일은 예측하지 않는다.
  · 범위(P10~P90)는 과거 예측 오차 비율의 분위수를 일유형 묶음(평일·토·일/공휴일)별로 구해 곱한다.
"""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import store_calendar as sc

DATA = Path(__file__).resolve().parent / "data"
GROUPS = {0: "평일", 1: "평일", 2: "평일", 3: "평일", 4: "평일", 5: "토", 6: "일·공휴일"}


def day_type(d: date) -> int:
    w = d.weekday()
    return 6 if (w < 5 and d in sc.public_holidays()) else w


def load_history() -> pd.Series:
    """정제된 일자별 순매출 (영업일만, index=date). 2025년 이후 모든 연도 파일을 합친다."""
    parts = []
    for f in sorted((DATA / "cleaned").glob("20*/매출일자별_정제.csv")):
        t = pd.read_csv(f)
        parts.append(t[t["영업여부"] == "영업"].set_index("매출일자")["순매출"])
    s = pd.concat(parts)
    s.index = [date.fromisoformat(x) for x in s.index]
    return s.sort_index().astype(float)


def _level(known: pd.Series, a: date, b: date, typical: dict) -> float | None:
    """[a, b] 영업일의 '일유형 평소 대비' 평균 (1이면 평소 수준)."""
    w = known[(known.index >= a) & (known.index <= b)]
    if len(w) < 8:
        return None
    return float(np.mean([v / typical[day_type(d)] for d, v in w.items() if day_type(d) in typical]))


def is_off(d: date) -> bool:
    """쉬는 날: 주말, 공휴일, 확정 휴점. (미확정 월요일은 쉰다고 보지 않는다)"""
    return d.weekday() >= 5 or d in sc.public_holidays() or d in sc.closures()


def is_bridge(d: date) -> bool:
    """징검다리 평일: 쉬는 날이 아닌 평일인데 전날과 다음날이 모두 쉬는 날 (예: 어린이날 화요일 앞의 월요일)."""
    return not is_off(d) and is_off(d - timedelta(days=1)) and is_off(d + timedelta(days=1))


def is_eve(d: date) -> bool:
    """공휴일·확정 휴점 전날인 평일 (연휴 앞두고 매출이 몰린다)."""
    nxt = d + timedelta(days=1)
    return d.weekday() < 5 and d not in sc.public_holidays() and d not in sc.closures() and (nxt in sc.public_holidays() or nxt in sc.closures())


KINDS = {"bridge": is_bridge, "eve": is_eve}
_RATIO_CACHE: dict = {}


def kind_ratios(history: pd.Series, kind: str) -> dict:
    """kind 에 해당하는 과거 날마다 (실제 ÷ 평소). 평소 = 그날 전까지 같은 일유형 최근 4일 중앙값 (그날 이후 데이터는 안 쓴다)."""
    key = (len(history), history.index[0], history.index[-1], round(float(history.sum()), 2), kind)      # 같은 내용이면 같은 결과
    if key not in _RATIO_CACHE:
        out = {}
        for d, v in history.items():
            if KINDS[kind](d):
                prior = history[history.index < d]
                same = prior[[day_type(x) == day_type(d) and not KINDS[kind](x) for x in prior.index]]
                if len(same) >= 2:
                    out[d] = v / float(same.tail(4).median())
        _RATIO_CACHE[key] = out
    return _RATIO_CACHE[key]


def learned_boost(history: pd.Series, cut: date, kind: str, min_n: int = 3, last: int = 8) -> float:
    """cut 까지 알려진 kind 날들의 배율 중앙값 (최근 last 개). 표본이 min_n 보다 적으면 1.0."""
    r = [v for d, v in sorted(kind_ratios(history, kind).items()) if d <= cut][-last:]
    return float(np.median(r)) if len(r) >= min_n else 1.0


def forecast(history: pd.Series, target: date, horizon: int = 1, k: int = 4, season_weight: float = 0.5, holiday_rule: bool = True, adjust: tuple = ("bridge", "eve")) -> float | None:
    """target 일의 순매출 예측. horizon 일 전까지의 history 만 쓴다 (horizon=1 이면 전날까지)."""
    cut = target - timedelta(days=horizon)
    known = history[history.index <= cut]
    typ = (lambda d: day_type(d)) if holiday_rule else (lambda d: d.weekday())
    same = known[[typ(d) == typ(target) and not any(KINDS[a](d) for a in adjust) for d in known.index]]     # 징검다리 날은 평소 기준에서 뺀다
    if len(same) < 2:
        return None
    base = float(same.tail(k).median())
    for a in adjust:
        if KINDS[a](target):
            base *= learned_boost(history, cut, a)
    if season_weight <= 0:
        return base
    typical = {t: float(known[[typ(d) == t for d in known.index]].median()) for t in set(typ(d) for d in known.index)}
    ly = timedelta(days=364)
    s_t = _level(known, target - ly - timedelta(days=14), target - ly + timedelta(days=14), typical)
    s_r = _level(known, cut - ly - timedelta(days=27), cut - ly, typical)
    if s_t is None or s_r is None or s_r <= 0:
        return base
    return base * float(np.clip(s_t / s_r, 0.75, 1.33)) ** season_weight


def backtest(history: pd.Series, start: date, end: date, **kw) -> pd.DataFrame:
    """[start, end] 의 영업일마다, 그날 이전 데이터만으로 예측해 실제와 비교한다."""
    rows = []
    for d, actual in history[(history.index >= start) & (history.index <= end)].items():
        p = forecast(history, d, **kw)
        if p is not None:
            rows.append({"date": d, "actual": actual, "pred": p, "group": GROUPS[day_type(d)]})
    return pd.DataFrame(rows)


def wape(bt: pd.DataFrame) -> float:
    return float((bt["actual"] - bt["pred"]).abs().sum() / bt["actual"].sum() * 100)


def fit_bands(bt: pd.DataFrame, lo=0.1, hi=0.9) -> dict:
    """일유형 묶음별 (실제/예측) 비율의 분위수 → {묶음: (P10 배율, P90 배율)}."""
    r = (bt["actual"] / bt["pred"]).groupby(bt["group"])
    return {g: (float(x.quantile(lo)), float(x.quantile(hi))) for g, x in r}


def predict_range(history: pd.Series, target: date, bands: dict, **kw) -> dict | None:
    p = forecast(history, target, **kw)
    if p is None:
        return None
    lo, hi = bands[GROUPS[day_type(target)]]
    return {"date": target, "p10": p * lo, "p50": p, "p90": p * hi}


def main() -> int:
    h = load_history()
    print(f"영업일 {len(h)}일 ({min(h.index)} ~ {max(h.index)})")
    s26, e26 = date(2026, 1, 1), date(2026, 9, 30)
    print("\n■ 2026-01~09 영업일 백테스트 (작년 데이터로 계절 보정 가능)  WAPE %, 괄호는 평일/토/일·공휴일")
    for name, kw in (("요일만 (공휴일 규칙 없음)", dict(holiday_rule=False, season_weight=0, adjust=())),
                     ("+ 공휴일=일요일형", dict(season_weight=0, adjust=())),
                     ("+ 전년동기 계절 보정 ×0.5", dict(season_weight=0.5, adjust=())),
                     ("+ 징검다리·연휴 직전 보정", dict(season_weight=0.5))):
        for hz in (1, 7):
            bt = backtest(h, s26, e26, horizon=hz, **kw)
            g = {k: round(wape(x), 1) for k, x in bt.groupby("group")}
            print(f"  {name:24s} {hz}일 전 예측: {wape(bt):5.1f}  ({g['평일']}/{g['토']}/{g['일·공휴일']})  n={len(bt)}")
    print("\n■ P10~P90 범위: 2025-04~12 오차로 범위를 만들고 2026 에 적용 (시간 순서대로 검증)")
    kw = dict(horizon=1, season_weight=0.5)
    bands = fit_bands(backtest(h, date(2025, 4, 1), date(2025, 12, 31), horizon=1, season_weight=0))
    bt = backtest(h, s26, e26, **kw)
    lo = bt["group"].map(lambda g: bands[g][0]); hi = bt["group"].map(lambda g: bands[g][1])
    inside = (bt["actual"] >= bt["pred"] * lo) & (bt["actual"] <= bt["pred"] * hi)
    print("  묶음별 배율(P10, P90):", {g: (round(a, 2), round(b, 2)) for g, (a, b) in bands.items()})
    print(f"  2026 실제가 범위 안: {inside.mean() * 100:.0f}% (목표 80%)  묶음별:", {g: f"{inside[bt['group'] == g].mean() * 100:.0f}%" for g in GROUPS.values() if g in set(bt['group'])})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
