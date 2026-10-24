"""화면용 시뮬레이션 재고 (Streamlit 비의존).

동결해 둔 재고 예측(`inventory_sim.py --forecast`, data/forecast/<월>_출발/)에서 기준일 아침의 예상 재고를 꺼내 품목 마스터의 기본단위로 바꾼다.
실사재고를 더 올리지 않으므로 마지막 월말 실사 이후의 재고는 이 값으로 본다. 기준일이 출발일(월말 실사일)이 지난 뒤여야 쓴다.
"""
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from inventory_sim import FORECAST_DIR, month_end
from order_units import packs_for

CLEANED = Path(__file__).resolve().parent / "data" / "cleaned"


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


@lru_cache(maxsize=2)
def _requests(path: str, mtime: float) -> pd.DataFrame:
    t = pd.read_csv(path, dtype={"품목코드_RMS": str}, usecols=["청구일자", "납기일자", "입고일자", "품목코드_RMS", "규격", "발주단위", "발주수량", "입고단위", "입고수량"])
    for c in ("청구일자", "납기일자", "입고일자"):
        d = pd.to_datetime(t[c], errors="coerce")
        t[c] = [x.date() if pd.notna(x) else None for x in d]            # '미입고' 는 None
    return t


def actual_flows(items_by_code: dict, origin: date, asof: date, cleaned: Path | None = None, placed_by: date | None = None) -> dict | None:
    """구매청구에 실제로 기록된 입고 {arrived: {품목명: origin 다음 날~asof 에 실제 도착한 양}, transit: {품목명: asof 다음 날 아침 이미 발주해 오는 중인 양 (placed_by 일까지 청구한 것, 기본 asof)},
    last_request: 구매청구 자료의 마지막 청구일, last_receipt: 마지막 입고일, po_items: 구매청구 이력이 있는 품목명 집합} (기본단위). 구매청구 정제본이 없으면 None.
    입고는 입고수량(입고단위), 오는 중은 발주수량(발주단위)을 앱 마스터의 PK 로 바꿔 쓴다 (order_units.packs_for)."""
    path = (cleaned or CLEANED) / "2026" / "구매청구_정제.csv"
    if not path.exists():
        return None
    r = _requests(str(path), path.stat().st_mtime)
    day = asof + timedelta(days=1)
    placed_by = placed_by or asof
    arrived, transit = {}, {}

    def base(row, qty, unit):
        it = items_by_code.get(row.품목코드_RMS)
        if it is None or it.current_stock is None:
            return None, None
        pk, _ = packs_for(float(qty), unit, row.규격, it.pk_weight_g, it.box_pk, it.base_unit)
        return it.name, pk * it.pk_weight_g

    recv = [d if d is not None else date.min for d in r["입고일자"]]
    recent = r[[(d == date.min or d > origin) and c >= origin - timedelta(days=30) for d, c in zip(recv, r["청구일자"])]]
    for row in recent.itertuples():
        got = row.입고일자
        if got is not None and origin < got <= asof and row.입고수량 > 0:
            n, q = base(row, row.입고수량, row.입고단위)
            if n:
                arrived[n] = arrived.get(n, 0.0) + q
        arrival = got if got is not None else row.납기일자
        if row.청구일자 <= placed_by and arrival is not None and arrival >= day and row.발주수량 > 0:
            n, q = base(row, row.발주수량, row.발주단위)
            if n:
                transit[n] = transit.get(n, 0.0) + q
    po_codes = set(r["품목코드_RMS"])
    return {"arrived": arrived, "transit": transit, "last_request": max(d for d in r["청구일자"] if d is not None),
            "last_receipt": max(d for d in r["입고일자"] if d is not None), "po_items": {it.name for c, it in items_by_code.items() if c in po_codes}}


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
    m = _read(str(d / "월별_예측.csv"), (d / "월별_예측.csv").stat().st_mtime, "month")
    start = m[m["월"] == m["월"].iloc[0]].set_index("key")["출발재고"]
    if asof <= origin:
        s, clamped, asof = start, False, origin
    else:
        t = _read(str(d / "일별_예측.csv"), (d / "일별_예측.csv").stat().st_mtime, "daily")
        last = date.fromisoformat(t["일자"].max())
        clamped = asof > last
        asof = min(asof, last)
        s = start.copy()                                                           # 시뮬레이션하지 않은(휴면) 품목은 출발 재고 그대로, 나머지는 그날 값
        s.update(t[t["일자"] == asof.isoformat()].set_index("key")["예상재고"])
    return {k: float(q) for k, q in s.items() if pd.notna(q)}, {"origin": origin, "asof": asof, "clamped": clamped}


def _daily_dir(day: date, root: Path):
    cand = [(o, d) for o, d in _origins(root) if o < day and (d / "일별_예측.csv").exists()]
    return cand[-1] if cand else (None, None)


