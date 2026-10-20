"""품목의 발주단위(박스·팩·개·병·킬로그램)와 박스 안 낱개(병·캔) 표기 — 화면 어디서나 같은 기준으로 수량을 보여 준다.

앱은 수량을 PK 로 저장하지만 화면에는 품목의 실제 발주단위로 보여 준다. 청구 이력(2025~2026)의 발주단위가 우선이고,
없으면 품목명 끝 규격('…_375ml*12ea/box')에서 읽는다. 변환 규칙은 order_units 참고.
"""
from functools import lru_cache

import pandas as pd

import reorder_engine
from data import ITEMS
from order_units import UNIT_SHORT, Units, item_units, qty_text, stock_text


@lru_cache(maxsize=2)
def _load(stamp: tuple) -> dict:
    out = {}
    for name, *_ in stamp:
        d = pd.read_csv(name, encoding="utf-8-sig", dtype=str, usecols=["품목코드_RMS", "발주단위"]).dropna()
        out.update(d.groupby("품목코드_RMS")["발주단위"].agg(lambda x: x.value_counts().index[0]))
    return out


def history_units() -> dict:
    """품목코드 → 청구 이력의 발주단위. 이력 파일이 없으면 비어 있다. 파일이 바뀌면 다시 읽는다."""
    files = sorted(reorder_engine.DATA.glob("20*/구매청구_정제.csv"))
    return _load(tuple((str(f), f.stat().st_mtime) for f in files))


def units_of(it) -> Units:
    return item_units(it.name, it.supplier.name, it.base_unit, it.pk_weight_g, it.box_pk, history_units().get(it.code))


def unit_name(it) -> str:
    """수량 입력칸에 붙이는 발주단위 이름 (박스·팩·개·병·kg)."""
    u = units_of(it).unit
    return UNIT_SHORT.get(u, u)


def qty_of(it, packs: float) -> str:
    """PK 수량을 발주단위로: '2박스', 박스 안 낱개가 있으면 '24병 (2박스)'."""
    u = units_of(it)
    return qty_text(u, packs / u.per)


def qty_for(name: str, packs: float) -> str:
    """품목명으로 qty_of. 품목 마스터에 없으면 PK 그대로."""
    it = ITEMS.get(name)
    return qty_of(it, packs) if it else f"{packs:g}PK"


def stock_of(it, amount: float) -> str:
    """재고(기본단위 양)를 낱개가 있으면 병·캔 수로, 없으면 발주단위 수로."""
    return stock_text(units_of(it), amount, it.pk_weight_g)


def display_unit(it) -> tuple[str, float]:
    """(표시 단위 이름, PK → 표시 단위 환산 배수). 낱개가 있으면 병·캔, 없으면 발주단위."""
    u = units_of(it)
    return (u.each, u.count / u.per) if u.each else (UNIT_SHORT.get(u.unit, u.unit), 1 / u.per)
