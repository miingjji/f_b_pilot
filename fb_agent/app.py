from datetime import timedelta

import streamlit as st

from agent import AgentContext
from agent_panel import agent_dock, agent_drawer
from auth_ui import render_header
from calendar_data import build_events
from state import DOCK_RATIO, agent_mode, get_calendar, get_recs, get_today, init_state
from viewport import mount_probe

st.set_page_config(page_title="F&B Pilot", page_icon=":material/storefront:", layout="wide")
st.logo("assets/logo.svg", size="large")
init_state()

page = st.navigation(
    [
        st.Page("app_pages/dashboard.py", title="대시보드", icon=":material/calendar_month:", default=True),
        st.Page("app_pages/inventory.py", title="매출/재고 관리", icon=":material/inventory_2:"),
        st.Page("app_pages/monitoring.py", title="매장 모니터링", icon=":material/monitor_heart:"),
        st.Page("app_pages/settings.py", title="설정", icon=":material/settings:"),
    ],
    position="sidebar",
)

today, cal, recs = get_today(), get_calendar(), get_recs()
ctx = AgentContext(today, recs, build_events(st.session_state.events, recs, cal, today, today + timedelta(days=14)))
mode = agent_mode()

render_header(page, mode, lambda: agent_drawer(ctx))

if mode == "dock" and st.session_state.agent_open:
    main, side = st.columns(list(DOCK_RATIO), gap="medium")
else:
    main, side = st.container(), None

with main:
    page.run()
if side is not None:
    with side:
        agent_dock(ctx)

mount_probe()   # 창 폭 측정 (맨 아래, 높이 0)
