"""화면 공통 헬퍼."""
import re
import zlib
from datetime import date, timedelta

import streamlit as st

import sales_data
import style
from state import get_store, get_today


def sales_anchor():
    """매출 화면의 기준일: 오늘, 단 데이터가 끝난 뒤라면 마지막 영업일."""
    return sales_data.anchor(get_today())


def sales_notice(what: str = "POS"):
    """매출 화면 안내: 실제 POS 데이터의 기간과 기준일."""
    a, b = sales_data.first_date(), sales_data.last_date()
    txt = f":material/database: 수원점 실제 {what} 데이터입니다 ({a:%Y-%m-%d}\\~{b:%Y-%m-%d})."
    if get_today() > b:
        txt += f" 데이터가 {b:%Y-%m-%d}까지라 이 날을 기준일로 보여 줍니다."
    st.caption(txt)


def no_data(what: str = "표시할 데이터가 없어요"):
    """실제 데이터가 없을 때 안내 (가상 값으로 채우지 않는다)."""
    st.info(f"{what}", icon=":material/database_off:")


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
        for i, (label, value, delta) in enumerate(items):
            with st.container(key=f"kpi-{i}-{zlib.crc32(label.encode()):x}"):          # style.py 의 KPI 카드 CSS 대상
                st.html(style.kpi_chip(label, i))
                real = bool(delta) and re.match(r"^[+\-−]\d", delta) is not None          # +3.2% 같은 증감만 화살표·색을 쓰고, '영업일 28일' 같은 보조 문구는 그냥 글자로
                st.metric(label, value, delta, delta_color="normal" if real else "off", delta_arrow="auto" if real else "off")


def pct_delta(now: float, before: float) -> str:
    if not before:
        return "—"
    return f"{(now - before) / before * 100:+.1f}%"


def date_range(label: str, days: int, key: str) -> tuple[date, date]:
    """기간 선택. 선택 도중(시작일만)에는 시작=종료로 처리."""
    end = sales_anchor()
    with st.container(key="filterbar"):                     # 필터는 화면 상단의 카드형 바에 둔다
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
