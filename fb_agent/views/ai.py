"""F&B AI 에이전트: AI 운영 분석 · Q&A 대화창."""
from datetime import timedelta

import streamlit as st

import sales_data as sd
from agent import TOPIC_QUESTIONS
from agent_context import build_context
from agent_panel import render_chat
from insights import build_alerts
from menu import Leaf, breadcrumb
from routing import go
from state import get_calendar, get_recs, get_store, get_today
from unit_info import qty_for
from views import register
from views.common import kpis, no_data, pct_delta, sales_notice, won

LEVEL = {"high": ("긴급", "red", ":material/error:"), "medium": ("주의", "orange", ":material/warning:"),
         "info": ("정보", "blue", ":material/info:")}


@register("ai.report")
def report(leaf: Leaf):
    sales_notice("POS")
    store, recs = get_store(), get_recs()
    end = sd.latest_day(get_today())
    if end is None:
        return no_data("매출 데이터가 없어요.")
    cur, prev = sd.daily(end - timedelta(days=6), end), sd.daily(end - timedelta(days=13), end - timedelta(days=7))
    s_now, s_prev = int(cur["sales"].sum()), int(prev["sales"].sum())
    ticket = int(cur["sales"].sum() / max(1, cur["customers"].sum()))
    todo = [r for r in recs if r.status in ("URGENT", "ORDER_NOW", "ORDER_SOON")]
    alerts = [a for a in build_alerts(store, end, recs) if a.level != "info"]

    kpis([("7일 매출", won(s_now), (pct_delta(s_now, s_prev) + " 전주 대비") if s_prev else None), ("객단가", won(ticket), None),
          ("발주 필요", f"{len(todo)}개", None)])

    lines = [f"**{store} 주간 운영 요약 ({end - timedelta(days=6):%m/%d}~{end:%m/%d}, 영업일 {len(cur)}일)**", "",
             f"- 매출 {won(s_now)}" + (f" (전주 대비 {pct_delta(s_now, s_prev)})" if s_prev else "") + f", 객단가 {won(ticket)}"]
    lines += [f"- 발주 필요: {r.item} ({r.supplier}, {qty_for(r.item, r.order_packs)}, {r.status})" for r in todo] or ["- 발주 필요 품목 없음"]
    lines += [f"- 주의: {a.title} — {a.detail}" for a in alerts] or ["- 감지된 이상징후 없음"]
    text = "\n".join(lines)

    with st.container(border=True):
        st.markdown(text)
    st.caption("복사해서 공유할 수 있는 텍스트")
    st.code(text, language=None)


@register("ai.alerts")
def alerts(leaf: Leaf):
    sales_notice("POS")
    found = build_alerts(get_store(), sd.anchor(get_today()), get_recs())
    st.caption("재고·매출·취소 데이터를 규칙으로 점검한 결과입니다 (인건비·인력 배치는 근태 데이터가 없어 점검하지 않아요).")
    for i, a in enumerate(found):
        label, color, icon = LEVEL[a.level]
        with st.container(border=True):
            left, right = st.columns([5, 2], vertical_alignment="center")
            with left:
                st.markdown(f":{color}-badge[{icon} {label}] **{a.title}**")
                st.caption(a.detail)
            if right.button(" › ".join(breadcrumb(a.leaf)[1:]), key=f"alert_go_{i}", icon=":material/arrow_forward:", width="stretch"):
                go(a.leaf)


@register("ai.chat")
def chat(leaf: Leaf):
    st.caption(f"'{leaf.arg}' 관련 질문을 자유롭게 해보세요. 추천 질문을 눌러도 돼요.")
    with st.container(border=True):
        render_chat(build_context(), height=520, title=False, quick=TOPIC_QUESTIONS[leaf.arg])
