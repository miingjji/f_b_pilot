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


CHART_COLORS = ["#1F3B5C", "#6E86A8", "#0B1F3A", "#A7B1BE", "#2B2F36", "#8E9CB0", "#3E5C84", "#C3CAD4"]


def axis_chart(kind: str, data, *, x: str | None = None, y=None, x_label: str | None = None, y_label: str | None = None, alt_text: str,
               stack: bool = True, year: str | bool = False, height: int = 300):
    """가로축 글자가 눕지 않는 차트 (bar·line·area). data 는 DataFrame/Series — x 열을 주거나, 없으면 인덱스가 가로축.
    가로축이 날짜면 'MM-DD' 로 짧게 쓰고, 연도는 차트 왼쪽 위에 따로 적는다 (year=True 면 날짜에서 계산, 문자열이면 그대로)."""
    import altair as alt
    import pandas as pd
    df = data.to_frame(name=data.name or "값") if isinstance(data, pd.Series) else data.copy()
    if x is None:
        df = df.rename_axis("가로축").reset_index()
        x = df.columns[0]
    ys = [y] if isinstance(y, str) else list(y) if y else [c for c in df.columns if c != x]
    long = df[[x, *ys]].melt(id_vars=x, var_name="구분", value_name="값")
    temporal = pd.api.types.is_datetime64_any_dtype(df[x])
    order = None if temporal else list(dict.fromkeys(long[x]))
    title = None
    if year and temporal:
        y1, y2 = df[x].min().year, df[x].max().year
        title = alt.TitleParams(f"{y1}년" if y1 == y2 else f"{y1}년 ~ {y2}년", anchor="start", fontSize=13, fontWeight=600, color="#2B2F36", offset=8)
    elif isinstance(year, str):
        title = alt.TitleParams(year, anchor="start", fontSize=13, fontWeight=600, color="#2B2F36", offset=8)
    axis = alt.Axis(labelAngle=0, labelOverlap=True, title=x_label, **({"format": "%m-%d"} if temporal else {}))
    enc_x = alt.X(f"{x}:T" if temporal else f"{x}:N", axis=axis, **({} if temporal else {"sort": order}))
    enc_y = alt.Y("값:Q", axis=alt.Axis(format=",.0f", title=y_label), **({"stack": None} if not stack and len(ys) > 1 and kind == "bar" else {}))
    multi = len(ys) > 1
    color = (alt.Color("구분:N", scale=alt.Scale(domain=ys, range=CHART_COLORS), legend=alt.Legend(orient="top", title=None, columns=6, labelLimit=140, symbolLimit=0))
             if multi else alt.value(CHART_COLORS[0]))
    tip = [alt.Tooltip(f"{x}:T" if temporal else f"{x}:N", title=x_label or "", **({"format": "%Y-%m-%d"} if temporal else {})),
           *([alt.Tooltip("구분:N", title="구분")] if multi else []), alt.Tooltip("값:Q", format=",.0f", title=y_label or "값")]
    base = alt.Chart(long, title=title) if title else alt.Chart(long)
    if kind == "bar":
        mark = base.mark_bar()
        if multi and not stack:
            enc = dict(x=enc_x, y=enc_y, color=color, xOffset=alt.XOffset("구분:N", sort=ys), tooltip=tip)
        else:
            enc = dict(x=enc_x, y=enc_y, color=color, tooltip=tip)
    elif kind == "area":
        mark, enc = base.mark_area(opacity=0.85), dict(x=enc_x, y=enc_y, color=color, tooltip=tip)
    else:
        mark, enc = base.mark_line(point=False, strokeWidth=2), dict(x=enc_x, y=enc_y, color=color, tooltip=tip)
    st.altair_chart(mark.encode(**enc).properties(height=height), width="stretch", alt=alt_text)