def sim_stock(day: date, items_by_code: dict, root: Path | None = None, cleaned: Path | None = None) -> tuple[dict, dict | None]:
    """({품목명: day 아침의 예상 재고(기본단위)}, 정보). 쓸 수 있는 예측이 없으면 ({}, None). 정보에 값을 준 품목 수 items 가 더해진다.

    구매청구에 출발일 이후 실제 입고나 오는 중인 주문이 있는 품목은 출발일 이후의 입고를 시뮬레이션 값 대신 실제 값으로 바꾼다:
    재고 = 시뮬레이션 재고 − 시뮬레이션 누적 입고 + 실제 누적 입고 (소비는 시뮬레이션 그대로). 실제 입고가 기록된 마지막 날까지만 바꾸고 그 뒤는 시뮬레이션.
    정보: actual_until(실제 입고를 반영한 마지막 날, 없으면 None), actual_items(반영한 품목 수)."""
    root = root or FORECAST_DIR
    raw, info = sim_stock_raw(day, root)
    if info is None:
        return {}, None
    out = {}
    for code, q in raw.items():
        it = items_by_code.get(code)
        if it is not None and it.current_stock is not None:                        # 마스터에서 재고를 모르는 품목(세지 않은 소모품)은 모르는 채로 둔다
            out[it.name] = q * it.pk_weight_g                                       # 수불부 규격 수량 -> 기본단위 (개수 품목은 PK당수량 1, 중량 품목은 환산 g)
    info |= {"actual_until": None, "actual_items": 0}
    flows = actual_flows(items_by_code, info["origin"], info["asof"], cleaned) if info["asof"] > info["origin"] else None
    if flows is not None:
        cut = min(info["asof"], flows["last_receipt"])
        if cut > info["origin"]:
            flows = actual_flows(items_by_code, info["origin"], cut, cleaned)
            _, d = _daily_dir(day, root)
            t = _read(str(d / "일별_예측.csv"), (d / "일별_예측.csv").stat().st_mtime, "daily")
            cum = t[t["일자"] <= cut.isoformat()].groupby("key")["예상입고"].sum()
            code_of = {it.name: c for c, it in items_by_code.items()}
            n = 0
            for name in flows["po_items"]:
                if name in out and (name in flows["arrived"] or name in flows["transit"]):       # 그 사이 입고·발주가 한 번도 없었던 품목은 실제 흐름이 없는 것이라 시뮬레이션을 그대로 둔다 (휴면 의심)
                    it = items_by_code[code_of[name]]
                    out[name] = max(0.0, out[name] - float(cum.get(code_of[name], 0.0)) * it.pk_weight_g + flows["arrived"].get(name, 0.0))
                    n += 1
            if n:
                info |= {"actual_until": cut, "actual_items": n}
    return out, info | {"items": len(out)}


def sim_inbound(day: date, items_by_code: dict, root: Path | None = None, cleaned: Path | None = None) -> dict:
    """{품목명: day 아침 이미 발주해 오는 중으로 볼 입고량(기본단위)}.
    구매청구 이력이 있는 품목은 구매청구에 실제로 기록된 오는 중인 주문(청구했고 아직 도착하지 않은 것)을 쓴다 — 구매청구가 전날까지 기록돼 있을 때만.
    그 밖의 품목(CK 등)은 오늘 발주분이 리드타임 뒤에야 도착하므로, day ~ day+리드타임−1 에 도착하는 시뮬레이션 예상 입고를 오는 중으로 본다.
    쓸 예측이 없거나 예측이 끝난 날짜이면 {}."""
    root = root or FORECAST_DIR
    origin, d = _daily_dir(day, root)
    if d is None:
        return {}
    t = _read(str(d / "일별_예측.csv"), (d / "일별_예측.csv").stat().st_mtime, "daily")
    if day > date.fromisoformat(t["일자"].max()):
        return {}
    flows = actual_flows(items_by_code, origin, day - timedelta(days=1), cleaned, placed_by=day)           # 오늘 이미 청구한 것도 오는 중으로 본다
    covered = flows is not None and flows["last_request"] >= day - timedelta(days=1)
    t = t[t["예상입고"] > 0]
    out = {}
    for code, g in t.groupby("key"):
        it = items_by_code.get(code)
        lead = None if it is None else it.lead_time_days
        if it is None or it.current_stock is None or lead is None or (covered and it.name in flows["po_items"]):
            continue
        a, b = day.isoformat(), (day + timedelta(days=lead - 1)).isoformat()
        q = float(g.loc[(g["일자"] >= a) & (g["일자"] <= b), "예상입고"].sum())
        if q > 0:
            out[it.name] = q * it.pk_weight_g
    if covered:
        out |= {n: q for n, q in flows["transit"].items() if q > 0}
    return out


@lru_cache(maxsize=4)
def _read_plan(path: str, mtime: float) -> pd.DataFrame:
    t = pd.read_csv(path, dtype={"품목코드": str})
    t["발주일"], t["입고예정일"] = pd.to_datetime(t["발주일"]).dt.date, pd.to_datetime(t["입고예정일"]).dt.date
    return t


def sim_order_plan(day: date, days: int = 14, root: Path | None = None) -> pd.DataFrame | None:
    """day 부터 days 일 동안의 발주 예정(시뮬레이션 예측, `inventory_sim.py --orders`). 쓸 발주일 예측이 없으면 None.
    day 이전에 출발한 가장 최근 예측을 쓴다."""
    root = root or FORECAST_DIR
    cand = [(o, d / "발주일_예측.csv") for o, d in _origins(root) if o < day and (d / "발주일_예측.csv").exists()]
    if not cand:
        return None
    path = cand[-1][1]
    t = _read_plan(str(path), path.stat().st_mtime)
    return t[(t["발주일"] >= day) & (t["발주일"] < day + timedelta(days=days))].reset_index(drop=True)
