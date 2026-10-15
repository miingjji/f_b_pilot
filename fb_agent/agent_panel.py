"""F&B Agent 채팅 UI. 우측 고정 패널(dock)과 우측 서랍(drawer)이 같은 본문을 공유."""
import time

import streamlit as st

from agent import GREETING, QUICK_QUESTIONS, AgentContext, answer


def _queue_quick():
    st.session_state.agent_pending = st.session_state.agent_quick
    st.session_state.agent_quick = None


def _clear():
    st.session_state.messages = []


def _stream(text: str):
    for word in text.split(" "):
        yield word + " "
        time.sleep(0.012)


def render_chat(ctx: AgentContext, *, height: int, title: bool):
    ss = st.session_state
    with st.container(horizontal=True, vertical_alignment="center"):
        if title:
            st.markdown("#### :material/smart_toy: F&B Agent")
        if ss.messages:
            st.button("대화 지우기", icon=":material/delete_sweep:", type="tertiary", on_click=_clear)
    chat = st.container(height=height, border=False)
    suggest = st.container()
    prompt = st.chat_input("재고, 발주, 일정에 대해 물어보세요", key="agent_input") or ss.pop("agent_pending", None)

    if prompt:
        ss.messages.append({"role": "user", "content": prompt})
        reply = answer(prompt, ctx)
    with chat:
        if not ss.messages:
            with st.chat_message("assistant"):
                st.markdown(GREETING)
        for m in ss.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        if prompt:
            with st.chat_message("assistant"):
                st.write_stream(_stream(reply))
            ss.messages.append({"role": "assistant", "content": reply})
    if not ss.messages:
        with suggest:
            st.pills("추천 질문", QUICK_QUESTIONS, key="agent_quick", on_change=_queue_quick,
                     label_visibility="collapsed")


@st.fragment
def agent_dock(ctx: AgentContext):
    """우측 고정 패널. fragment라서 대화해도 중앙 페이지가 다시 그려지지 않음."""
    with st.container(border=True):
        render_chat(ctx, height=560, title=True)


@st.dialog("F&B Agent", position="right", width="medium", icon=":material/smart_toy:")
def agent_drawer(ctx: AgentContext):
    """우측에서 열리는 전체 높이 서랍. 달력은 그대로 넓게 쓸 수 있음."""
    render_chat(ctx, height=480, title=False)
