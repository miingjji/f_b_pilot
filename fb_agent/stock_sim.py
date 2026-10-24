"""화면용 시뮬레이션 재고 (Streamlit 비의존).

동결해 둔 재고 예측(`inventory_sim.py --forecast`, data/forecast/<월>_출발/)에서 기준일 아침의 예상 재고를 꺼내 품목 마스터의 기본단위로 바꾼다.
실사재고를 더 올리지 않으므로 마지막 월말 실사 이후의 재고는 이 값으로 본다. 기준일이 출발일(월말 실사일)이 지난 뒤여야 쓴다.
"""
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from inventory_sim import FORECAST_DIR, month_end


@lru_cache(maxsize=8)
def _read(path: str, mtime: float, kind: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"key": str}, usecols=(["일자", "key", "예상재고", "예상입고"] if kind == "daily" else ["월", "key", "출발재고"]))


def _origins(root: Path) -> list[tuple[date, Path]]:
    out = []
    for d in root.glob("20??-??_출발"):
        try:
            out.append((month_end(d.name[:7]), d))
        except ValueError:
            continue
    return sorted(out)


def sim_stock_raw(day: date, root: Path | None = None) -> tuple[dict, dict | None]:
    """({품목코드: day 아침의 예상 재고(수불부 규격 수량)}, 정보). 쓸 수 있는 예측이 없으면 ({}, None).

    day 아침 재고 = 전날 말 재고. 전날이 출발일이면 출발일의 실사 재고. 예측이 끝난 뒤의 날짜는 마지막 날 값을 쓰고 정보에 clamped=True.
    정보: origin(출발일), asof(재고 기준일 = 전날), clamped.
    """
    root = root or FORECAST_DIR
    cand = [(o, d) for o, d in _origins(root) if o < day and (d / "일별_예측.csv").exists()]
    if not cand:
        return {}, None
    origin, d = cand[-1]
    asof = day - timedelta(days=1)
    if asof <= origin:
        m = _read(str(d / "월별_예측.csv"), (d / "월별_예측.csv").stat().st_mtime, "month")
        s, clamped, asof = m[m["월"] == m["월"].iloc[0]].set_index("key")["출발재고"], False, origin
    else:
        t = _read(str(d / "일별_예측.csv"), (d / "일별_예측.csv").stat().st_mtime, "daily")
        last = date.fromisoformat(t["일자"].max())
        clamped = asof > last
        asof = min(asof, last)
        s = t[t["일자"] == asof.isoformat()].set_index("key")["예상재고"]
    return {k: float(q) for k, q in s.items() if pd.notna(q)}, {"origin": origin, "asof": asof, "clamped": clamped}


def sim_stock(day: date, items_by_code: dict, root: Path | None = None) -> tuple[dict, dict | None]:
    """({품목명: day 아침의 예상 재고(기본단위)}, 정보). 쓸 수 있는 예측이 없으면 ({}, None). 정보에 값을 준 품목 수 items 가 더해진다."""
    raw, info = sim_stock_raw(day, root)
    if info is None:
        return {}, None
    out = {}
    for code, q in raw.items():
        it = items_by_code.get(code)
        if it is not None and it.current_stock is not None:                        # 마스터에서 재고를 모르는 품목(세지 않은 소모품)은 모르는 채로 둔다
            out[it.name] = q * it.pk_weight_g                                       # 수불부 규격 수량 -> 기본단위 (개수 품목은 PK당수량 1, 중량 품목은 환산 g)
    return out, info | {"items": len(out)}


def sim_inbound(day: date, items_by_code: dict, root: Path | None = None) -> dict:
    """{품목명: day 아침 이미 발주해 오는 중으로 볼 입고량(기본단위)}. 오늘 발주분은 리드타임 뒤에야 도착하므로, day ~ day+리드타임−1 에 도착하는
    시뮬레이션 예상 입고가 이미 오는 중인 입고다. 쓸 예측이 없거나 예측이 끝난 날짜이면 {}."""
    root = root or FORECAST_DIR
    cand = [(o, d) for o, d in _origins(root) if o < day and (d / "일별_예측.csv").exists()]
    if not cand:
        return {}
    d = cand[-1][1]
    t = _read(str(d / "일별_예측.csv"), (d / "일별_예측.csv").stat().st_mtime, "daily")
    if day > date.fromisoformat(t["일자"].max()):
        return {}
    t = t[t["예상입고"] > 0]
    out = {}
    for code, g in t.groupby("key"):
        it = items_by_code.get(code)
        lead = None if it is None else it.lead_time_days
        if it is None or it.current_stock is None or lead is None:
            continue
        a, b = day.isoformat(), (day + timedelta(days=lead - 1)).isoformat()
        q = float(g.loc[(g["일자"] >= a) & (g["일자"] <= b), "예상입고"].sum())
        if q > 0:
            out[it.name] = q * it.pk_weight_g
    return out
