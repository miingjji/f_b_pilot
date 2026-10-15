"""홈: 요약 카드 + 달력 대시보드."""
import calendar as pycal
from datetime import date, timedelta

import streamlit as st

import sample_data as sd
from calendar_data import (CATEGORIES, MANUAL_CATEGORIES, Event, build_events, cell_width, chars_per_line,
                           max_cell_events, new_event, row_height, visible_events)
from errors import InvalidInputError
from menu import Leaf
from state import get_calendar, get_recs, get_store, get_today, main_width
from viewport import is_mobile
from views import register
from views.common import pct_delta, sample_notice, won_short

ss = st.session_state
DOW = "일월화수목금토"          # 일요일 시작


def dow(d: date) -> str:
    return DOW[(d.weekday() + 1) % 7]


def select_day(d: date):
    ss.sel_day = d
    ss.cal_month = d.replace(day=1)


def shift_month(n: int):
    m = ss.cal_month
    idx = m.year * 12 + m.month - 1 + n
    ss.cal_month = date(idx // 12, idx % 12 + 1, 1)
    today = get_today()
    ss.sel_day = today if today.replace(day=1) == ss.cal_month else ss.cal_month


def shift_day(n: int):
    select_day(ss.sel_day + timedelta(days=n))


def go_today():
    select_day(get_today())


def delete_event(event_id: str):
    ss.events = [e for e in ss.events if e.id != event_id]


@st.dialog("일정 추가")
def add_event_dialog():
    with st.form("add_event", border=False):
        day = st.date_input("날짜", value=ss.sel_day)
        cat = st.selectbox("분류", MANUAL_CATEGORIES, format_func=lambda c: CATEGORIES[c][0])
        title = st.text_input("제목")
        detail = st.text_area("메모", height=80)
        if st.form_submit_button("추가", type="primary"):
            try:
                ss.events = [*ss.events, new_event(day, cat, title, detail)]
            except InvalidInputError as e:
                st.error(str(e))
            else:
                select_day(day)
                st.rerun()


def event_line(e: Event):
    """달력 셀용: 말줄임 없이 줄바꿈되는 '색 점 + 제목'."""
    st.caption(f":{CATEGORIES[e.category][1]}[●] {e.title}")


def day_detail(d: date, evs: list[Event], today: date):
    st.subheader(f"{d:%m월 %d일} ({dow(d)})" + (" · 오늘" if d == today else ""))
    if not evs:
        st.caption("등록된 일정이 없어요. 위의 '일정 추가'로 등록할 수 있어요.")
    for e in evs:
        label, color, icon = CATEGORIES[e.category]
        with st.container(border=True):
            top, act = st.columns([6, 1], vertical_alignment="center")
            with top:
                st.markdown(f":{color}-badge[{icon} {label}] **{e.title}**" + (" · _샘플_" if e.sample else ""))
                if e.detail:
                    st.caption(e.detail)
            if e.deletable:
                act.button("삭제", key=f"del_{e.id}", icon=":material/delete:", type="tertiary",
                           on_click=delete_event, args=(e.id,))


def summary_cards(today: date, cal, recs):
    store = get_store()
    now, last_week = sd.day_sales(store, today), sd.day_sales(store, today - timedelta(days=7))
    week = build_events(ss.events, recs, cal, today, today + timedelta(days=6))
    n_week = sum(e.category != "closed" for evs in week.values() for e in evs)
    n_order = sum(r.status in ("URGENT", "ORDER_NOW", "ORDER_SOON") for r in recs)
    n_urgent = sum(r.status == "URGENT" for r in recs)
    staff = sd.today_staff_count(store, today)
    full = sum(1 for n, k, _w in sd.STAFF if k == "정직원"
               and sd.month_schedule(store, today.year, today.month)[str(today.day)][n] != "휴")
    with st.container(horizontal=True):
        for label, value, delta in [
            ("오늘 매출 (샘플)", won_short(now["sales"]), pct_delta(now["sales"], last_week["sales"]) + " 전주 같은 요일"),
            ("오늘 객수 (샘플)", f"{now['customers']:,}명", f"객단가 {won_short(now['ticket'])}"),
            ("오늘 근무 (샘플)", f"{staff}명", f"정직원 {full} · 파트 {staff - full}"),
            ("발주 필요 품목", f"{n_order}개", f"긴급 {n_urgent}개"),
            ("7일 내 일정", f"{n_week}건", f"오늘 {sum(e.category != 'closed' for e in week.get(today, []))}건"),
        ]:
            with st.container(border=True):
                st.metric(label, value, delta, delta_color="off", delta_arrow="off")


@register("home.dashboard")
def dashboard(leaf: Leaf):
    today, cal, recs = get_today(), get_calendar(), get_recs()
    summary_cards(today, cal, recs)

    # ---- 도구 모음 ----
    m = ss.cal_month
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button("이전", icon=":material/chevron_left:", type="tertiary", on_click=shift_month, args=(-1,))
        st.subheader(f"{m.year}년 {m.month}월", width="content")
        st.button("다음", icon=":material/chevron_right:", type="tertiary", on_click=shift_month, args=(1,))
        st.button("오늘", on_click=go_today)
        view = st.segmented_control("보기", ["월", "일"], default="월", key="cal_view",
                                    label_visibility="collapsed") or "월"
        if st.button("일정 추가", icon=":material/add:", type="primary"):
            add_event_dialog()

    with st.container(horizontal=True):
        for label, color, icon in CATEGORIES.values():
            st.badge(label, icon=icon, color=color)

    if view == "월" and is_mobile():  # 좁은 화면: 7열 격자 대신 일정이 있는 날만 목록으로
        last = date(m.year, m.month, pycal.monthrange(m.year, m.month)[1])
        by_day = build_events(ss.events, recs, cal, m, last)
        listed = [(d, [e for e in evs if e.category != "closed"]) for d, evs in sorted(by_day.items())]
        listed = [(d, evs) for d, evs in listed if evs]
        if not listed:
            st.caption("이번 달에는 등록된 일정이 없어요.")
        for d, evs in listed:
            with st.container(border=True):
                st.button(f"{d.day}일 ({dow(d)})" + ("  오늘" if d == today else ""), key=f"ag_{d}",
                          type="primary" if d == ss.sel_day else "tertiary", on_click=select_day, args=(d,))
                for e in evs:
                    event_line(e)
        st.divider()
        day_detail(ss.sel_day, by_day.get(ss.sel_day, []), today)
    elif view == "월":
        weeks = pycal.Calendar(firstweekday=6).monthdatescalendar(m.year, m.month)
        by_day = build_events(ss.events, recs, cal, weeks[0][0], weeks[-1][-1])

        # 창 폭에 맞춰 셀 글자 수/표시 일정 수를 정하고, 주(행)마다 필요한 높이만 사용
        cw = cell_width(main_width())
        cpl, limit = chars_per_line(cw), max_cell_events(cw)

        head = st.columns(7, gap="xsmall")
        for i, c in enumerate(head):
            c.markdown(f":red[{DOW[i]}]" if i == 0 else (f":blue[{DOW[i]}]" if i == 6 else DOW[i]))

        for wk in weeks:
            plan = {}   # 날짜 -> (표시할 일정, 숨긴 개수, 휴무 여부)
            for d in wk:
                if d.month != m.month:
                    continue
                evs = by_day.get(d, [])
                shown = [e for e in evs if e.category != "closed"]
                kept, hidden = visible_events(shown, limit)
                plan[d] = (kept, hidden, len(evs) != len(shown))
            height = row_height(list(plan.values()), cpl)

            cols = st.columns(7, gap="xsmall")
            for d, c in zip(wk, cols):
                with c, st.container(border=True, height=height):
                    if d not in plan:
                        st.caption(str(d.day))
                        continue
                    kept, hidden, closed = plan[d]
                    st.button(f"{d.day}" + ("  오늘" if d == today else ""), key=f"day_{d}",
                              type="primary" if d == ss.sel_day else "tertiary", on_click=select_day, args=(d,))
                    if closed:
                        st.caption(":gray[휴무]")
                    for e in kept:
                        event_line(e)
                    if hidden:
                        st.caption(f"+{hidden}건 더보기")
        st.divider()
        day_detail(ss.sel_day, by_day.get(ss.sel_day, []), today)
    else:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.button("전날", icon=":material/chevron_left:", type="tertiary", on_click=shift_day, args=(-1,))
            st.button("다음날", icon=":material/chevron_right:", type="tertiary", on_click=shift_day, args=(1,))
        d = ss.sel_day
        day_detail(d, build_events(ss.events, recs, cal, d, d).get(d, []), today)

    st.caption("달력에는 직접 추가한 일정과, 재고 기반 발주·입고 일정, 매장 휴무가 함께 표시돼요. "
               "직접 추가한 일정은 현재 세션에만 저장됩니다.")
    sample_notice("POS·근태")
