"""홈: 요약 카드 + 달력 대시보드."""
import calendar as pycal
import zlib
from datetime import date, timedelta

import streamlit as st

import sample_data as sd
import style
from calendar_data import (CATEGORIES, MANUAL_CATEGORIES, ORDER_STATUSES, Event, build_events, cell_width, chars_per_line,
                           max_cell_events, new_event, row_height, visible_events)
from errors import InvalidInputError
from menu import Leaf
from state import get_calendar, get_recs, get_store, get_today, main_width
from unit_info import qty_for
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


def shift_week(n: int):
    select_day(ss.sel_day + timedelta(days=7 * n))


def toggle_expand():
    ss.cal_expanded = not ss.get("cal_expanded", False)


def open_page(leaf_id: str):
    ss.nav_target = leaf_id         # nav_ui.apply_pending_navigation 이 다음 실행에서 이동


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


def event_cards(evs: list[Event]):
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


PANEL_HEIGHT = 420          # 하단 3칸 패널 높이 (넘치면 안에서 스크롤)
LIST_MAX = 8                # 패널에 나열할 품목 수 (나머지는 '외 N개')
UPCOMING_DAYS = 7
RECV_AHEAD_DAYS = 3
STATUS_BADGE = {"URGENT": ("긴급", "red"), "ORDER_NOW": ("지금 발주", "orange"), "ORDER_SOON": ("곧 발주", "blue")}


def day_label(d: date, today: date) -> str:
    return "오늘" if d == today else f"{d:%m/%d}({dow(d)})"


def item_list(rows: list[str], empty: str):
    """품목 줄을 LIST_MAX 개까지 보여 주고 나머지는 '외 N개'."""
    if not rows:
        st.caption(empty)
    for line in rows[:LIST_MAX]:
        st.markdown(line)
    if len(rows) > LIST_MAX:
        st.caption(f"… 외 {len(rows) - LIST_MAX}개")


def receiving_panel(recs: list, d: date, today: date):
    """선택한 날(기본 오늘) 입고 예정 품목."""
    due = sorted((r for r in recs if r.status in ORDER_STATUSES and r.arrival_date == d), key=lambda r: (r.supplier, r.item))
    with st.container(border=True, height=PANEL_HEIGHT):
        st.markdown(f"#### :material/move_to_inbox: {day_label(d, today)} 입고 품목")
        st.caption(f"{len(due)}개 품목")
        item_list([f"**{r.item}** · {r.supplier}" for r in due], "이 날 입고 예정인 품목이 없어요.")
        st.divider()
        st.markdown(f"**앞으로 {RECV_AHEAD_DAYS}일 입고 예정**")
        ahead = []
        for i in range(1, RECV_AHEAD_DAYS + 1):
            day = d + timedelta(days=i)
            by_supplier: dict[str, int] = {}
            for r in recs:
                if r.status in ORDER_STATUSES and r.arrival_date == day:
                    by_supplier[r.supplier] = by_supplier.get(r.supplier, 0) + 1
            ahead += [f":orange[●] {day:%m/%d}({dow(day)}) {sup} {n}개 품목" for sup, n in sorted(by_supplier.items())]
        item_list(ahead, "예정된 입고가 없어요.")
        st.button("입고 관리로 이동", icon=":material/arrow_forward:", type="tertiary", key="go_recv", on_click=open_page, args=("recv-general",))


def order_panel(recs: list, d: date, today: date):
    """선택한 날 발주해야 할 품목. 오늘은 이미 기한이 지난 '긴급·지금 발주' 품목도 포함한다."""
    due = [r for r in recs if r.status in ORDER_STATUSES
           and (r.order_date == d or (d == today and r.status in ("URGENT", "ORDER_NOW")))]
    due.sort(key=lambda r: (list(STATUS_BADGE).index(r.status), r.supplier, r.item))
    with st.container(border=True, height=PANEL_HEIGHT):
        st.markdown(f"#### :material/local_shipping: {day_label(d, today)} 발주 품목")
        st.caption(f"{len(due)}개 품목")
        rows = []
        for r in due:
            label, color = STATUS_BADGE[r.status]
            rows.append(f":{color}-badge[{label}] **{r.item}** · {r.supplier} · {qty_for(r.item, r.order_packs)}")
        item_list(rows, "이 날 발주할 품목이 없어요.")
        st.button("자동 발주 추천으로 이동", icon=":material/arrow_forward:", type="tertiary", key="go_po", on_click=open_page, args=("po-auto",))


def issue_panel(d: date, by_day: dict, today: date):
    """선택한 날의 매장 일정(이벤트·매출·인력 이슈·휴무) + 앞으로 7일."""
    cats = ("event", "sales", "staff", "closed")
    with st.container(border=True, height=PANEL_HEIGHT):
        st.markdown("#### :material/campaign: 매장 이슈")
        st.caption(f"{day_label(d, today)} 일정")
        mine = [e for e in by_day.get(d, []) if e.category in cats]
        if mine:
            event_cards(mine)
        else:
            st.caption("이 날은 등록된 이슈가 없어요.")
        st.divider()
        st.markdown(f"**앞으로 {UPCOMING_DAYS}일**")
        upcoming = [(day, e) for day in (d + timedelta(days=i) for i in range(1, UPCOMING_DAYS + 1))
                    for e in by_day.get(day, []) if e.category in cats]
        item_list([f":{CATEGORIES[e.category][1]}[●] {day:%m/%d}({dow(day)}) {e.title}" for day, e in upcoming], "예정된 이슈가 없어요.")


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
        for i, (label, value, delta) in enumerate([
            ("오늘 매출 (샘플)", won_short(now["sales"]), pct_delta(now["sales"], last_week["sales"]) + " 전주 같은 요일"),
            ("오늘 객수 (샘플)", f"{now['customers']:,}명", f"객단가 {won_short(now['ticket'])}"),
            ("오늘 근무 (샘플)", f"{staff}명", f"정직원 {full} · 파트 {staff - full}"),
            ("발주 필요 품목", f"{n_order}개", f"긴급 {n_urgent}개"),
            ("7일 내 일정", f"{n_week}건", f"오늘 {sum(e.category != 'closed' for e in week.get(today, []))}건"),
        ]):
            with st.container(key=f"kpi-{zlib.crc32(label.encode()):x}"):                # style.py 의 KPI 카드 CSS 대상
                st.html(style.kpi_chip(label, i))
                st.metric(label, value, delta, delta_color="off", delta_arrow="off")


