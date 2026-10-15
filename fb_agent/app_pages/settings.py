from datetime import date

import pandas as pd
import streamlit as st

from data import SUPPLIERS
from models import WEEKDAY_KR

ss = st.session_state
DOW = "일월화수목금토"


def _add_closed():
    d = ss.set_new_closed
    if d not in ss.cfg_closed_dates:
        ss.cfg_closed_dates = sorted([*ss.cfg_closed_dates, d])


def _fmt(d: date) -> str:
    return f"{d:%Y-%m-%d} ({DOW[(d.weekday() + 1) % 7]})"


st.subheader("매장 설정")
with st.container(border=True):
    ss.cfg_closed_wd = st.multiselect(
        "정기 휴무 요일", range(7), default=ss.cfg_closed_wd, format_func=lambda d: WEEKDAY_KR[d] + "요일")

    st.markdown("**임시 휴무일** (공휴일·임시 휴무)")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.date_input("날짜 선택", value=date.today(), key="set_new_closed")
        st.button("추가", icon=":material/add:", on_click=_add_closed)
    ss.cfg_closed_dates = st.multiselect(
        "등록된 임시 휴무일 (선택 해제하면 삭제)", options=sorted(ss.cfg_closed_dates),
        default=sorted(ss.cfg_closed_dates), format_func=_fmt)

    picked = st.date_input("기준일 (시뮬레이션용)", value=ss.cfg_today or date.today(),
                           help="기본값은 오늘입니다. 다른 날짜로 바꾸면 발주·일정 계산의 기준일이 바뀝니다.")
    ss.cfg_today = None if picked == date.today() else picked

st.subheader("화면")
with st.container(border=True):
    labels = {"auto": "자동 (창이 넓으면 고정, 좁으면 서랍)", "dock": "항상 우측에 고정", "drawer": "항상 서랍으로 열기"}
    ss.cfg_agent_mode = st.radio("F&B Agent 패널 방식", list(labels), index=list(labels).index(ss.cfg_agent_mode),
                                 format_func=labels.get,
                                 help="고정하면 달력 칸이 좁아져요. 서랍은 버튼을 눌렀을 때만 우측에서 열립니다.")

st.subheader("거래처")
st.dataframe(
    pd.DataFrame([{"거래처": s.name, "발주 요일": s.order_days_label, "리드타임": f"D+{s.lead_time_days}"}
                  for s in SUPPLIERS.values()]),
    hide_index=True, width="stretch", alt="거래처별 발주 요일과 리드타임")
