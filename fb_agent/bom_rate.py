"""BOM 으로 구한 품목별 소비 속도 (Streamlit 비의존).

inventory_sim 의 '매출 1원당 소비량' 을 최근 달의 실제 소비 대신 이렇게 구한다:
    이론 사용량(g) = Σ 메뉴 판매 수량 × 표준 bom(품목, 메뉴)      — 달마다 그 달의 bom 과 영수증 판매량(메뉴_BOM_변환표)
    소비 속도 = (최근 k_mix 개월 이론 사용량 ÷ 그 달들의 매출) × 보정비율 ÷ 환산단위
    보정비율 = 최근 k_ratio 개월 (실제 소비 ÷ 이론 사용량). 품목의 이론 합이 작으면 전체 비율 쪽으로 당긴다.
BOM 에 없는 품목은 NaN (호출하는 쪽이 습관 방식으로 대신한다). origin 까지의 자료만 쓴다.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data" / "cleaned"
LEDGER = DATA / "수불부"
TABLE = DATA / "매출" / "메뉴_BOM_변환표.csv"


@lru_cache(maxsize=None)
def _menu_qty() -> dict:
    """{월: Series(BOM 메뉴 -> 판매 수량)} — 영수증 기준."""
    t = pd.read_csv(TABLE, encoding="utf-8-sig")
    t = t[t["BOM상품명"].notna()]
    return {m: g.groupby("BOM상품명")["수량"].sum() for m, g in t.groupby("월")}


@lru_cache(maxsize=None)
def theory_g(month: str) -> pd.Series:
    """그 달 BOM × 판매량 = 품목코드_RMS 별 이론 사용량(g). 자료가 없으면 빈 Series."""
    p = LEDGER / month[:4] / month / "표준BOM_정제.csv"
    q = _menu_qty().get(month)
    if not p.exists() or q is None:
        return pd.Series(dtype=float)
    b = pd.read_csv(p, encoding="utf-8-sig", dtype={"품목코드_RMS": str})
    b["g"] = b["사용량_g"] * b["메뉴"].map(q).fillna(0.0)
    return b.groupby("품목코드_RMS")["g"].sum()


@lru_cache(maxsize=None)
def _unit_g_month(month: str) -> pd.Series:
    """{품목 키: 환산단위(수량 1당 g)} 한 달치. 키 = RMS 코드, 없으면 매장 코드(inventory_sim 과 같다)."""
    c = pd.read_csv(LEDGER / month[:4] / month / "실사재고_정제.csv", dtype={"품목코드_RMS": str, "품목코드_매장": str})
    key = c["품목코드_RMS"].where(c["품목코드_RMS"] != "없음", c["품목코드_매장"])
    u = pd.Series(pd.to_numeric(c["환산단위"], errors="coerce").values, index=key.values)
    return u[u > 0].groupby(level=0).last()


def unit_g(months: list) -> pd.Series:
    """주어진 달들 중 가장 최근 값."""
    out = pd.Series(dtype=float)
    for m in months:
        out = _unit_g_month(m).combine_first(out) if out.empty else _unit_g_month(m).combine_first(out)
    return out


def item_ratio(L, origin: str, k_ratio: int = 6, shrink_g: float = 5e4):
    """(보정비율, 환산단위) — 품목 키별. 보정비율 = 최근 k_ratio 개월 (실제 소비 ÷ 이론 사용량), 이론 합이 작으면 전체 비율 쪽으로 당긴다."""
    ms = L.months[: L.months.index(origin) + 1]
    rat = [m for m in ms[-k_ratio:] if m in L.consumption.columns]
    unit = unit_g(ms[-12:]).reindex(L.counts.index)
    th = pd.concat([theory_g(m) for m in rat], axis=1).fillna(0).sum(axis=1).reindex(L.counts.index).fillna(0.0)
    act_g = L.consumption[rat].clip(lower=0).sum(axis=1) * unit
    inb = (th > 0) & act_g.notna()
    g_all = float(act_g[inb].sum() / th[inb].sum()) if inb.any() else 1.0
    return (act_g.fillna(0) + shrink_g * g_all) / (th + shrink_g), unit


def bom_rate(L, origin: str, revenue: pd.Series, k_mix: int = 3, k_ratio: int = 6, shrink_g: float = 5e4) -> pd.Series:
    """품목 키별 소비 속도(수량/원). L = inventory_sim.Ledger, revenue = 월별 매출(origin 까지)."""
    ms = L.months[: L.months.index(origin) + 1]
    mix = [m for m in ms[-k_mix:] if m in revenue.index]
    ratio, unit = item_ratio(L, origin, k_ratio, shrink_g)
    th_mix = pd.concat([theory_g(m) for m in mix], axis=1).fillna(0).sum(axis=1) if mix else pd.Series(dtype=float)
    per_won = th_mix.reindex(L.counts.index).fillna(0.0) / float(revenue.reindex(mix).sum())
    rate = per_won * ratio / unit
    return rate.where((per_won > 0) & unit.notna())
