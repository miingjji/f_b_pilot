"""화면 공통 헬퍼."""
from datetime import date, timedelta

import streamlit as st

from state import get_store, get_today


def sample_notice(what: str = "POS"):
    st.caption(f":material/science: 샘플 데이터입니다 — {what} 연동 전 화면 구성용이며, "
               f"'{get_store()}' 기준으로 값이 달라집니다.")


def won(n) -> str:
    return f"{int(n):,}원"


def won_short(n) -> str:
    """카드용 축약 표기: 430.9만원 / 1.2억원."""
    n = float(n)
    if abs(n) >= 1e8:
        return f"{n / 1e8:,.1f}억원"
    if abs(n) >= 1e4:
        return f"{n / 1e4:,.1f}만원"
    return f"{n:,.0f}원"


def kpis(items):
    """items = [(라벨, 값, 보조문구 또는 None), ...] 를 카드 한 줄로."""
    with st.container(horizontal=True):
        for label, value, delta in items:
            with st.container(border=True):
                st.metric(label, value, delta, delta_color="off" if delta is None else "normal")


def pct_delta(now: float, before: float) -> str:
    if not before:
        return "—"
    return f"{(now - before) / before * 100:+.1f}%"


def date_range(label: str, days: int, key: str) -> tuple[date, date]:
    """기간 선택. 선택 도중(시작일만)에는 시작=종료로 처리."""
    end = get_today()
    value = st.date_input(label, value=(end - timedelta(days=days - 1), end), key=key, max_value=end)
    if isinstance(value, (tuple, list)):
        if len(value) == 2:
            return value[0], value[1]
        if len(value) == 1:
            return value[0], value[0]
    return value, value


def num_cols(*names) -> dict:
    """표의 숫자 열에 천 단위 구분을 적용하는 column_config."""
    return {n: st.column_config.NumberColumn(format="localized") for n in names}


def iso(df, col: str = "date"):
    """차트 x축 날짜를 영어 요일 표기 대신 YYYY-MM-DD 문자열로."""
    out = df.copy()
    out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out
