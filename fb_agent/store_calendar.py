"""휴점 캘린더 (Streamlit 비의존). 입점 백화점이 쉬는 날을 '확정'과 '미확정'으로 나눠 준다.

확정 휴점
  · 고정: 1월 1일, 설날 전날·당일, 추석 전날·당일
  · 실적: 일자별 매출에 '무매출일'로 찍힌 날 (정산레포트에서 매출 0 = 백화점 휴무)
  · 입력: data/calendar/휴점일_입력.csv 에 적은 날 (백화점 공지를 받으면 여기에 추가)
미확정: 월요일. 매달 한 번 월요일에 쉬는 때가 많지만 몇째 주인지 정해져 있지 않아, 위 셋에 없으면 '미확정'이다.
영업일 매출 예측은 '영업한다'는 가정 아래의 값이고, 미확정 월요일은 휴점 확률(monday_closure_rate)을 함께 알려 준다.
공휴일은 data/calendar/공휴일.csv (2027년은 '추정' 표시, 확정되면 고쳐 쓴다).
"""
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from models import StoreCalendar

DATA = Path(__file__).resolve().parent / "data"
CAL = DATA / "calendar"
LUNAR = {   # 연도: (설날 당일, 추석 당일)
    2025: (date(2025, 1, 29), date(2025, 10, 6)), 2026: (date(2026, 2, 17), date(2026, 9, 25)),
    2027: (date(2027, 2, 7), date(2027, 9, 15)), 2028: (date(2028, 1, 27), date(2028, 10, 3)),
    2029: (date(2029, 2, 13), date(2029, 9, 22)), 2030: (date(2030, 2, 3), date(2030, 9, 12)),
}


@lru_cache(maxsize=1)
def public_holidays() -> dict:
    t = pd.read_csv(CAL / "공휴일.csv", parse_dates=["날짜"])
    return {r.날짜.date(): r.이름 for r in t.itertuples()}


def fixed_closures(year: int) -> dict:
    out = {date(year, 1, 1): "신정"}
    if year in LUNAR:
        seol, chuseok = LUNAR[year]
        out |= {seol - timedelta(days=1): "설날 전날", seol: "설날", chuseok - timedelta(days=1): "추석 전날", chuseok: "추석"}
    return out


@lru_cache(maxsize=1)
def observed_closures() -> dict:
    """일자별 매출 정제 파일의 무매출일. 고정 휴점이 아니면 '월요일 휴점'(월요일) 또는 '기타 무매출'로 이름 붙인다."""
    out = {}
    for f in sorted((DATA / "cleaned").glob("20*/매출일자별_정제.csv")):
        t = pd.read_csv(f)
        for s in t.loc[t["영업여부"] == "무매출일", "매출일자"]:
            d = date.fromisoformat(s)
            out[d] = fixed_closures(d.year).get(d) or ("월요일 휴점" if d.weekday() == 0 else "기타 무매출")
    return out


def entered_closures() -> dict:
    p = CAL / "휴점일_입력.csv"
    t = pd.read_csv(p) if p.exists() else pd.DataFrame(columns=["날짜", "사유"])
    return {date.fromisoformat(str(r.날짜)): str(r.사유) for r in t.itertuples()}


@lru_cache(maxsize=4)
def _closures(entered_mtime: float, year: int) -> dict:
    years = {d.year for d in observed_closures()} | {d.year for d in public_holidays()} | {year, year + 1}
    out = {}
    for y in sorted(years):
        out |= fixed_closures(y)
    return out | observed_closures() | entered_closures()


def closures() -> dict:
    """확정 휴점일 {날짜: 사유}. 고정(해당 연도) + 실적 + 입력. 입력 파일이 바뀌면 다시 만든다 (읽기 전용으로 쓸 것)."""
    p = CAL / "휴점일_입력.csv"
    return _closures(p.stat().st_mtime if p.exists() else 0.0, date.today().year)


def status(d: date) -> tuple[str, str]:
    """('휴점'|'영업'|'미확정', 사유). 미확정 = 월요일인데 확정 휴점이 아님."""
    c = closures()
    if d in c:
        return "휴점", c[d]
    return ("미확정", "월요일 (휴점 여부 미확정)") if d.weekday() == 0 else ("영업", "")


def is_closed(d: date) -> bool:
    return status(d)[0] == "휴점"


@lru_cache(maxsize=1)
def monday_closure_rate() -> float:
    """관측 기간의 평범한 월요일(공휴일·명절 아님) 중 휴점이었던 비율."""
    days = []
    for f in sorted((DATA / "cleaned").glob("20*/매출일자별_정제.csv")):
        t = pd.read_csv(f)
        days += [(date.fromisoformat(s), z == "무매출일") for s, z in zip(t["매출일자"], t["영업여부"])]
    plain = [(d, z) for d, z in days if d.weekday() == 0 and d not in public_holidays() and d not in fixed_closures(d.year)]
    return sum(z for _d, z in plain) / len(plain) if plain else 0.0


def store_calendar(start: date, end: date) -> StoreCalendar:
    """발주 계산(reorder.py)에 넘기는 StoreCalendar: [start, end] 의 확정 휴점일만 임시 휴무로 넣는다."""
    return StoreCalendar(closed_dates=frozenset(d for d in closures() if start <= d <= end))
