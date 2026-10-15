"""F&B Agent 에 넘기는 현재 매장 컨텍스트."""
from datetime import timedelta

import streamlit as st

import sample_data as sd
from agent import AgentContext
from calendar_data import build_events
from state import get_calendar, get_recs, get_store, get_today


def build_context() -> AgentContext:
    ss = st.session_state
    today, cal, recs, store = get_today(), get_calendar(), get_recs(), get_store()
    now, last_week = sd.day_sales(store, today), sd.day_sales(store, today - timedelta(days=7))
    diff = (now["sales"] - last_week["sales"]) / last_week["sales"] * 100
    staffing = sd.staffing_by_hour(store, today)
    return AgentContext(
        today, recs, build_events(ss.events, recs, cal, today, today + timedelta(days=14)),
        store=store,
        sales_note=f"{store} 오늘 매출은 **{now['sales']:,}원**, 객수 {now['customers']:,}명(객단가 {now['ticket']:,}원)으로 "
                   f"지난주 같은 요일보다 {diff:+.1f}% 입니다. (샘플 데이터)",
        staff_today=sd.today_staff_count(store, today),
        shortage_hours=list(staffing[staffing["배치 인력"] < staffing["적정 인력"]]["시간"]),
    )