def draw_grid(weeks: list, by_day: dict, today: date, sel: date, month: int | None):
    """7열 달력 격자. 창 폭에 맞춰 셀 글자 수/표시 일정 수를 정하고, 주(행)마다 필요한 높이만 쓴다.
    month 가 주어지면 그 달이 아닌 날은 빈 칸으로 둔다 (주간 보기는 None)."""
    cw = cell_width(main_width())
    cpl, limit = chars_per_line(cw), max_cell_events(cw)

    head = st.columns(7, gap="xsmall")
    for i, c in enumerate(head):
        c.markdown(f":red[{DOW[i]}]" if i == 0 else (f":blue[{DOW[i]}]" if i == 6 else DOW[i]))

    for wk in weeks:
        plan = {}   # 날짜 -> (표시할 일정, 숨긴 개수, 휴무 여부)
        for d in wk:
            if month is not None and d.month != month:
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
                          type="primary" if d == sel else "tertiary", on_click=select_day, args=(d,))
                if closed:
                    st.caption(":gray[휴무]")
                for e in kept:
                    event_line(e)
                if hidden:
                    st.caption(f"+{hidden}건 더보기")


@register("home.dashboard")
def dashboard(leaf: Leaf):
    today, cal, recs = get_today(), get_calendar(), get_recs()
    summary_cards(today, cal, recs)
    sel = ss.sel_day
    expanded = bool(ss.get("cal_expanded", False))
    m = ss.cal_month

    # ---- 도구 모음: 기본은 이번 주 한 줄, '달력 확대하기'로 한 달 전체 ----
    week_start = sel - timedelta(days=(sel.weekday() + 1) % 7)             # 일요일 시작
    week = [week_start + timedelta(days=i) for i in range(7)]
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button("이전", icon=":material/chevron_left:", type="tertiary",
                  on_click=shift_month if expanded else shift_week, args=(-1,))
        st.subheader(f"{m.year}년 {m.month}월" if expanded else f"{week[0]:%Y년 %m월 %d일} ~ {week[-1]:%m월 %d일}", width="content")
        st.button("다음", icon=":material/chevron_right:", type="tertiary",
                  on_click=shift_month if expanded else shift_week, args=(1,))
        st.button("오늘", on_click=go_today)
        st.button("주간으로 줄이기" if expanded else "달력 확대하기", key="cal_expand",
                  icon=":material/close_fullscreen:" if expanded else ":material/open_in_full:", on_click=toggle_expand)
        if st.button("일정 추가", icon=":material/add:", type="primary"):
            add_event_dialog()

    with st.container(horizontal=True):
        for label, color, icon in CATEGORIES.values():
            st.badge(label, icon=icon, color=color)

    if is_mobile():  # 좁은 화면: 7열 격자 대신 일정이 있는 날만 목록으로
        last = date(m.year, m.month, pycal.monthrange(m.year, m.month)[1])
        lo, hi = min(m, sel), max(last, sel + timedelta(days=UPCOMING_DAYS))
        by_day = build_events(ss.events, recs, cal, lo, hi)
        listed = [(d, [e for e in evs if e.category != "closed"]) for d, evs in sorted(by_day.items()) if m <= d <= last]
        listed = [(d, evs) for d, evs in listed if evs]
        if not listed:
            st.caption("이번 달에는 등록된 일정이 없어요.")
        for d, evs in listed:
            with st.container(border=True):
                st.button(f"{d.day}일 ({dow(d)})" + ("  오늘" if d == today else ""), key=f"ag_{d}",
                          type="primary" if d == sel else "tertiary", on_click=select_day, args=(d,))
                for e in evs:
                    event_line(e)
        st.divider()
    else:
        if expanded:
            weeks = pycal.Calendar(firstweekday=6).monthdatescalendar(m.year, m.month)
            month = m.month
        else:
            weeks, month = [week], None
        lo, hi = min(weeks[0][0], sel), max(weeks[-1][-1], sel + timedelta(days=UPCOMING_DAYS))
        by_day = build_events(ss.events, recs, cal, lo, hi)
        draw_grid(weeks, by_day, today, sel, month)

    # ---- 선택한 날(기본 오늘)의 입고 · 발주 · 매장 이슈를 같은 너비의 3칸으로 ----
    c_recv, c_order, c_issue = st.columns(3, gap="medium")
    with c_recv:
        receiving_panel(recs, sel, today)
    with c_order:
        order_panel(recs, sel, today)
    with c_issue:
        issue_panel(sel, by_day, today)

    st.caption("달력에는 직접 추가한 일정과, 재고 기반 발주·입고 일정, 매장 휴무가 함께 표시돼요. "
               "날짜를 누르면 아래 3칸이 그 날 기준으로 바뀌어요. 직접 추가한 일정은 현재 세션에만 저장됩니다.")
    sample_notice("POS·근태")
