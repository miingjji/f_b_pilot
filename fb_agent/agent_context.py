"""F&B Agent 에 넘기는 현재 매장 컨텍스트."""
from datetime import timedelta

import streamlit as st

import sales_data as sd
from agent import AgentContext
from calendar_data import build_events
from state import get_calendar, get_recs, get_store, get_today


def build_context() -> AgentContext:
    ss = st.session_state
    today, cal, recs, store = get_today(), get_calendar(), get_recs(), get_store()
    ref = sd.latest_day(today)
    now = sd.day_sales(ref) if ref else None
    last_week = sd.day_sales(ref - timedelta(days=7)) if ref else None
    if now is None:
        note = f"{store} 매출 데이터가 아직 없어요."
    else:
        note = (f"{store} {ref:%Y-%m-%d} 매출은 **{now['sales']:,}원**, 객수 {now['customers']:,}명(객단가 {now['ticket']:,}원)입니다. "
                + (f"지난주 같은 요일보다 {(now['sales'] - last_week['sales']) / last_week['sales'] * 100:+.1f}% 입니다. " if last_week else "")
                + "(실제 POS 데이터, 가장 최근 영업일 기준)")
    return AgentContext(today, recs, build_events(ss.events, recs, cal, today, today + timedelta(days=14)), store=store, sales_note=note,
                        staff_today=None, shortage_hours=[])           # 근태 데이터가 없어 근무 인원·인력 부족 시간은 알 수 없다
