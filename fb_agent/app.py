import streamlit as st

import routing
import style
from agent_context import build_context
from agent_panel import agent_dock, agent_drawer
from auth_ui import current_user, render_header, render_login
from menu import get_leaf
from nav_ui import apply_pending_navigation, build_pages, current_leaf_id, render_sidebar
from state import DOCK_RATIO, agent_mode, init_state
from viewport import mount_probe

st.set_page_config(page_title="F&B Pilot", page_icon="assets/logo-mark.svg", layout="wide")
style.inject()
init_state()

if current_user() is None:      # 처음 접속하면 로그인 화면만 보여 준다
    render_login()
    st.stop()
st.logo("assets/logo.svg", size="large")

pages = build_pages()
routing.PAGES = pages
page = st.navigation(list(pages.values()), position="hidden")   # 메뉴는 nav_ui가 직접 그린다
apply_pending_navigation()

leaf_id = current_leaf_id(page)
leaf = get_leaf(leaf_id)
chat_page = leaf.view == "ai.chat"          # Q&A 화면은 본문이 곧 대화창이라 에이전트 패널을 숨김
mode = agent_mode()
ctx = build_context()

render_sidebar(leaf_id)
render_header(leaf_id, leaf.title, mode, lambda: agent_drawer(ctx), show_agent=not chat_page)

if mode == "dock" and st.session_state.agent_open and not chat_page:
    main, side = st.columns(list(DOCK_RATIO), gap="medium")
else:
    main, side = st.container(), None

with main:
    page.run()
if side is not None:
    with side:
        agent_dock(ctx)

mount_probe()   # 창 폭 측정 (맨 아래, 높이 0)
