"""발주 및 재고관리: 발주관리 · 입고관리 · 기타입출고 · 수불관리."""
import re
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import activity
import inventory_sim
import routing
import sales_data
import reorder_engine
import stock_sim
import store_calendar
from config import TEST_MASTER
from converter import parse_count, to_grams
from data import ITEMS, SUPPLIERS
from errors import InvalidInputError
from importer import TEMPLATE_CSV, parse_inventory_file
from insights import build_table, stock_from_table
from menu import STORES, Leaf
from models import fmt_amount
from order_units import UNIT_SHORT, WHOLE_UNITS, packs_for
from reorder import fmt_date, is_order_day, order_days, recommend, safety_stock
from style import DANGER, WARN
from state import get_calendar, get_store, get_today, inv_state, on_order_g, position_g, stock_note, stock_note_short
from unit_info import display_unit, qty_for, qty_of, stock_of, unit_name, units_of
from views import register
from views.common import axis_chart, kpis

ss = st.session_state

# 상태: (라벨, 배지 색, 아이콘)
STATUS = {
    "URGENT": ("긴급", "red", ":material/error:"),
    "ORDER_NOW": ("지금 발주", "orange", ":material/shopping_cart:"),
    "ORDER_SOON": ("곧 발주", "yellow", ":material/schedule:"),
    "OK": ("양호", "green", ":material/check_circle:"),
    "NO_USAGE": ("소비 없음", "gray", ":material/remove_circle:"),
    "NO_DATA": ("데이터 없음", "gray", ":material/help:"),
}
ACTION = ("URGENT", "ORDER_NOW", "ORDER_SOON")
MAX_CARDS = 10   # 우선 처리를 한 번에 펼치는 최대 개수 (나머지는 표로)
STATUS_ORDER = {s: i for i, s in enumerate(STATUS)}


# ---------------- 공통 ----------------
def current_results():
    """(품목, 총 재고(기본단위), 추천) 목록. 현재 매장의 재고 기준. 추천은 재고에 이미 오는 중인 입고(시뮬레이션 예측)를 더한 값으로 계산한다."""
    stock, pos = inv_state()["stock_g"], position_g()
    today, cal = get_today(), get_calendar()
    out = [(ITEMS[n], g, recommend(ITEMS[n], pos[n], today, cal)) for n, g in stock.items() if n in ITEMS]     # 판단은 재고 + 이미 오는 중인 입고
    return sorted(out, key=lambda x: STATUS_ORDER[x[2].status])


@st.cache_data(show_spinner=False)
def _active_codes(stamp: float) -> frozenset:
    return frozenset(activity.recent_activity_codes() or ())


def active_codes() -> frozenset | None:
    """최근 45일 안에 입고·구매청구가 있었던 품목코드. 테스트 마스터이거나 활동 자료가 없으면 None (거르지 않는다)."""
    if TEST_MASTER:
        return None
    return _active_codes(activity.stamp()) or None


def dormant_toggle(key: str, label: str | None = None) -> bool:
    """'활동 없는 품목도 보기' 스위치. 선택은 화면을 옮겨도 유지한다(cfg_show_dormant)."""
    on = st.toggle(label or f"최근 {activity.DORMANT_DAYS}일 입고·청구가 없는 품목도 보기", value=ss.get("cfg_show_dormant", False), key=key,
                   help=f"기본은 최근 {activity.DORMANT_DAYS}일 안에 입고나 구매청구가 있었던 품목과 발주가 필요한 품목만 보여줍니다. 몇 달에 한 번 사는 집기·유니폼, 쓰지 않는 품목은 숨겨져요.")
    ss.cfg_show_dormant = on
    return on


def only_active(results, show_all: bool):
    """(품목, 재고, 추천) 목록에서 활동 있는 품목(또는 발주가 필요한 품목)만. (남긴 목록, 숨긴 개수)."""
    codes = active_codes()
    if show_all or codes is None:
        return results, 0
    keep = [(it, g, r) for it, g, r in results if it.code in codes or r.status in ACTION]
    return keep, len(results) - len(keep)


def add_stock(item: str, packs: float):
    """입고(+)·반품/손망실(-)을 현재 매장 재고표의 PK 칸에 반영."""
    s = inv_state()
    t = s["table"].copy()
    idx = t.index[t["품목"] == item]
    if len(idx):
        t.loc[idx[0], "PK"] = max(0.0, float(t.loc[idx[0], "PK"]) + packs)
        s["table"] = t
        s["ver"] += 1


def item_label(name: str) -> str:
    it = ITEMS[name]
    return f"{name} · {it.code} · {it.spec}"


ALL_SUP = "전체 업체"


def item_filter(key: str, items: list) -> list:
    """품목을 고르기 전에 업체 선택 + 검색창(품목명·코드·규격)으로 후보를 좁힌다. 좁혀진 품목 목록을 돌려준다."""
    c1, c2 = st.columns([2, 3], vertical_alignment="bottom")
    sups = sorted({it.supplier.name for it in items})
    sup = c1.selectbox("업체", [ALL_SUP, *sups], key=f"{key}_sup")
    q = c2.text_input("품목 검색", placeholder="품목명 · 품목코드 · 규격", key=f"{key}_q", icon=":material/search:").strip().lower()
    out = [it for it in items if (sup == ALL_SUP or it.supplier.name == sup) and (not q or q in f"{it.name} {it.code} {it.spec}".lower())]
    if not out:
        st.caption("조건에 맞는 품목이 없어요. 업체나 검색어를 바꿔 보세요.")
    return out


def status_badge(status: str):
    label, color, icon = STATUS[status]
    st.badge(label, icon=icon, color=color)


def rec_card(item, g, r, *, request_button=False):
    """품목 하나의 재고 상태와 발주 추천."""
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            status_badge(r.status)
            st.markdown(f"**{item.name}** · {item.supplier.name}")
        st.markdown(r.message)
        with st.container(horizontal=True):
            coming = on_order_g().get(item.name, 0.0)
            st.metric("재고", stock_of(item, g), item.fmt(g) + (f" · 오는 중 {stock_of(item, coming)}" if coming else ""), delta_color="off", delta_arrow="off", border=True)
            st.metric("잔여", "-" if r.days_left is None else f"{r.days_left:.1f}일", f"소진 {fmt_date(r.stockout_date)}",
                      delta_color="off", delta_arrow="off", border=True)
            st.metric("발주 → 입고", fmt_date(r.order_date), fmt_date(r.arrival_date), delta_color="off", delta_arrow="off", border=True)
            st.metric("추천 수량", qty_of(item, r.order_packs), delta_color="off", delta_arrow="off", border=True)
        if request_button and r.status in ACTION:
            st.button("구매청구 만들기", key=f"mkreq_{item.name}", icon=":material/add_shopping_cart:",
                      on_click=request_and_open, args=(item.name, r.order_packs, r.arrival_date, "자동 발주 추천"))


# ---------------- 발주관리 ----------------
def qty_input(label: str, it, *, key: str, min_value: float = 0.5, default: float | None = None, container=st) -> float:
    """품목의 발주단위로 수량을 입력받고 PK 로 돌려준다. 박스·개·병은 1씩, 팩·kg 는 0.5씩 늘어난다."""
    u = units_of(it)
    whole = u.unit in WHOLE_UNITS
    lo = max(min_value, 1.0) if whole and min_value else min_value
    q = container.number_input(f"{label} ({unit_name(it)})", min_value=lo, value=max(lo, default if default is not None else 1.0),
                               step=1.0 if whole else 0.5, key=key, label_visibility="collapsed" if label == "" else "visible")
    return round(q * u.per, 2)


def pk_df(df: pd.DataFrame) -> pd.DataFrame:
    """표의 '수량(PK)' 열을 품목 발주단위 표기('2박스', '24병 (2박스)')의 '수량' 열로 바꾼다."""
    if "수량(PK)" not in df or "품목" not in df:
        return df
    out = df.copy()
    out["수량(PK)"] = [qty_for(n, p) for n, p in zip(out["품목"], out["수량(PK)"])]
    return out.rename(columns={"수량(PK)": "수량"})


def add_request(item: str, packs: float, want: date | None, memo: str, toast: bool = True, order_day: date | None = None):
    ss.purchase_requests = [*ss.purchase_requests, {
        "청구번호": f"PR-{len(ss.purchase_requests) + 1:04d}", "청구일": get_today(), "품목": item,
        "거래처": ITEMS[item].supplier.name, "수량(PK)": packs, "발주예정일": order_day, "희망입고일": want, "메모": memo, "상태": "청구"}]
    if toast:
        st.toast(f"구매청구를 만들었어요: {item} {qty_for(item, packs)}", icon=":material/check_circle:")


def request_and_open(item: str, packs: float, want: date | None, memo: str):
    """한 품목을 구매청구로 만들고 청구 목록 창을 바로 연다."""
    add_request(item, packs, want, memo, toast=False)
    open_req_list()


def add_requests_bulk(todo):
    """우선 처리 품목 전체를 한 번에 구매청구로 (이미 청구한 품목은 건너뜀)."""
    pending = {r["품목"] for r in ss.purchase_requests if r["상태"] == "청구"}
    made = 0
    for it, _g, r in todo:
        if it.name not in pending:
            add_request(it.name, r.order_packs, r.arrival_date, "자동 발주 추천", toast=False)
            made += 1
    st.toast(f"구매청구 {made}건을 만들었어요 (이미 청구한 {len(todo) - made}건은 건너뜀).", icon=":material/check_circle:")
    open_req_list()


def convert_to_po(req_no: str, toast: bool = True):
    for r in ss.purchase_requests:
        if r["청구번호"] == req_no and r["상태"] == "청구":
            lead = ITEMS[r["품목"]].lead_time_days or 0
            ss.purchase_orders = [*ss.purchase_orders, {
                "발주번호": f"PO-{len(ss.purchase_orders) + 1:04d}", "거래처": r["거래처"], "품목": r["품목"],
                "수량(PK)": r["수량(PK)"], "발주일": r.get("발주예정일") or get_today(),
                "입고예정": r["희망입고일"] or get_today() + timedelta(days=lead), "입고수량(PK)": 0.0, "상태": "입고대기"}]
            r["상태"] = "발주완료"
            if toast:
                st.toast(f"{req_no}을(를) 발주서로 전환했어요.", icon=":material/check_circle:")
            return


def _pending() -> list:
    return [r for r in ss.purchase_requests if r["상태"] == "청구"]


def _selected() -> list:
    return [r for r in _pending() if ss.get(f"cvsel_{r['청구번호']}")]


def ask_convert(on: bool):
    ss.cv_confirm = on


def pick_all(sup: str, on: bool):
    for r in _pending():
        if r["거래처"] == sup:
            ss[f"cvsel_{r['청구번호']}"] = on
    ss.cv_confirm = False


def do_convert():
    chosen = _selected()
    for r in chosen:
        convert_to_po(r["청구번호"], toast=False)
        ss[f"cvsel_{r['청구번호']}"] = False
    ss.cv_confirm = False
    ss.cv_done = f"{len(chosen)}건을 발주서로 전환했어요."      # 알림은 창 본문에서 띄운다 (콜백에서 화면 요소를 그리면 안 됨)


def open_req_list():
    ss.cv_confirm = False
    ss.pop("cv_done", None)
    for r in ss.purchase_requests:
        ss[f"cvsel_{r['청구번호']}"] = False
    req_list_dialog()


@st.dialog("청구 목록", width="large")
def req_list_dialog():
    """업체별 청구 목록. 지금 발주할 건만 골라 전환한다 (전환 전에 같은 창 안에서 한 번 더 확인)."""
    reqs = ss.purchase_requests
    if ss.get("cv_done"):
        st.success(ss.pop("cv_done"), icon=":material/check_circle:")
    if not reqs:
        st.caption("등록된 구매청구가 없어요.")
        return
    st.caption("지금 발주할 청구만 체크한 뒤 아래 '선택 발주 전환'을 누르세요. 체크하지 않은 청구는 그대로 남아요.")
    for sup in dict.fromkeys(r["거래처"] for r in reversed(reqs)):
        mine = [r for r in reversed(reqs) if r["거래처"] == sup]
        pend = [r for r in mine if r["상태"] == "청구"]
        with st.container(border=True):
            head, a1, a2 = st.columns([5, 1.3, 1.3], vertical_alignment="center")
            head.markdown(f"**{sup}** · 청구 {len(mine)}건" + (f" · 전환 대기 {len(pend)}건" if pend else " · 모두 발주 전환됨"))
            if pend:
                a1.button("전체 선택", key=f"cvall_{sup}", width="stretch", on_click=pick_all, args=(sup, True))
                a2.button("선택 해제", key=f"cvnone_{sup}", width="stretch", on_click=pick_all, args=(sup, False))
            for r in mine:
                line = f"{r['청구번호']} · {r['품목']} {qty_for(r['품목'], r['수량(PK)'])} · 발주 {fmt_date(r.get('발주예정일'))} → 입고 {fmt_date(r['희망입고일'])}"
                if r["상태"] == "청구":
                    st.checkbox(line, key=f"cvsel_{r['청구번호']}", on_change=ask_convert, args=(False,))
                else:
                    st.markdown(f":gray[{line} · {r['상태']}]")
    chosen = _selected()
    if not _pending():
        return
    if ss.get("cv_confirm") and chosen:
        with st.container(border=True, key="cvbox"):
            st.markdown(f"**선택한 {len(chosen)}건**을 발주로 전환하시겠습니까? 전환하면 입고 대기 상태가 돼요.")
            st.dataframe(pd.DataFrame([{"거래처": r["거래처"], "청구번호": r["청구번호"], "품목": r["품목"], "수량": qty_for(r["품목"], r["수량(PK)"]),
                                        "발주일": fmt_date(r.get("발주예정일")), "입고 예정": fmt_date(r["희망입고일"])} for r in chosen]),
                         hide_index=True, width="stretch")
            ok, no, _ = st.columns([2, 1, 3])
            ok.button(f"발주 전환 ({len(chosen)}건)", key="cvok", type="primary", icon=":material/check:", width="stretch", on_click=do_convert)
            no.button("취소", key="cvno", width="stretch", on_click=ask_convert, args=(False,))
    else:
        st.button(f"선택 발주 전환 ({len(chosen)}건)", key="cvgo", type="primary", icon=":material/swap_horiz:", disabled=not chosen, on_click=ask_convert, args=(True,))


REQ_PAGE = 12            # 구매청구 화면에서 한 페이지에 보여 주는 품목 카드 수
REQ_COLS = 3
REQ_SUP_COLS = 5         # 거래처 카드 한 줄 개수
REQ_NEED, REQ_ALL = "발주 필요", "전체"      # 거래처 선택에 함께 놓는 묶음


def _cart() -> dict:
    """청구할 품목 {품목명: 수량(품목의 발주단위)}. 거래처를 바꿔도 유지된다."""
    return ss.setdefault("req_cart", {})


def cart_add(name: str):
    _cart()[name] = float(ss[f"rq_{name}"])


def cart_remove(name: str):
    _cart().pop(name, None)


CAL_WEEKS = 4            # 일정 달력에 보여 주는 주 수


def _cart_items(sup: str) -> list:
    return [ITEMS[n] for n in _cart() if ITEMS[n].supplier.name == sup]


def item_days(it) -> list[date]:
    """품목의 발주 가능일 (업체 발주 요일·매장 영업일·입고일 영업일). 품목마다 따로 계산한다."""
    today, cal = get_today(), get_calendar()
    return [today + timedelta(days=i) for i in range(CAL_WEEKS * 7) if is_order_day(it, today + timedelta(days=i), cal)]


def day_key(name: str) -> str:
    return f"req_day_{name}"


def day_advice(items: list, days: list[date], info: dict) -> tuple[date | None, dict]:
    """발주일 후보별 조언. (권장일, {날짜: 문구}). 권장일 = 담긴 품목 모두가 재고 소진·안전재고 전에 입고되는 마지막 발주일 (엔진의 '발주 예정일' 기준).
    그보다 늦은 날은 결품 예상 일수를 알려 준다. 근거가 없는 품목(소비·리드타임 데이터 없음)은 판단에서 뺀다."""
    recs = [(it, info[it.name][1]) for it in items if it.name in info and info[it.name][1].order_date is not None]
    if not days or not recs:
        return None, {}
    limit = min(r.order_date for _it, r in recs)
    safe = [d for d in days if d <= limit]
    best = safe[-1] if safe else days[0]
    out = {}
    for d in days:
        gap = max((max(0, (d + timedelta(days=it.lead_time_days) - r.stockout_date).days) for it, r in recs if r.stockout_date and it.lead_time_days is not None), default=0)
        if d == best:
            out[d] = "권장" if safe else "권장 · 가장 빠른 날"
        elif d > best:
            out[d] = f"결품 {gap}일 예상" if gap else "안전재고 부족 가능"
    return best, out


def chosen_day(it) -> date | None:
    """사용자가 고른 발주일. 고른 적이 없거나 더는 가능하지 않으면 가장 빠른 발주 가능일."""
    days = item_days(it)
    pick = ss.get(day_key(it.name))
    return pick if pick in days else (days[0] if days else None)


def item_schedule(it) -> tuple[date | None, date | None]:
    """(발주일, 입고 예정일). 품목 카드에서 고른 날이 있으면 그 날, 없으면 가장 빠른 발주 가능일."""
    od = chosen_day(it)
    return (od, od + timedelta(days=it.lead_time_days)) if od and it.lead_time_days is not None else (None, None)


def set_days(names: list[str], how: str, info: dict):
    """how: 'first' 가장 빠른 날 / 'best' 권장일 (근거가 없는 품목은 가장 빠른 날)."""
    for n in names:
        days = item_days(ITEMS[n])
        best = day_advice([ITEMS[n]], days, info)[0] if how == "best" else None
        if days:
            ss[day_key(n)] = best or days[0]


def cart_submit():
    cart = _cart()
    memo = ss.get("req_memo", "")
    for name, qty in cart.items():
        od, arr = item_schedule(ITEMS[name])
        add_request(name, round(qty * units_of(ITEMS[name]).per, 2), arr, memo, toast=False, order_day=od)
    ss.req_cart = {}
    open_req_list()                                              # 등록하면 바로 청구 목록 창을 띄워 발주 전환으로 이어 준다


def req_item_card(it, g, r):
    """품목 카드: 이름·규격·재고·추천 + 수량을 정해 청구 목록에 담는다. 수량은 모두 품목의 발주단위로 보여 준다."""
    in_cart = it.name in _cart()
    u = units_of(it)
    one = (f"1박스 = {u.count}{u.each} ({fmt_amount(u.each_amt * u.count, 'ml') if u.each in ('병', '캔') else it.fmt(u.each_amt * u.count)})" if u.each
           else f"1{unit_name(it)} = {it.fmt(it.pk_weight_g * u.per)}")
    with st.container(border=True):
        st.markdown(f"**{it.name}**")
        st.caption(f"{it.code} · {one} · {it.mid}")
        with st.container(horizontal=True, vertical_alignment="center"):
            if r.status in ACTION:
                status_badge(r.status)
                st.caption(f"추천 {qty_of(it, r.order_packs)}")
            st.caption(f"재고 {stock_of(it, g)}")
        whole = u.unit in WHOLE_UNITS
        lo = 1.0 if whole else 0.5
        default = round(r.order_packs / u.per, 2) if r.status in ACTION and r.order_packs else 1.0
        st.number_input(f"수량 ({unit_name(it)})", min_value=lo, value=max(lo, default), step=1.0 if whole else 0.5,
                        key=f"rq_{it.name}", label_visibility="collapsed")
        st.button("수정" if in_cart else "담기", key=f"rqb_{it.name}", icon=":material/check:" if in_cart else ":material/add_shopping_cart:",
                  type="primary" if in_cart else "secondary", width="stretch", on_click=cart_add, args=(it.name,))


def req_list_button(key: str):
    """청구 목록 창을 다시 여는 작은 버튼. 대기 중인 청구가 있으면 건수를 함께 보여 준다."""
    n, waiting = len(ss.purchase_requests), sum(r["상태"] == "청구" for r in ss.purchase_requests)
    st.button(f"청구 목록 보기 ({n}건" + (f" · 전환 대기 {waiting}건" if waiting else "") + ")", key=key, type="primary" if waiting else "secondary",
              icon=":material/list_alt:", width="stretch", disabled=not n, on_click=open_req_list, help="등록한 청구를 업체별로 확인하고, 지금 발주할 것만 골라 발주서로 전환합니다.")


@register("po.request")
def po_request(leaf: Leaf):
    c_cap, c_open = st.columns([5, 2], gap="medium", vertical_alignment="center")    # 아래 본문·청구 패널과 같은 열 비율 → 버튼 폭이 패널과 같다
    with c_open:
        req_list_button("open_req_list")
    c_cap.caption("거래처를 고르고 품목 카드에서 수량을 정해 '담기' → 오른쪽 청구 목록에서 품목마다 발주일·입고일을 정하고 한 번에 등록합니다. 등록하면 청구 목록 창이 바로 열려 업체별로 확인한 뒤 발주서로 전환해요.")
    today, cal = get_today(), get_calendar()
    stock, pos = inv_state()["stock_g"], position_g()
    info = {it.name: (stock.get(it.name, 0.0), recommend(it, pos.get(it.name, 0.0), today, cal)) for it in ITEMS.values()}
    need = [n for n, (_g, r) in info.items() if r.status in ACTION]
    by_sup: dict = {}
    for it in ITEMS.values():
        by_sup.setdefault(it.supplier.name, []).append(it)
    labels = {f"{REQ_NEED} ({len(need)})": REQ_NEED, f"{REQ_ALL} ({len(ITEMS)})": REQ_ALL,
              **{f"{n} ({len(v)})": n for n, v in sorted(by_sup.items(), key=lambda kv: (-len(kv[1]), kv[0]))}}

    main, side = st.columns([5, 2], gap="medium")
    with main:
        st.markdown("##### 거래처")
        names = list(labels)
        if ss.get("req_supplier") not in labels:
            ss.req_supplier = names[0]
        pick = ss.req_supplier
        with st.container(height=230, border=True):
            for i in range(0, len(names), REQ_SUP_COLS):
                for col, n in zip(st.columns(REQ_SUP_COLS), names[i:i + REQ_SUP_COLS]):
                    col.button(n, key=f"req_sup_{n}", type="primary" if n == pick else "secondary", width="stretch",
                               on_click=ss.__setitem__, args=("req_supplier", n))
        sup = labels[pick]
        items = ([ITEMS[n] for n in need] if sup == REQ_NEED else list(ITEMS.values()) if sup == REQ_ALL else by_sup[sup])
        c1, c2 = st.columns([2, 3], vertical_alignment="bottom")
        q = c1.text_input("품목 검색", placeholder="이름 · 품목코드 · 규격", key="req_q").strip().lower()
        mids = sorted({it.mid for it in items if it.mid})
        mid = c2.segmented_control("분류", [REQ_ALL, *mids], default=REQ_ALL, key="req_mid") if len(mids) > 1 else REQ_ALL
        if q:
            items = [it for it in items if q in f"{it.name} {it.code} {it.spec}".lower()]
        if mid and mid != REQ_ALL:
            items = [it for it in items if it.mid == mid]
        items = sorted(items, key=lambda it: (info[it.name][1].status not in ACTION, STATUS_ORDER[info[it.name][1].status], it.name))

        sig = (sup, q, mid)
        if ss.get("req_sig") != sig:                                   # 거래처·검색·분류가 바뀌면 첫 페이지부터
            ss.req_sig, ss.req_page = sig, 0
        pages = max(1, -(-len(items) // REQ_PAGE))
        page = min(ss.get("req_page", 0), pages - 1)
        st.markdown(f"##### 품목 ({len(items)}개)")
        if not items:
            st.info("조건에 맞는 품목이 없습니다. 검색어나 분류를 바꿔 보세요.", icon=":material/search_off:")
        shown = items[page * REQ_PAGE:(page + 1) * REQ_PAGE]
        for row in range(0, len(shown), REQ_COLS):
            cols = st.columns(REQ_COLS)
            for col, it in zip(cols, shown[row:row + REQ_COLS]):
                with col:
                    req_item_card(it, *info[it.name])
        if pages > 1:
            with st.container(horizontal=True, vertical_alignment="center", horizontal_alignment="center"):
                st.button("이전", icon=":material/chevron_left:", disabled=page == 0, key="req_prev", on_click=lambda: ss.update(req_page=page - 1))
                st.caption(f"{page + 1} / {pages} 페이지")
                st.button("다음", icon=":material/chevron_right:", disabled=page >= pages - 1, key="req_next", on_click=lambda: ss.update(req_page=page + 1))

    with side:
        with st.container(border=True, key="req-cart"):                      # 스크롤해도 따라오게 style.py 에서 고정
            cart = _cart()
            st.markdown(f"##### 청구 목록 ({len(cart)})")
            if not cart:
                st.caption("카드에서 '담기'를 누르면 여기에 쌓여요. 품목별 발주일 · 입고일도 여기서 정해요.")
            for sup in sorted({ITEMS[n].supplier.name for n in cart}):
                items = _cart_items(sup)
                names = [it.name for it in items]
                with st.expander(f"{sup} · {len(items)}개 품목", expanded=len({ITEMS[n].supplier.name for n in cart}) == 1):
                    b1, b2 = st.columns(2)
                    b1.button("모두 빠른 날로", key=f"rqfirst_{sup}", width="stretch", on_click=set_days, args=(names, "first", info))
                    b2.button("모두 권장일로", key=f"rqbest_{sup}", width="stretch", on_click=set_days, args=(names, "best", info),
                              help="권장일 = 재고 소진·안전재고 전에 입고되는 마지막 발주일. 여유가 0일이라 하루만 어긋나도 결품 위험이 생겨요.")
                    for it in items:
                        with st.container(horizontal=True, vertical_alignment="center"):
                            st.markdown(f"**{it.name}**  \n:gray[{qty_of(it, round(cart[it.name] * units_of(it).per, 2))}]")
                            st.button("", key=f"rqx_{it.name}", icon=":material/close:", type="tertiary", on_click=cart_remove, args=(it.name,), help="목록에서 빼기")
                        days = item_days(it)
                        if not days or it.lead_time_days is None:
                            st.warning(f"앞으로 {CAL_WEEKS}주 안에 발주 가능한 날이 없어요." if it.lead_time_days is not None else "리드타임 데이터가 없어 날짜를 계산할 수 없어요.", icon=":material/event_busy:")
                            continue
                        key = day_key(it.name)
                        if ss.get(key) not in days:                                # 처음이거나 고른 날이 더는 가능하지 않으면 가장 빠른 발주일
                            ss[key] = days[0]
                        best, advice = day_advice([it], days, info)
                        st.selectbox("발주일 → 입고일", days, key=key, label_visibility="collapsed",
                                     format_func=lambda d, ad=advice, lt=it.lead_time_days: fmt_date(d) + " → " + fmt_date(d + timedelta(days=lt)) + (f"  ({ad[d]})" if d in ad else ""),
                                     help=f"발주 가능한 날만 나와요 (발주 {SUPPLIERS[sup].order_days_label}, 리드타임 D+{it.lead_time_days}, 휴점·입고 불가일 제외). "
                                          "(권장)은 이 품목이 재고 소진·안전재고 전에 입고되는 마지막 발주일이에요. 그보다 늦은 날은 결품 예상 일수를 알려 줘요.")
                sched = [item_schedule(it) for it in items]
                ods = sorted({od for od, _a in sched if od})
                if ods:
                    st.caption("발주 " + (fmt_date(ods[0]) if len(ods) == 1 else f"{fmt_date(ods[0])} ~ {fmt_date(ods[-1])} ({len(ods)}일로 나뉨)"))
                st.divider()
            st.text_input("메모", placeholder="선택", key="req_memo")
            st.button(f"청구 등록 ({len(cart)}건)", type="primary", icon=":material/add:", width="stretch", disabled=not cart, on_click=cart_submit)


@register("po.request_detail")
def po_request_detail(leaf: Leaf):
    reqs = ss.purchase_requests
    req_list_button("open_req_list_detail")
    kpis([("전체 청구", f"{len(reqs)}건", None), ("발주 전환", f"{sum(r['상태'] == '발주완료' for r in reqs)}건", None),
          ("대기", f"{sum(r['상태'] == '청구' for r in reqs)}건", None)])
    if not reqs:
        st.caption("등록된 구매청구가 없어요. '구매청구' 또는 '자동 발주 추천'에서 만들 수 있어요.")
        return
    status = st.segmented_control("상태", ["전체", "청구", "발주완료"], default="전체", key="req_status") or "전체"
    df = pk_df(pd.DataFrame(reqs))
    st.dataframe(df if status == "전체" else df[df["상태"] == status], hide_index=True, width="stretch", alt="구매청구 상세내역")


@register("po.leadtime")
def po_leadtime(leaf: Leaf):
    today, cal = get_today(), get_calendar()
    st.subheader("거래처")
    st.dataframe(pd.DataFrame([{"거래처": s.name, "발주 요일": s.order_days_label, "리드타임": s.lead_time_label}
                               for s in SUPPLIERS.values()]), hide_index=True, width="stretch", alt="거래처 리드타임")
    head, pick, search = st.columns([3, 2, 3], vertical_alignment="bottom")
    head.subheader("품목별 다음 발주 가능일")
    lsup = pick.selectbox("업체", [ALL_SUP, *SUPPLIERS], key="lt_sup")
    q = search.text_input("품목 검색", placeholder="품목명 · 거래처 · 품목코드", key="lt_q", icon=":material/search:").strip().lower()
    st.caption("거래처 발주 요일, 매장 휴무, 입고일 영업 여부를 모두 반영합니다.")
    rows = []
    for it in ITEMS.values():
        if (lsup != ALL_SUP and it.supplier.name != lsup) or (q and q not in f"{it.name} {it.supplier.name} {it.code}".lower()):
            continue
        days = order_days(it, today, cal)[:3]
        rows.append({"품목": it.name, "거래처": it.supplier.name, "리드타임": it.lead_time_label,
                     "다음 발주 가능일": " · ".join(fmt_date(d) for d in days) or "-",
                     "입고 예정": " · ".join(fmt_date(d + timedelta(days=it.lead_time_days)) for d in days) or "-"})
    if q:
        st.caption(f"'{q}' 검색 결과 {len(rows)}개 / 전체 {len(ITEMS)}개")
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", alt="품목별 다음 발주 가능일")
    else:
        st.info("검색 결과가 없습니다. 품목명이나 거래처 이름을 바꿔 보세요.", icon=":material/search_off:")


def rec_row(item, g, r):
    """우선 처리 한 줄: 상태·품목·재고·잔여일·발주→입고·추천 수량·청구 버튼. 카드(rec_card)보다 낮아서 한 화면에 여러 개가 보인다."""
    with st.container(border=True):
        c_name, c_stock, c_when, c_qty, c_btn = st.columns([5, 2, 4, 2, 3], vertical_alignment="center")
        with c_name:
            with st.container(horizontal=True, vertical_alignment="center"):
                status_badge(r.status)
                st.markdown(f"**{item.name}**")
            st.caption(f"{item.supplier.name} · {r.message}")
        coming = on_order_g().get(item.name, 0.0)
        c_stock.markdown(f"재고 **{stock_of(item, g)}**" + (f"  \n:gray[오는 중 {stock_of(item, coming)}]" if coming else ""))
        c_when.markdown(f"{fmt_date(r.order_date)} 발주 → {fmt_date(r.arrival_date)} 입고" + (f"  \n:gray[잔여 {r.days_left:.1f}일 · 소진 {fmt_date(r.stockout_date)}]" if r.days_left is not None else ""))
        c_qty.markdown(f"추천 **{qty_of(item, r.order_packs)}**")
        c_btn.button("구매청구 만들기", key=f"mkreq_{item.name}", icon=":material/add_shopping_cart:", width="stretch",
                     on_click=request_and_open, args=(item.name, r.order_packs, r.arrival_date, "자동 발주 추천"))


def other_view_link(leaf_id: str, label: str):
    if leaf_id in routing.PAGES:                                    # 앱 안에서만 (테스트 화면에는 페이지 목록이 없다)
        st.page_link(routing.PAGES[leaf_id], label=label, icon=":material/arrow_forward:")


@register("po.auto")
def po_auto(leaf: Leaf):
    st.caption("**재고가 언제 떨어지는지** 기준으로 발주할 품목을 보여 줍니다. 평소 주문 습관과 수량 근거까지 보려면 '발주 추천 (이력 기반)'을 보세요.")
    other_view_link("po-engine", "발주 추천 (이력 기반)")
    short = stock_note_short()
    with st.expander(short or f"'{get_store()}' 현재 재고 기준이에요", icon=":material/info:"):
        if short:
            st.markdown(stock_note())
        st.markdown(f"'{get_store()}' 현재 재고 기준입니다. 실제 재고는 '매장별 재고입력'에서 바꿀 수 있어요.")
    pool = {it.name for it in item_filter("pa", list(ITEMS.values()))}
    narrowed = len(pool) != len(ITEMS)                                     # 업체·검색으로 좁히면 활동 없는 품목도 찾을 수 있게 한다
    c_state, c_tg = st.columns([7, 3], vertical_alignment="center")
    with c_tg:
        show_all = dormant_toggle("po_auto_dormant", "활동 없는 품목도 보기")
    results, hidden = only_active([x for x in current_results() if x[0].name in pool], show_all or narrowed)
    n = {s: sum(r.status == s for _, _, r in results) for s in STATUS}
    with c_state:
        status_badges(n)
    if hidden:
        st.caption(f":material/visibility_off: 활동 있는 품목 {len(results)}개만 보고 있어요. 숨긴 품목 {hidden}개는 최근 {activity.DORMANT_DAYS}일 입고·청구가 없고 발주도 필요 없는 품목이에요.")
    todo = [(it, g, r) for it, g, r in results if r.status in ACTION]
    c_head, c_bulk = st.columns([6, 3], vertical_alignment="center")
    c_head.subheader(f"우선 처리 ({len(todo)}개)")
    if todo:
        c_bulk.button(f"위 {len(todo)}개 전체 구매청구 만들기", icon=":material/add_shopping_cart:", type="primary", on_click=add_requests_bulk, args=(todo,), width="stretch",
                      help="우선 처리 품목을 한 번에 구매청구로 만듭니다. 이미 청구한 품목은 건너뜁니다.")
    else:
        st.success("지금 발주할 품목이 없습니다.", icon=":material/check_circle:")
    for it, g, r in todo[:MAX_CARDS]:
        rec_row(it, g, r)
    if len(todo) > MAX_CARDS:
        st.caption(f"급한 순서로 {MAX_CARDS}개만 보여줘요. 나머지 {len(todo) - MAX_CARDS}개는 아래 '전체 품목 현황' 표에서 확인하세요 "
                   "(상태 순으로 정렬돼 있어요).")

    st.subheader("전체 품목 현황")
    oo = on_order_g()
    df = pd.DataFrame([{
        "상태": STATUS[r.status][0], "품목코드": it.code, "품목": it.name, "분류": it.mid, "거래처": it.supplier.name,
        "총재고": stock_of(it, g), "오는 중 입고": stock_of(it, oo[it.name]) if oo.get(it.name) else "",
        "잔여일": r.days_left, "소진예정": fmt_date(r.stockout_date), "발주예정일": fmt_date(r.order_date),
        "입고예정": fmt_date(r.arrival_date), "추천 수량": qty_of(it, r.order_packs),
        "비고": r.message} for it, g, r in results])
    st.dataframe(df, hide_index=True, width="stretch", alt="품목별 재고 상태와 발주 추천",
                 column_config={"잔여일": st.column_config.ProgressColumn("잔여일", min_value=0, max_value=14, format="%.1f일",
                                                                        help="14일을 가득 찬 값으로 표시"),
                                "비고": st.column_config.TextColumn(width="large")})
    st.subheader("거래처별 발주서")
    po = df[df["상태"].isin([STATUS[s][0] for s in ACTION])]
    if po.empty:
        st.caption("발주할 품목이 없습니다.")
    else:
        st.dataframe(po[["거래처", "품목", "추천 수량", "발주예정일", "입고예정", "상태"]]
                     .sort_values(["거래처", "발주예정일"]), hide_index=True, width="stretch", alt="거래처별 발주서")


# ---------------- 발주 추천 (이력 기반) ----------------
def _engine_stamp() -> float:
    """모델·자료 파일이 바뀌면 캐시를 새로 만들도록 하는 표시."""
    files = [reorder_engine.MODEL_PATH, *reorder_engine.DATA.glob("20*/구매청구_정제.csv"), *reorder_engine.DATA.glob("20*/매출일자별_정제.csv"),
             *reorder_engine.LEDGER.glob("20*/20*/실사재고_정제.csv")]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0)


@st.cache_resource(show_spinner="발주·입고 이력을 불러오는 중…")
def _engine(stamp: float):
    return reorder_engine.Engine()


@st.cache_data(show_spinner=False)
def _po_factors(origin: date, stamp: float) -> dict:
    """구매청구 발주단위 ↔ 수불부 규격 수량 비율 (시뮬레이션 재고를 발주단위로 바꿀 때)."""
    return inventory_sim.po_factors(inventory_sim.load_ledger(), _engine(stamp).b, f"{origin:%Y-%m}")


def _sim_order_units(day: date, stamp: float) -> dict:
    """{품목코드: day 아침 시뮬레이션 재고(발주단위)}. 쓸 예측이 없으면 {}."""
    raw, info = stock_sim.sim_stock_raw(day)
    if info is None:
        return {}
    fac = _po_factors(info["origin"], stamp)
    return {c: q * fac[c] for c, q in raw.items() if c in fac}


@st.cache_data(show_spinner="발주 추천을 계산하는 중…")
def _engine_table(day: date, stamp: float) -> pd.DataFrame:
    return _engine(stamp).recommend(day, use_stock=True, sim_stock=_sim_order_units(day, stamp)).drop(columns=["_key"])


def _qty(q, unit) -> str:
    return f"{q:g} {unit}"


def qty_range(q: float, unit: str, err: float) -> str:
    """권장 수량 ± 과거 검증 평균 오차(err, 0~1)를 발주 단위에 맞춰 '2~4 박스' 꼴로. 낱개 단위는 1 아래로 내려가지 않는다."""
    step = 0.1 if unit in ("킬로그램", "kg") else 1.0
    lo, hi = max(step, round(q * (1 - err) / step) * step), max(step, round(q * (1 + err) / step) * step)
    return _qty(hi, unit) if lo == hi else f"{lo:g}~{hi:g} {unit}"


def reliability_line(ev: dict | None) -> str:
    """과거 검증에서 확인한 정확도 한 줄 (검증 자료가 없으면 빈 문자열)."""
    if not ev:
        return ""
    t = ev["시점"]["엔진"]
    return (f"과거 검증(학습에 쓰지 않은 {ev['검증기간']}) 기준 — 시점: 추천한 품목의 **{t['정밀도'] * 100:.0f}%** 가 실제로 그날 발주됐고 "
            f"실제 발주의 **{t['재현율'] * 100:.0f}%** 를 잡았어요. 수량: 평균 **±{ev['수량']['엔진']:.0f}%** 오차.")


def engine_requests(o: pd.DataFrame):
    """추천 표 → 앱 구매청구 목록. 품목코드로 앱 마스터와 맞추고, 발주단위 수량을 PK 로 환산한다. 마스터에 없는 품목은 따로 돌려준다."""
    by_code = {it.code: it for it in ITEMS.values() if it.code}
    ok, missing = [], []
    for r in o.itertuples():
        it = by_code.get(r.코드)
        if it is None:
            missing.append(r.품목)
            continue
        packs, why = packs_for(r.권장수량, r.단위, r.규격, it.pk_weight_g, it.box_pk, it.base_unit)
        ok.append(dict(item=it.name, packs=packs, want=r.입고예정일, memo=f"이력 기반 발주 추천 · 권장 {r.권장수량:g}{r.단위}" + (f" · {why}" if why else "")))
    return ok, missing


def add_engine_requests(reqs: list):
    """추천을 구매청구로 (이미 '청구' 상태인 품목은 건너뜀)."""
    pending = {r["품목"] for r in ss.purchase_requests if r["상태"] == "청구"}
    made = 0
    for q in reqs:
        if q["item"] not in pending:
            add_request(q["item"], q["packs"], q["want"], q["memo"], toast=False)
            pending.add(q["item"])
            made += 1
    st.toast(f"구매청구 {made}건을 만들었어요 (이미 청구한 {len(reqs) - made}건은 건너뜀).", icon=":material/check_circle:")
    open_req_list()


@register("po.engine")
def po_engine(leaf: Leaf):
    has_data = (reorder_engine.DATA / "2026" / "구매청구_정제.csv").exists()
    if get_store() != sales_data.STORE or not has_data:
        st.info(f"이력 기반 발주 추천은 실제 청구·입고 이력이 있는 '{sales_data.STORE}'에서만 제공합니다.", icon=":material/info:")
        return
    stamp = _engine_stamp()
    e = _engine(stamp)
    ev = reorder_engine.load_eval()
    st.caption("**평소 주문 습관**으로 '무엇을 · 언제 · 얼마나' 발주할지 제안합니다. 재고가 떨어지는 시점 기준으로 보려면 '자동 발주 추천'을 보세요.")
    other_view_link("po-auto", "자동 발주 추천 (재고 기준)")
    c_day, c_state = st.columns([3, 7], vertical_alignment="bottom")
    day = c_day.date_input("기준일 (발주하는 날)", value=get_today(), key="po_engine_day")
    if day > e.data_end + timedelta(days=3):
        st.warning(f"구매청구 자료가 {e.data_end:%Y-%m-%d}까지라, {(day - e.data_end).days}일 뒤 날짜는 최근 주문 이력이 빠져 결과가 부정확합니다. "
                   "구매청구·일자별 매출을 갱신한 뒤 모델을 다시 학습해 주세요 (python reorder_engine.py --fit).", icon=":material/warning:")
    status, why = store_calendar.status(day)
    if status != "영업":
        st.caption(f":material/event: {day:%m/%d} {status}{f' · {why}' if why else ''}")
    t = _engine_table(day, stamp)
    counted = e.latest_count(day)
    n_ref = int(t["재고"].notna().sum())
    if counted is None:
        stock_line, stock_more = "재고 반영 없음 — 월말 실사재고 자료가 없습니다.", ""
    elif (day - counted).days > reorder_engine.STALE_DAYS and n_ref:
        stock_line = f"재고는 실사 대신 시뮬레이션 재고를 참고로 보여 줍니다 ({n_ref}개 품목)"
        stock_more = (f"최근 월말 실사는 {counted:%Y-%m-%d}({(day - counted).days}일 전)라 실사 추정 대신 시뮬레이션 재고를 참고로 보여 줍니다. "
                      "발주할 시점 판단에는 쓰지 않고 '재고 넉넉' 주의와 '재고 확인' 품목의 근거에만 씁니다 (시뮬레이션 재고로 판정하면 맞은 비율이 낮아서).")
    elif (day - counted).days > reorder_engine.STALE_DAYS:
        stock_line = f"재고 추정은 쓰지 않았어요 (최근 월말 실사 {counted:%Y-%m-%d}, {(day - counted).days}일 전)"
        stock_more = f"실사 후 {reorder_engine.STALE_DAYS}일 안에만 반영합니다. 시뮬레이션 예측이 없는 날짜입니다."
    else:
        stock_line = f"{counted:%Y-%m-%d} 월말 실사 + 그 뒤 입고 − 예상 소비로 재고를 추정했어요 ({n_ref}개 품목)"
        stock_more = ""
    with st.expander(stock_line, icon=":material/inventory_2:"):
        if stock_more:
            st.markdown(stock_more)
        st.markdown("거래처 청구·입고 이력(2024~2026)과 매출 예측으로 '무엇을 · 언제 · 얼마나' 발주할지 제안합니다. "
                    "월말 실사재고(수불부)가 있으면 재고를 추정해 참고로 보여 주고, 주문 간격이 길어 습관으로 판단할 수 없는 품목은 재고로 판단합니다.")
    orders = t[t["상태"] == "발주"].sort_values(["거래처", "확률"], ascending=[True, False])
    n_season, n_check = int((t["상태"] == "시즌 시작 예상").sum()), int((t["상태"] == "재고 확인").sum())
    with c_state:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge(f"발주 추천 {len(orders)}건", color="blue" if len(orders) else "gray")
            st.badge(f"거래처 {orders['거래처'].nunique()}곳", color="gray")
            st.badge(f"시즌 시작 예상 {n_season}건", color="gray")
            st.badge(f"재고 확인 필요 {n_check}건", color="orange" if n_check else "gray")

    st.subheader(f"오늘 발주 추천 ({len(orders)}건)")
    if reliability_line(ev):
        st.caption(f":material/verified: {reliability_line(ev)}")
    if orders.empty:
        n_day, n_wait = int((t["상태"].isin(["발주", "보류", "재고 확인"])).sum()), int((t["상태"] == "보류").sum())
        if n_day == 0:
            st.success(f"{day:%m/%d}은 거래처 발주 요일이 아니거나 휴점이라 발주할 품목이 없습니다.", icon=":material/check_circle:")
        else:
            st.success(f"{day:%m/%d} 발주 가능한 정기 품목 {n_day}개 중 지금 발주할 시점인 품목은 없습니다 ({n_wait}개는 아직 이른 상태).", icon=":material/check_circle:")
    else:
        c_pick, c_bulk = st.columns([7, 3], vertical_alignment="center")
        pick = c_pick.multiselect("거래처", sorted(orders["거래처"].unique()), default=sorted(orders["거래처"].unique()), key="po_engine_sup", label_visibility="collapsed")
        o = orders[orders["거래처"].isin(pick)]
        reqs, missing = engine_requests(o)
        by_code = {it.code: it.name for it in ITEMS.values() if it.code}
        pk = {r["item"]: r["packs"] for r in reqs}
        df = pd.DataFrame({
            "거래처": o["거래처"], "품목": o["품목"], "규격": o["규격"],
            "권장 수량": [_qty(q, u) for q, u in zip(o["권장수량"], o["단위"])],
            "예상 범위": [qty_range(q, u, ev["수량"]["엔진"] / 100) if ev else "" for q, u in zip(o["권장수량"], o["단위"])],
            "상한": [_qty(q, u) for q, u in zip(o["상한수량"], o["단위"])],
            "앱 청구 수량": [qty_for(by_code[c], pk[by_code[c]]) if c in by_code else "마스터 미등록" for c in o["코드"]],
            "입고 예정": [fmt_date(d) for d in o["입고예정일"]], "직전 발주": o["직전발주"],
            "예상 재고": [_qty(round(r, 1), u) if pd.notna(r) else "" for r, u in zip(o["재고"], o["단위"])], "재고 주의": o["재고주의"],
            "발주 확률": (o["확률"] * 100).round(), "시즌": o["시즌"], "근거": o["사유"]})
        view_cols = [c for c in df.columns if c not in ("거래처", "근거", "상한")]      # 상한은 예상 범위로 대신 보여 주고 내려받기 CSV 에만 둔다
        c_bulk.button(f"구매청구 만들기 ({len(reqs)}건)", icon=":material/add_shopping_cart:", type="primary", width="stretch", on_click=add_engine_requests, args=(reqs,), disabled=not reqs,
                      help="선택한 모든 거래처의 추천을 한 번에 구매청구로 만듭니다. 이미 청구한 품목은 건너뜁니다. 업체별로 만들려면 아래 각 거래처의 버튼을 누르세요.")
        cols = {"발주 확률": st.column_config.ProgressColumn("발주 확률", min_value=0, max_value=100, format="%d%%",
                                                          help="이 품목을 오늘 발주할 가능성. 평소 주문 주기와 마지막 주문 후 경과일로 계산"),
                "예상 범위": st.column_config.TextColumn(help="권장 수량에 과거 검증 평균 오차를 적용한 범위예요. 품목마다 오차는 다를 수 있어, 실제 주문량이 이 안에 들어올 가능성이 높다는 뜻의 참고값입니다."),
                "상한": st.column_config.TextColumn(help="평소보다 많이 팔릴 때를 대비한 여유 수량(25% 더)")}
        for sup_name, g in o.groupby("거래처", sort=True):
            sub, _miss = engine_requests(g)
            arrive = sorted({d for d in g["입고예정일"]})
            with st.container(border=True):
                h, b = st.columns([4, 1], vertical_alignment="center")
                h.markdown(f"**{sup_name}** · {len(g)}개 품목 · 입고 예정 {', '.join(fmt_date(d) for d in arrive)}")
                b.button(f"{sup_name} 청구 ({len(sub)}건)", key=f"po_engine_req_{sup_name}", icon=":material/add_shopping_cart:", width="stretch",
                         on_click=add_engine_requests, args=(sub,), disabled=not sub, help=f"{sup_name} 추천만 구매청구로 만듭니다. 이미 청구한 품목은 건너뜁니다.")
                gd = df[df["거래처"] == sup_name]
                st.dataframe(gd[view_cols], hide_index=True, width="stretch", alt=f"{sup_name} 발주 추천", column_config=cols)
                with st.expander("근거 보기", expanded=len(gd) <= 3):
                    st.markdown("\n".join(f"- **{n}**: {w}" for n, w in zip(gd["품목"], gd["근거"])))
        if missing:
            st.caption(f":material/info: 앱 품목 마스터에 없어 구매청구를 만들 수 없는 품목 {len(missing)}건: {', '.join(missing)}")
        st.download_button("발주 추천 내려받기 (CSV)", df.to_csv(index=False).encode("utf-8-sig"), file_name=f"발주추천_{day:%Y%m%d}.csv", mime="text/csv",
                           icon=":material/download:")

    plan = stock_sim.sim_order_plan(day)
    if plan is not None and len(plan):
        with st.expander(f"앞으로 2주 발주 예정 ({len(plan)}건) — 시뮬레이션 예측", icon=":material/event_upcoming:"):
            st.caption("재고·입고 시뮬레이션이 예측한 입고에서 거꾸로 계산한 발주일입니다(업체 발주 요일·리드타임·휴점 반영). 과거 검증에서 예측한 발주의 81%가 "
                       "실제 발주일과 ±1일 안에 맞았고(같은 날 66%), 실제 발주의 72%를 잡았습니다. 날짜는 하루쯤 어긋날 수 있어요. 구매청구 이력이 있는 품목만 나옵니다.")
            by_day = plan.groupby("발주일").agg(건수=("품목코드", "size"), 거래처=("거래처", lambda s: ", ".join(sorted(set(s))))).reset_index()
            by_day["발주일"] = [fmt_date(d) for d in by_day["발주일"]]
            st.dataframe(by_day, hide_index=True, width="stretch", alt="날짜별 발주 예정 건수")
            show = plan.assign(발주일=[fmt_date(d) for d in plan["발주일"]], 입고예정=[fmt_date(d) for d in plan["입고예정일"]],
                               수량=[_qty(round(q, 1), u) for q, u in zip(plan["수량_발주단위"], plan["발주단위"])])
            st.dataframe(show[["발주일", "거래처", "품명", "규격", "수량", "입고예정"]], hide_index=True, width="stretch", alt="품목별 발주 예정")
    with st.expander(f"시즌 시작 예상 ({n_season}건) — 작년 이맘때 주문했던 시즌 품목"):
        x = t[t["상태"] == "시즌 시작 예상"][["거래처", "품목", "규격", "직전발주", "사유"]]
        st.caption("계절 메뉴 때문에 특정 시기에만 주문하는 품목입니다. 시즌 메뉴가 시작되면 발주 추천에 자동으로 나타나요. 집기·소모품도 함께 표시될 수 있습니다.")
        if len(x):
            st.dataframe(x, hide_index=True, width="stretch", alt="시즌 시작 예상 품목")
        else:
            st.caption("해당 품목이 없습니다.")
    with st.expander(f"재고 확인 필요 ({n_check}건) — 주문 간격이 길어 재고 없이는 판단할 수 없는 품목"):
        x = t[t["상태"] == "재고 확인"][["거래처", "품목", "규격", "권장수량", "단위", "직전발주", "사유"]]
        if len(x):
            st.dataframe(x, hide_index=True, width="stretch", alt="재고 확인 필요 품목")
        else:
            st.caption("해당 품목이 없습니다.")
    with st.expander("이 추천은 어떻게 만들어지나요?"):
        ev = reorder_engine.load_eval()
        st.markdown(
            "- **언제**: 품목마다 '평소 주문 주기'와 '마지막 주문 후 경과일', 요일 습관으로 오늘 주문할 확률을 계산합니다. 확률이 기준 이상이고 거래처 발주 요일·영업일이면 추천합니다.\n"
            "- **얼마나**: 그 품목의 평소 주문량(최근 4회 중앙값)을 기준으로, 앞으로 매출 예측이 평소보다 낮으면 조금 줄이고 높으면 조금 늘립니다.\n"
            "- **시즌 품목**: 최근 1년 중 주문이 없던 달이 4개월 이상이면 시즌 품목으로 보고, 비수기에는 추천하지 않습니다.\n"
            "- **입고 예정일**: 거래처별 실제 리드타임(요일별)과 매장 휴점일을 반영합니다.")
        if ev:
            t_ = ev["시점"]
            st.markdown(f"**검증 결과** (학습 {ev['학습기간']} → 학습에 쓰지 않은 {ev['검증기간']}, {ev['판단건수']:,}건)\n\n"
                        f"- 발주 시점 정확도(F1): **{t_['엔진']['F1'] * 100:.0f}%** (단순 규칙 {t_['간격규칙']['F1'] * 100:.0f}%) — 추천한 것 중 {t_['엔진']['정밀도'] * 100:.0f}%가 실제 발주, 실제 발주의 {t_['엔진']['재현율'] * 100:.0f}%를 포착\n"
                        f"- 발주 수량 오차: **{ev['수량']['엔진']:.0f}%** (평소 주문량 그대로 {ev['수량']['직전4회']:.0f}%)")
        st.caption(f"학습 자료 {e.last:%Y-%m-%d}까지 · 수량은 '1팩·2팩' 같은 주문 단위라 오차를 크게 줄이기 어렵습니다. 월말 실사재고를 더해 봐도 발주 시점 정확도는 오르지 않았고(2026 검증), 재고는 주문 간격이 긴 품목의 판단과 '재고 넉넉' 주의에 씁니다.")


# ---------------- 입고관리 ----------------
def add_receipt(day: date, supplier: str, item: str, packs: float, kind: str, memo: str = "", po_no: str = ""):
    ss.receipts = [*ss.receipts, {"입고번호": f"RC-{len(ss.receipts) + 1:04d}", "입고일": day, "거래처": supplier, "품목": item, "수량(PK)": packs, "구분": kind,
                                  "발주번호": po_no, "비고": memo}]
    add_stock(item, packs)


SHORT_REASONS = ["거래처 수량 부족", "오배송", "파손·반품", "기타"]
WAIT_REST, CLOSE_REST = "남은 수량은 나중에 입고 (발주서는 계속 입고 대기)", "남은 수량은 더 안 받음 (발주서를 부분 입고로 마감)"


def po_received(po: dict) -> float:
    return round(po.get("입고수량(PK)", 0.0), 2)


RT_WAIT, RT_DONE, RT_CANCEL = "회수대기", "회수완료", "취소"
RETURN_REASONS = ["초과입고", "품질 불량", "오배송", "유통기한", "기타"]


def _returns() -> list:
    return ss.get("returns") or []


def returned_of(key: str, value: str, *, states=(RT_WAIT, RT_DONE)) -> float:
    """입고 건(입고번호) 또는 발주서(발주번호)에 대해 이미 반품 등록한 수량(PK). 취소한 반품은 뺀다."""
    return round(sum(r["수량(PK)"] for r in _returns() if r.get(key) == value and r["상태"] in states), 2)


def po_over(po: dict) -> float:
    return round(max(po_received(po) - po["수량(PK)"], 0.0), 2)


def po_over_left(po: dict) -> float:
    """초과 입고분 중 아직 반품 등록을 하지 않은 수량."""
    return round(max(po_over(po) - returned_of("발주번호", po["발주번호"]), 0.0), 2)


def po_tone(po: dict) -> str:
    """입고 수량이 발주와 다른 정도: 'short'(덜 들어옴·남음) / 'over'(초과) / ''(정상·반품 정리됨)."""
    got, ordered = po_received(po), po["수량(PK)"]
    if po["상태"] == "부분입고" or (po["상태"] == "입고대기" and got > 0):
        return "short"
    if got > ordered:
        return "over" if returned_of("발주번호", po["발주번호"], states=(RT_DONE,)) < po_over(po) else ""
    return ""


TONE_CSS = {"short": f"color: {DANGER}; font-weight: 700", "over": f"color: {WARN}; font-weight: 700"}


def tone_html(text: str, tone: str) -> str:
    return f'<span style="{TONE_CSS[tone]}">{text}</span>' if tone else text


def po_gap_label(po: dict) -> str:
    """입고수량 옆에 보여 줄 차이 문구 (정상이면 빈 칸)."""
    tone, item, got, ordered = po_tone(po), po["품목"], po_received(po), po["수량(PK)"]
    if got > ordered:
        over, done, wait = po_over(po), returned_of("발주번호", po["발주번호"], states=(RT_DONE,)), returned_of("발주번호", po["발주번호"], states=(RT_WAIT,))
        base = f"초과 {qty_for(item, over)}"
        if done >= over:
            return base + " → 반품 회수 완료"
        return base + (f" · 반품 회수 대기 {qty_for(item, wait)}" if wait else " · 반품 필요")
    if tone == "short":
        return ("남음 " if po["상태"] == "입고대기" else "부족 ") + qty_for(item, po_remaining(po))
    return ""


def po_remaining(po: dict) -> float:
    return round(max(po["수량(PK)"] - po_received(po), 0.0), 2)


def receive_po(po_no: str, actual: float, rest: str | None, reason: str, memo: str) -> str:
    """실제 들어온 수량(PK)만큼 입고 처리한다. 모자라면 rest 선택에 따라 발주서를 계속 대기시키거나 부분 입고로 마감한다. 처리 결과 문구를 돌려준다."""
    for po in ss.purchase_orders:
        if po["발주번호"] == po_no and po["상태"] == "입고대기":
            remain, item = po_remaining(po), po["품목"]
            note = f"{po_no} · 발주 {qty_for(item, po['수량(PK)'])} 중 {qty_for(item, actual)} 입고"
            if actual < remain:
                note += f" · 부족 {qty_for(item, round(remain - actual, 2))} ({reason}" + (f", {memo}" if memo else "") + ")"
            elif actual > remain:
                note += f" · 초과 {qty_for(item, round(actual - remain, 2))}" + (f" ({memo})" if memo else "")
            elif memo:
                note += f" · {memo}"
            po["입고수량(PK)"] = round(po_received(po) + actual, 2)
            add_receipt(get_today(), po["거래처"], item, actual, "구매발주서", note, po_no)
            if actual >= remain:
                po["상태"] = "입고완료"
                return f"{po_no} 입고 완료 — 재고에 {qty_for(item, actual)} 반영했어요."
            if rest == CLOSE_REST:
                po["상태"] = "부분입고"
                return f"{po_no} 부분 입고로 마감 — 재고에 {qty_for(item, actual)} 반영했고, 부족 {qty_for(item, round(remain - actual, 2))}는 더 받지 않아요."
            return f"{po_no} 일부 입고 — 재고에 {qty_for(item, actual)} 반영했고, 남은 {qty_for(item, po_remaining(po))}는 계속 입고 대기예요."
    return f"{po_no}은(는) 이미 처리된 발주서예요."


@st.dialog("입고 처리", width="medium")
def receive_dialog(po_no: str):
    """실제로 들어온 수량을 입력받는다. 발주와 다르면(모자람·초과) 어떻게 처리할지 함께 정한다."""
    po = next((x for x in ss.purchase_orders if x["발주번호"] == po_no and x["상태"] == "입고대기"), None)
    if po is None:
        st.caption("이미 처리된 발주서예요.")
        return
    item, remain = po["품목"], po_remaining(po)
    it, got = ITEMS[item], po_received(po)
    st.markdown(f"**{po_no}** · {item} · {po['거래처']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("발주", qty_for(item, po["수량(PK)"]), border=True)
    c2.metric("이미 입고", qty_for(item, got), border=True)
    c3.metric("입고 남음", qty_for(item, remain), border=True)
    per = units_of(it).per
    st.markdown("**실제로 들어온 수량**")
    actual = qty_input("", it, key=f"rc_qty_{po_no}_{remain}", min_value=0.0, default=remain / per)
    rest, reason, memo = None, "", ""
    if actual <= 0:
        st.caption("들어온 수량을 입력하세요. 아무것도 안 들어왔다면 입고 처리를 하지 않고 발주서를 그대로 두세요.")
    elif actual < remain:
        short = round(remain - actual, 2)
        st.warning(f"발주보다 **{qty_for(item, short)}** 적게 들어왔어요.", icon=":material/warning:")
        rest = st.radio("남은 수량은?", [WAIT_REST, CLOSE_REST], key=f"rc_rest_{po_no}")
        reason = st.selectbox("부족 사유", SHORT_REASONS, key=f"rc_why_{po_no}")
    elif actual > remain:
        st.warning(f"발주보다 **{qty_for(item, round(actual - remain, 2))}** 더 들어왔어요. 들어온 수량만큼 재고에 반영하고 발주서는 입고 완료로 닫아요.", icon=":material/warning:")
    memo = st.text_input("메모", placeholder="선택 (예: 기사님 확인, 거래처 연락)", key=f"rc_memo_{po_no}")
    ok, no = st.columns(2)
    if ok.button("입고 처리", type="primary", icon=":material/check:", width="stretch", disabled=actual <= 0, key=f"rc_ok_{po_no}"):
        ss.rc_done = receive_po(po_no, actual, rest, reason, memo)
        st.rerun()
    if no.button("취소", width="stretch", key=f"rc_no_{po_no}"):
        st.rerun()


@register("recv.by_po")
def recv_by_po(leaf: Leaf):
    if ss.get("rc_done"):
        st.success(ss.pop("rc_done"), icon=":material/check_circle:")
    pos = ss.purchase_orders
    pending = [p for p in pos if p["상태"] == "입고대기"]
    kpis([("입고 대기", f"{len(pending)}건", None),
          ("입고 완료", f"{sum(p['상태'] == '입고완료' for p in pos)}건", None),
          ("부분 입고 마감", f"{sum(p['상태'] == '부분입고' for p in pos)}건", None)])
    st.subheader("입고 대기 발주서")
    st.caption("들어온 수량이 발주와 다르면 '입고 처리' 창에서 실제 수량을 입력하세요. 모자란 만큼은 계속 기다리거나 부분 입고로 마감할 수 있어요.")
    if not pending:
        st.caption("입고 대기 중인 발주서가 없어요.")
    for p in pending:
        with st.container(border=True):
            left, right = st.columns([5, 1], vertical_alignment="center")
            got = po_received(p)
            left.markdown(f"**{p['발주번호']}** · {p['품목']} {qty_for(p['품목'], p['수량(PK)'])} · {p['거래처']} · 입고예정 {fmt_date(p['입고예정'])}"
                          + (" · " + tone_html(f"일부 입고 {qty_for(p['품목'], got)} · {po_gap_label(p)}", "short") if got else ""), unsafe_allow_html=True)
            right.button("입고 처리", key=f"rc_{p['발주번호']}", type="primary", on_click=receive_dialog, args=(p["발주번호"],))
    over = [p for p in pos if po_over_left(p) > 0]
    if over:
        st.subheader(f"초과 입고 — 반품 필요 ({len(over)}건)")
        for p in over:
            with st.container(border=True):
                left, right = st.columns([5, 2], vertical_alignment="center")
                left.markdown(f"**{p['발주번호']}** · {p['품목']} · {p['거래처']} · 발주 {qty_for(p['품목'], p['수량(PK)'])} → 입고 {qty_for(p['품목'], po_received(p))} · "
                              + tone_html(f"초과 {qty_for(p['품목'], po_over_left(p))}", "over"), unsafe_allow_html=True)
                right.button("초과분 반품 등록", key=f"ov_{p['발주번호']}", icon=":material/assignment_return:", width="stretch", on_click=over_return_dialog, args=(p["발주번호"],))
    st.subheader("전체 발주서")
    if pos:
        st.caption(":red[빨강] 발주보다 덜 들어옴(남음·부족) · :orange[주황] 발주보다 더 들어옴(초과)")
        df = pk_df(pd.DataFrame(pos).drop(columns=["입고수량(PK)"], errors="ignore"))
        df["입고수량"] = [qty_for(p["품목"], po_received(p)) for p in pos]
        df["차이"] = [po_gap_label(p) for p in pos]
        tones = [po_tone(p) for p in pos]
        css = pd.DataFrame("", index=df.index, columns=df.columns)
        for c in ("입고수량", "차이"):
            css[c] = [TONE_CSS.get(x, "") for x in tones]
        css["상태"] = [TONE_CSS["short"] if p["상태"] == "부분입고" else "" for p in pos]
        st.dataframe(df.style.apply(lambda _: css, axis=None), hide_index=True, width="stretch", alt="발주서 목록")
    else:
        st.caption("발주서가 없어요. 구매청구에서 발주로 전환하면 여기에 나와요.")


@register("recv.general")
def recv_general(leaf: Leaf):
    st.caption("발주서 없이 들어온 물품을 입고 처리합니다. 입고하면 재고에 반영돼요.")
    s1, s2 = st.columns([2, 3], vertical_alignment="bottom")
    sup = s1.selectbox("거래처", list(SUPPLIERS))
    gq = s2.text_input("품목 검색", placeholder="품목명 · 품목코드 · 규격", key="gr_q", icon=":material/search:").strip().lower()
    names = [n for n, i in ITEMS.items() if i.supplier.name == sup] or list(ITEMS)
    names = [n for n in names if not gq or gq in f"{n} {ITEMS[n].code} {ITEMS[n].spec}".lower()]
    if not names:
        st.caption("조건에 맞는 품목이 없어요. 거래처나 검색어를 바꿔 보세요.")
        return
    with st.container(border=True):
        c1, c2 = st.columns(2)
        item = c1.selectbox("품목", names)
        packs = qty_input("수량", ITEMS[item], key=f"gr_qty_{item}", container=c2)
        memo = st.text_input("비고", placeholder="선택")
        if st.button("입고 등록", type="primary", icon=":material/move_to_inbox:"):
            add_receipt(get_today(), sup, item, packs, "일반입고", memo)
            st.toast(f"{item} {qty_for(item, packs)} 입고 완료", icon=":material/check_circle:")


@register("recv.detail")
def recv_detail(leaf: Leaf):
    df = pd.DataFrame(ss.receipts)
    kpis([("입고 건수", f"{len(df)}건", None), ("입고 품목", f"{df['품목'].nunique() if len(df) else 0}개", None)])
    if df.empty:
        st.caption("입고 내역이 없어요.")
        return
    kind = st.segmented_control("구분", ["전체", "구매발주서", "일반입고"], default="전체", key="recv_kind") or "전체"
    view = pk_df(df if kind == "전체" else df[df["구분"] == kind])
    css = pd.DataFrame("", index=view.index, columns=view.columns)
    css["비고"] = ["" if not isinstance(n, str) else TONE_CSS["short"] if "부족" in n else TONE_CSS["over"] if "초과" in n else "" for n in view["비고"]]
    st.dataframe(view.style.apply(lambda _: css, axis=None), hide_index=True, width="stretch", alt="입고 상세내역")


def create_return(receipt_no: str, packs: float, reason: str, memo: str = "", po_no: str = "") -> str | None:
    """반품을 '회수 대기'로 등록한다 (재고는 회수 완료 때 차감). 등록할 수 없으면 이유를 돌려준다."""
    rc = next((r for r in ss.receipts if r.get("입고번호") == receipt_no), None)
    if rc is None:
        return "입고 건을 찾을 수 없어요."
    if packs <= 0:
        return "반품 수량을 입력하세요."
    left = round(rc["수량(PK)"] - returned_of("입고번호", receipt_no), 2)
    if packs > left:
        return f"이 입고 건에서 더 반품할 수 있는 수량은 {qty_for(rc['품목'], left)}예요 (입고 {qty_for(rc['품목'], rc['수량(PK)'])}, 이미 반품 등록 {qty_for(rc['품목'], round(rc['수량(PK)'] - left, 2))})."
    ss.returns = [*_returns(), {"반품번호": f"RT-{len(_returns()) + 1:04d}", "반품일": get_today(), "거래처": rc["거래처"], "품목": rc["품목"], "수량(PK)": packs,
                               "사유": reason, "상태": RT_WAIT, "입고번호": receipt_no, "발주번호": po_no or rc.get("발주번호", ""), "회수일": None, "메모": memo}]
    return None


def complete_return(no: str):
    """거래처가 물건을 회수해 갔을 때: 이때 재고에서 차감한다."""
    for r in _returns():
        if r["반품번호"] == no and r["상태"] == RT_WAIT:
            r["상태"], r["회수일"] = RT_DONE, get_today()
            add_stock(r["품목"], -r["수량(PK)"])
            st.toast(f"{no} 회수 완료 — 재고에서 {qty_for(r['품목'], r['수량(PK)'])} 차감했어요.", icon=":material/check_circle:")
            return


def cancel_return(no: str):
    for r in _returns():
        if r["반품번호"] == no and r["상태"] == RT_WAIT:
            r["상태"] = RT_CANCEL
            st.toast(f"{no} 반품을 취소했어요. 재고는 그대로예요.", icon=":material/undo:")
            return


@st.dialog("초과 입고분 반품", width="medium")
def over_return_dialog(po_no: str):
    """발주보다 더 들어온 수량을 반품 요청(회수 대기)으로 등록한다. 재고는 회수 완료 때 차감한다."""
    po = next((x for x in ss.purchase_orders if x["발주번호"] == po_no), None)
    rc = next((r for r in reversed(ss.receipts) if r.get("발주번호") == po_no), None)
    if po is None or rc is None or po_over_left(po) <= 0:
        st.caption("반품할 초과 입고분이 없어요.")
        return
    item, left = po["품목"], po_over_left(po)
    st.markdown(f"**{po_no}** · {item} · {po['거래처']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("발주", qty_for(item, po["수량(PK)"]), border=True)
    c2.metric("실제 입고", qty_for(item, po_received(po)), border=True)
    c3.metric("초과(반품 대상)", qty_for(item, left), border=True)
    st.markdown("**반품할 수량**")
    packs = qty_input("", ITEMS[item], key=f"ov_qty_{po_no}_{left}", default=left / units_of(ITEMS[item]).per)
    too_many = packs > left
    if too_many:
        st.error(f"초과분({qty_for(item, left)})보다 많이 반품할 수 없어요.")
    memo = st.text_input("메모", placeholder="선택 (예: 기사님께 회수 요청)", key=f"ov_memo_{po_no}")
    st.caption("등록하면 '회수 대기'가 돼요. 재고는 거래처가 실제로 회수해 간 뒤 '반품' 화면에서 '회수 완료'를 눌러야 줄어요.")
    ok, no = st.columns(2)
    if ok.button("반품 등록 (회수 대기)", type="primary", icon=":material/assignment_return:", width="stretch", disabled=too_many, key=f"ov_ok_{po_no}"):
        err = create_return(rc["입고번호"], packs, "초과입고", memo, po_no)
        ss.rc_done = err or f"{po_no} 초과분 {qty_for(item, packs)} 반품을 등록했어요 (회수 대기)."
        st.rerun()
    if no.button("취소", width="stretch", key=f"ov_no_{po_no}"):
        st.rerun()


@register("recv.returns")
def recv_returns(leaf: Leaf):
    rts = _returns()
    kpis([("회수 대기", f"{sum(r['상태'] == RT_WAIT for r in rts)}건", None), ("회수 완료", f"{sum(r['상태'] == RT_DONE for r in rts)}건", None)])
    st.caption("반품을 등록하면 '회수 대기'가 되고 재고는 그대로예요. 거래처가 물건을 회수해 간 뒤 '회수 완료'를 눌러야 재고에서 빠져요. 초과 입고는 구매발주서 기준 화면에서도 바로 등록할 수 있어요.")
    receipts = [r for r in ss.receipts if r.get("입고번호") and round(r["수량(PK)"] - returned_of("입고번호", r["입고번호"]), 2) > 0]
    st.subheader("반품 등록")
    if not receipts:
        st.caption("반품할 입고 내역이 없어요.")
    else:
        with st.container(border=True):
            pool = {it.name for it in item_filter("rt", [ITEMS[n] for n in dict.fromkeys(r["품목"] for r in receipts)])}
            shown = [r for r in receipts if r["품목"] in pool]
            if shown:
                idx = st.selectbox("입고 건", range(len(shown)), format_func=lambda i: (
                    f"{shown[i]['입고번호']} · {shown[i]['입고일']} · {shown[i]['품목']} {qty_for(shown[i]['품목'], shown[i]['수량(PK)'])} ({shown[i]['거래처']})"
                    f" · 반품 가능 {qty_for(shown[i]['품목'], round(shown[i]['수량(PK)'] - returned_of('입고번호', shown[i]['입고번호']), 2))}"))
                r = shown[idx]
                c1, c2 = st.columns(2)
                packs = qty_input("반품 수량", ITEMS[r["품목"]], key=f"rt_qty_{r['입고번호']}", container=c1)
                reason = c2.selectbox("사유", RETURN_REASONS, index=1)
                memo = st.text_input("메모", placeholder="선택", key="rt_memo")
                if st.button("반품 등록 (회수 대기)", type="primary", icon=":material/assignment_return:"):
                    err = create_return(r["입고번호"], packs, reason, memo)
                    if err:
                        st.error(err)
                    else:
                        st.toast("반품을 등록했어요. 회수가 끝나면 '회수 완료'를 눌러 주세요.", icon=":material/check_circle:")
                        st.rerun()
    waiting = [r for r in rts if r["상태"] == RT_WAIT]
    st.subheader(f"회수 대기 ({len(waiting)}건)")
    if not waiting:
        st.caption("회수를 기다리는 반품이 없어요.")
    for r in reversed(waiting):
        with st.container(border=True):
            left, a1, a2 = st.columns([5, 2, 1], vertical_alignment="center")
            left.markdown(f"**{r['반품번호']}** · {r['품목']} {qty_for(r['품목'], r['수량(PK)'])} · {r['거래처']} · {r['사유']}"
                          + (f" · {r['발주번호']}" if r.get("발주번호") else "") + (f" · {r['메모']}" if r.get("메모") else ""))
            a1.button(f"회수 완료 (재고 -{qty_for(r['품목'], r['수량(PK)'])})", key=f"rtdone_{r['반품번호']}", type="primary", on_click=complete_return, args=(r["반품번호"],), width="stretch")
            a2.button("취소", key=f"rtcancel_{r['반품번호']}", on_click=cancel_return, args=(r["반품번호"],), width="stretch")
    st.subheader("반품 내역")
    if rts:
        df = pk_df(pd.DataFrame(rts))
        css = pd.DataFrame("", index=df.index, columns=df.columns)
        css["상태"] = [TONE_CSS["over"] if s == RT_WAIT else "color: #566071" if s == RT_CANCEL else "" for s in df["상태"]]
        st.dataframe(df.style.apply(lambda _: css, axis=None), hide_index=True, width="stretch", alt="반품 내역")
    else:
        st.caption("반품 내역이 없어요.")


# ---------------- 기타입출고 ----------------
@register("io.loss")
def io_loss(leaf: Leaf):
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        item = c1.selectbox("품목", list(ITEMS), format_func=item_label)
        packs = qty_input("수량", ITEMS[item], key=f"ls_qty_{item}", min_value=0.0, container=c2)
        reason = c3.selectbox("사유", ["폐기", "파손", "유통기한", "시식·샘플", "기타"])
        if st.button("손망실 등록", type="primary", icon=":material/delete_forever:"):
            if packs <= 0:
                st.error("수량은 0보다 커야 해요.")
            else:
                ss.losses = [*ss.losses, {"일자": get_today(), "품목": item, "수량(PK)": packs, "사유": reason}]
                add_stock(item, -packs)
                st.toast("손망실을 등록했고 재고에서 차감했어요.", icon=":material/check_circle:")
    df = pd.DataFrame(ss.losses)
    if df.empty:
        st.caption("등록된 손망실이 없어요.")
        return
    kpis([("건수", f"{len(df)}건", None), ("품목", f"{df['품목'].nunique()}개", None)])
    axis_chart("bar", df.groupby("사유").size().rename("건수"), alt_text="사유별 손망실 건수")
    st.dataframe(pk_df(df), hide_index=True, width="stretch", alt="손망실 상세내역")


@register("io.transfer_request")
def io_transfer_request(leaf: Leaf):
    me = get_store()
    st.caption(f"'{me}'에서 다른 매장으로 물품 이체를 요청합니다.")
    if not [x for x in STORES if x != me]:
        st.info("이체할 다른 매장이 등록되어 있지 않아요. 매장이 추가되면 이 화면에서 요청할 수 있어요.", icon=":material/database_off:")
        return
    with st.container(border=True):
        pool = item_filter("tr", list(ITEMS.values()))
        c1, c2, c3 = st.columns(3)
        to = c1.selectbox("받는 매장", [s for s in STORES if s != me])
        item = c2.selectbox("품목", [it.name for it in pool], format_func=item_label) if pool else None
        if item is None:
            c3.empty()
        packs = qty_input("수량", ITEMS[item], key=f"tr_qty_{item}", container=c3) if item else 0
        memo = st.text_input("메모", placeholder="선택")
        if st.button("이체 요청", type="primary", icon=":material/swap_horiz:", disabled=not item):
            ss.transfer_requests = [*ss.transfer_requests, {
                "번호": f"TR-{len(ss.transfer_requests) + 1:04d}", "요청일": get_today(), "보내는 매장": me, "받는 매장": to,
                "품목": item, "수량(PK)": packs, "메모": memo, "상태": "요청"}]
            st.toast("이체를 요청했어요.", icon=":material/check_circle:")
    for r in ss.transfer_requests:
        if r["상태"] != "요청":
            continue
        with st.container(border=True):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.markdown(f"**{r['번호']}** · {r['보내는 매장']} → {r['받는 매장']} · {r['품목']} {qty_for(r['품목'], r['수량(PK)'])}")
            right.button("승인", key=f"ap_{r['번호']}", on_click=approve_transfer, args=(r["번호"],))


def approve_transfer(no: str):
    for r in ss.transfer_requests:
        if r["번호"] == no and r["상태"] == "요청":
            r["상태"] = "완료"
            ss.transfers = [*ss.transfers, {**r, "이체일": get_today()}]
            st.toast(f"{no} 이체를 승인했어요.", icon=":material/check_circle:")
            return


@register("io.transfer")
def io_transfer(leaf: Leaf):
    if not ss.transfers:
        st.caption("완료된 이체가 없어요. '이체요청'에서 요청하고 승인하면 여기에 표시돼요.")
        return
    st.dataframe(pk_df(pd.DataFrame(ss.transfers)), hide_index=True, width="stretch", alt="이체 상세내역")


# ---------------- 수불관리 ----------------
@register("stock.flow")
def stock_flow(leaf: Leaf):
    today = get_today()
    week_ago = today - timedelta(days=7)
    rows = []
    for it, g, _r in current_results():
        if not it.usage_known:                           # 일 소비량 근거가 없으면 주간 출고를 계산할 수 없다
            continue
        pk = it.pk_weight_g
        unit, f = display_unit(it)                       # 병·캔이 있으면 낱개, 없으면 품목의 발주단위로 센다
        inn = sum(r["수량(PK)"] for r in ss.receipts if r["품목"] == it.name and r["입고일"] > week_ago)
        out = it.daily_usage_g * 7 / pk
        loss = sum(r["수량(PK)"] for r in ss.losses if r["품목"] == it.name and r["일자"] > week_ago)
        ret = sum(r["수량(PK)"] for r in _returns() if r["품목"] == it.name and r["상태"] == RT_DONE and r["회수일"] > week_ago)       # 재고에서 실제로 빠진 것만
        end = g / pk
        rows.append({"품목": it.name, "단위": unit, "기초": round((end - inn + out + loss + ret) * f, 1), "입고": round(inn * f, 1),
                     "소비": round(out * f, 1), "손망실": round(loss * f, 1), "반품": round(ret * f, 1), "기말": round(end * f, 1)})
    st.caption("최근 7일 수불: 기초 + 입고 − 소비 − 손망실 − 반품 = 기말 (소비는 일 소비량 기준 추정). 수량은 품목의 단위(병·박스·팩·개 등)로 보여줘요.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", alt="최근 7일 수불현황")


CATEGORY_ORDER = {"원재료": 0, "반제품": 1, "포장재료": 2, "저장품": 3}   # 입력 표의 분류 순서: 먼저 세는 것부터
ENTRY_COLUMNS = ["품목", "BOX", "PK", "낱개", "합계", "확인", "환산 기준"]
ENTRY_CONFIG = {
    "품목": st.column_config.TextColumn("품목", width=150, pinned=True),
    "BOX": st.column_config.NumberColumn("BOX", min_value=0, format="%g", width="small", help="박스 수"),
    "PK": st.column_config.NumberColumn("PK", min_value=0, format="%g", width="small", help="팩 수 (소수로 입력해도 돼요)"),
    "낱개": st.column_config.NumberColumn("낱개", min_value=0, format="%g", width="small",
                                        help="PK로 채우지 못한 낱개. 품목의 기본단위(g·ml·개 등)로 입력하세요 — 맨 오른쪽 '환산 기준'에 적혀 있어요."),
    "합계": st.column_config.TextColumn("합계", width="medium", help="BOX·PK·낱개를 합친 환산 결과. 입력하면 바로 바뀌어요."),
    "확인": st.column_config.TextColumn("확인", width="medium", help="추정값 그대로인지, 직접 입력했는지, 이상한 값인지 알려 줘요. 0으로 입력했거나, 추정의 3배 이상·1/3 이하이거나, 소비 60일치를 넘으면 '확인 필요'."),
    "환산 기준": st.column_config.TextColumn("환산 기준", width="medium", help="이 품목의 1PK·1BOX가 얼마인지, 낱개를 무슨 단위로 세는지"),
}


def convert_basis(it) -> str:
    """환산 기준 한 줄: '1PK=20kg · 1BOX=4PK · 낱개=g'. 낱개 수로 세는 품목(1PK=1개)은 '낱개=개'만."""
    if it.base_unit not in ("g", "ml") and it.pk_weight_g == 1 and it.box_pk == 1:
        return f"낱개={it.base_unit}"
    return f"1PK={it.fmt(it.pk_weight_g)}" + (f" · 1BOX={it.box_pk:g}PK" if it.box_pk > 1 else "") + f" · 낱개={it.base_unit}"


CHECK_RATIO = 3   # 입력이 추정값의 이 배수 이상이거나 1/이 배수 이하이면 확인 필요
CHECK_DAYS = 60   # 입력이 하루 소비량의 이 일수치를 넘으면 확인 필요 (자릿수 실수: 20 대신 200)
CHECK_BIG = {"g": 500_000, "ml": 500_000}   # 소비량을 몰라도 매장 한 품목이 이 양(500kg·500L, 개수는 5만 개)을 넘을 수는 없다
CHECK_BIG_COUNT = 50_000


def entry_check(it, now, base) -> str:
    """입력 행의 확인 문구. now·base = (BOX, PK, 낱개): base 는 화면을 열 때의 추정값. 확인이 필요한 행은 '확인 필요'로 시작한다.
    같으면 '추정값', 직접 바꿨으면 '입력함', 0으로 입력했거나 소비 60일치를 넘거나 추정과 크게(3배 이상, 1PK 이상 차이) 다르면 '확인 필요 · …'."""
    try:
        g, g0 = to_grams(it, now[1], now[2], boxes=now[0]), to_grams(it, base[1], base[2], boxes=base[0])
    except InvalidInputError:
        return "확인 필요 · 입력 확인"
    if g == g0:
        return "추정값"
    if g == 0:
        return "확인 필요 · 0으로 입력"
    if g > g0 and it.usage_known and it.daily_usage_g > 0 and g > CHECK_DAYS * it.daily_usage_g:
        return f"확인 필요 · 소비 {g / it.daily_usage_g:.0f}일치"
    if g > g0 and g > CHECK_BIG.get(it.base_unit, CHECK_BIG_COUNT):
        return "확인 필요 · 너무 큰 값"
    if g0 > 0 and abs(g - g0) >= it.pk_weight_g:
        if g >= g0 * CHECK_RATIO:
            return f"확인 필요 · 추정의 {g / g0:.0f}배"
        if g * CHECK_RATIO <= g0:
            return f"확인 필요 · 추정의 1/{g0 / g:.0f}"
    return "입력함"


def entry_total(it, box, pk, loose) -> str:
    """입력한 BOX·PK·낱개의 환산 합계: '48.3kg = 2.42팩' (무게·부피 품목) 또는 '24개'. 값이 비었거나 음수면 '입력 확인'."""
    try:
        g = to_grams(it, pk, loose, boxes=box)
    except InvalidInputError:
        return "입력 확인"
    if g == 0:
        return "0"
    return f"{it.fmt(g)} = {stock_of(it, g)}" if it.base_unit in ("g", "ml") else stock_of(it, g)


def status_badges(n: dict, extra: list | None = None):
    """긴급·발주 필요·양호·데이터 없음 배지 한 줄 (n = 상태별 개수). 개수가 0이면 회색. extra = [(문구, 색, 아이콘)]."""
    with st.container(horizontal=True, vertical_alignment="center"):
        for label, count, color in (("긴급", n["URGENT"], "red"), ("발주 필요", n["ORDER_NOW"] + n["ORDER_SOON"], "orange"),
                                    ("양호", n["OK"] + n["NO_USAGE"], "gray"), ("데이터 없음", n["NO_DATA"], "gray")):
            st.badge(f"{label} {count}", color=color if count else "gray")
        for text, color, icon in extra or []:
            st.badge(text, color=color, icon=icon)


def table_signature(table: pd.DataFrame) -> int:
    """입력 표의 내용을 한 숫자로 (저장한 뒤 바뀌었는지 비교)."""
    return int(pd.util.hash_pandas_object(table, index=True).sum())


def stock_editor():
    """실사 재고 입력 화면: 기준 안내 · 필터 · 진행 상태 · 입력 표. (품목, 총 g, 추천) 결과를 반환하고 현재 매장의 stock_g를 갱신."""
    s = inv_state()
    short = stock_note_short()
    with st.expander(short or "입력 방법", icon=":material/info:"):
        if short:
            st.markdown(stock_note())
        st.markdown("**BOX · PK · 낱개**를 직접 고치면 바로 환산돼요. **낱개**는 PK로 채우지 못한 양을 품목의 기본단위(g·ml·개·장·롤 등)로 입력하고, "
                    "BOX·PK 입수는 품목 마스터 기준으로 자동 환산돼요. 표의 '환산 기준' 열에 품목마다 적혀 있어요.")
    table = s["table"]
    c_cat, c_sup, c_q, c_up = st.columns([4, 2, 3, 2], vertical_alignment="center")
    cat = c_cat.pills("분류", ["전체", *dict.fromkeys(table["분류"])], default="전체", key="inv_cat", label_visibility="collapsed") or "전체"
    sup = c_sup.selectbox("업체", [ALL_SUP, *sorted({ITEMS[n].supplier.name for n in table["품목"]})], key="inv_sup", label_visibility="collapsed")
    q = c_q.text_input("품목 검색", placeholder="품목명 또는 코드로 찾기", key="inv_q", icon=":material/search:", label_visibility="collapsed").strip()
    with c_up.popover("파일로 불러오기", icon=":material/upload_file:", width="stretch"):
        up = st.file_uploader("실사 재고 파일 (엑셀 · CSV · JSON · 텍스트)", type=["csv", "tsv", "txt", "md", "json", "xlsx", "xls", "ods"],
                              key=f"inv_up_{get_store()}")
        st.download_button("양식 받기 (CSV)", TEMPLATE_CSV, "실사재고_양식.csv", "text/csv", icon=":material/download:")
        if up is not None:
            try:
                imp = parse_inventory_file(up.name, up.getvalue(), ITEMS)
            except InvalidInputError as e:
                st.error(f"파일 오류: {e}")
            else:
                if imp.errors:
                    st.error(f"오류 {len(imp.errors)}건 — 해당 행은 제외하고 불러왔습니다.")
                    st.dataframe(pd.DataFrame([{"행": x.row, "품목": x.item, "내용": x.message} for x in imp.errors]),
                                 hide_index=True, width="stretch", alt="업로드 오류 목록")
                for w in imp.warnings:
                    st.warning(f"{w.row}행 {w.item}: {w.message}")
                if imp.missing:
                    st.info("파일에 없는 품목은 0으로 표시됩니다: " + ", ".join(imp.missing))
                if s["applied"] != up.file_id:  # 같은 파일을 rerun마다 다시 덮어쓰지 않음 (사용자 수정 보존)
                    s["table"] = build_table(imp.grams)
                    s["ver"] += 1
                    s["applied"] = up.file_id
                    table = s["table"]
                st.success(f"{len(imp.grams)}개 품목을 불러왔습니다. 아래 표에서 수정할 수 있습니다.")
    c_view, c_tg = st.columns([5, 4], vertical_alignment="center")
    which = c_view.segmented_control("보기", ["전체", "아직 안 센 품목", "확인 필요"], default="전체", key="inv_view", label_visibility="collapsed") or "전체"
    with c_tg:
        show_all = dormant_toggle("stock_input_dormant", "활동 없는 품목도 보기")
    codes = active_codes()
    seed = s["seed"][1]                                                # 화면을 열 때의 추정값 (입력과 비교하는 기준)
    checks = {i: entry_check(ITEMS[n], (b, p, l), (seed.at[i, "BOX"], seed.at[i, "PK"], seed.at[i, "낱개"]))
              for i, n, b, p, l in zip(table.index, table["품목"], table["BOX"], table["PK"], table["낱개"])}
    universe = table.index if codes is None or show_all else table.index[table["품목코드"].isin(codes)]    # 진행률의 분모: 화면에 보이는 품목 전체
    mask = pd.Series(True, index=table.index)
    if cat != "전체":
        mask &= table["분류"] == cat
    if sup != ALL_SUP:
        mask &= table["품목"].map(lambda n: ITEMS[n].supplier.name == sup)
    if q:
        mask &= table["품목"].str.contains(q, case=False, regex=False) | table["품목코드"].str.contains(q, case=False, regex=False)    # 검색하면 활동 없는 품목도 찾는다
    elif codes is not None and not show_all:
        mask &= table["품목코드"].isin(codes)
    if which == "아직 안 센 품목":
        mask &= pd.Series([checks[i] == "추정값" for i in table.index], index=table.index)
    elif which == "확인 필요":
        mask &= pd.Series([checks[i].startswith("확인 필요") for i in table.index], index=table.index)
    view = table[mask].sort_values("분류", key=lambda c: c.map(CATEGORY_ORDER).fillna(len(CATEGORY_ORDER)), kind="stable")    # 식재료(원재료·반제품)를 먼저, 집기·소모품은 뒤로
    status = st.container()                                              # 진행·상태·저장 줄: 아래 표와 결과를 계산한 뒤 채운다 (표 위에 놓기 위해)
    shown = view.assign(**{"환산 기준": [convert_basis(ITEMS[n]) for n in view["품목"]],
                           "합계": [entry_total(ITEMS[n], b, p, l) for n, b, p, l in zip(view["품목"], view["BOX"], view["PK"], view["낱개"])],
                           "확인": [checks[i] for i in view.index]})
    edited = st.data_editor(shown, hide_index=True, width="stretch", alt="품목별 실사 재고 입력 표", key=f"inv_editor_{get_store()}_{s['ver']}_{cat}_{sup}_{q}_{which}",
                            disabled=["품목코드", "품목", "분류", "단위", "합계", "확인", "환산 기준"], column_order=ENTRY_COLUMNS, column_config=ENTRY_CONFIG)
    t = table.copy()   # 보이는 행의 수정값만 전체 표에 반영 (필터로 가려진 행은 그대로)
    t.loc[edited.index, ["BOX", "PK", "낱개"]] = edited[["BOX", "PK", "낱개"]]
    s["table"] = t
    if not edited[["BOX", "PK", "낱개"]].fillna(-1).equals(view[["BOX", "PK", "낱개"]].fillna(-1)):
        st.rerun()   # 방금 고친 행의 환산 합계가 바로 보이도록 한 번 더 그린다 (표시 열은 저장된 값으로 계산하므로)
    st.caption(f"{len(view)}개 표시 / 전체 {len(table)}개" + (f" — 최근 {activity.DORMANT_DAYS}일 입고·청구가 있었던 품목만 보고 있어요 (위 스위치나 검색으로 나머지도 볼 수 있어요)" if codes is not None and not show_all and not q else ""))

    today, cal = get_today(), get_calendar()
    stock, errors = stock_from_table(t)
    s["stock_g"] = stock  # 달력·에이전트가 같은 재고로 계산
    results = [(ITEMS[n], g, recommend(ITEMS[n], g, today, cal)) for n, g in stock.items()]
    for name_, msg in errors:
        st.error(f"{name_}: {msg}")
    results = sorted(results, key=lambda x: STATUS_ORDER[x[2].status])
    shown_results, _ = only_active(results, show_all)                    # 상태 숫자도 표와 같은 품목 범위로
    n = {k: sum(r.status == k for _, _, r in shown_results) for k in STATUS}
    n_in = sum(checks[i] != "추정값" for i in universe)
    n_check = sum(checks[i].startswith("확인 필요") for i in universe)
    sig = table_signature(t)
    saved = ss.get("inv_saved", {}).get(get_store())
    with status:
        c_prog, c_state, c_save = st.columns([4, 6, 2], vertical_alignment="center")
        c_prog.progress(n_in / max(1, len(universe)), text=f"직접 센 품목 {n_in} / {len(universe)}개")
        with c_state:
            status_badges(n, ([(f"확인 필요 {n_check}", "orange", ":material/error:")] if n_check else []) + ([(f"입력 오류 {len(errors)}", "red", ":material/error:")] if errors else []))
        with c_save:
            st.button("이력에 저장", icon=":material/save:", type="primary", key="inv_save", on_click=save_snapshot, width="stretch",
                      help="현재 입력값을 '매장별 재고입력 이력'에 남깁니다.")
        if saved and saved[0] == sig:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.caption(f":material/check_circle: {saved[1]}에 저장했어요.")
                if "po-auto" in routing.PAGES:                              # 저장하면 다음에 할 일로 바로 가는 길 (앱 안에서만; 테스트 화면에는 페이지 목록이 없다)
                    st.page_link(routing.PAGES["po-auto"], label=f"긴급 {n['URGENT']}개 확인하기" if n["URGENT"] else "발주 추천 보기", icon=":material/arrow_forward:")
                if "po-engine" in routing.PAGES:
                    st.page_link(routing.PAGES["po-engine"], label="이력 기반 발주 추천", icon=":material/arrow_forward:")
        elif n_in:
            st.caption(":material/edit_note: 저장하지 않은 입력이 있어요. 끝나면 '이력에 저장'을 눌러 주세요." + (f" (마지막 저장 {saved[1]})" if saved else ""))
    return results, errors


def save_snapshot():
    s = inv_state()
    now = pd.Timestamp.now()
    ss.inv_history = [*ss.inv_history, {"저장시각": now.strftime("%Y-%m-%d %H:%M"), "매장": get_store(), "표": s["table"].copy()}]
    ss.inv_saved = {**ss.get("inv_saved", {}), get_store(): (table_signature(s["table"]), now.strftime("%H:%M"))}   # 저장한 뒤 바뀌었는지 알리려고
    st.toast("현재 실사 재고를 이력에 저장했어요.", icon=":material/check_circle:")


@register("stock.input")
def stock_input(leaf: Leaf):
    stock_editor()
    with st.expander("품목 하나만 빠르게 확인", icon=":material/search:"):
        pool = item_filter("quick", list(ITEMS.values()))
        if not pool:
            return
        name = st.selectbox("품목", [it.name for it in pool], key="quick_item")
        item = ITEMS[name]
        u = item.base_unit
        text = st.text_input(f"예: 1BOX 2PK 30{u}" + (", 2.5kg" if u == "g" else ", 1.5L" if u == "ml" else ""),
                             value=f"1pk 30{u}", key=f"quick_text_{name}")
        try:
            g = parse_count(item, text)
            rec_card(item, g, recommend(item, g, get_today(), get_calendar()))
        except InvalidInputError as e:
            st.error(f"입력 오류: {e}")


@register("stock.history")
def stock_history(leaf: Leaf):
    hist = [h for h in ss.inv_history if h["매장"] == get_store()]
    if not hist:
        st.caption("저장된 이력이 없어요. '매장별 재고입력'에서 '이력에 저장'을 눌러 남길 수 있어요.")
        return
    for h in reversed(hist):
        with st.expander(f"{h['저장시각']} · {h['매장']}"):
            st.dataframe(h["표"], hide_index=True, width="stretch", alt=f"{h['저장시각']} 재고 입력 이력")


@register("stock.forecast")
def stock_forecast(leaf: Leaf):
    show_all = dormant_toggle("stock_forecast_dormant")
    results, hidden = only_active(current_results(), show_all)
    if hidden:
        st.caption(f":material/visibility_off: 활동 있는 품목 {len(results)}개만 보고 있어요 (숨긴 품목 {hidden}개).")
    rows = [{"품목코드": it.code, "품목": it.name, "분류": it.mid, "재고": stock_of(it, g), "일 소비": stock_of(it, it.daily_usage_g) if it.usage_known else None,
             "안전재고": stock_of(it, safety_stock(it)) if it.usage_known else None,
             "소진율(%/일)": round(it.daily_usage_g / g * 100, 1) if g and it.usage_known else None,
             "잔여일": r.days_left, "상태": STATUS[r.status][0]} for it, g, r in results]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", alt="안전재고와 소진율 예측",
                 column_config={"잔여일": st.column_config.ProgressColumn("잔여일", min_value=0, max_value=14, format="%.1f일")})
    st.subheader("14일 재고 예측")
    st.caption("현재 재고에서 일 소비량만큼 줄어드는 단순 예측입니다 (입고 미반영). 기본으로 잔여일이 짧은 8개를 보여줘요.")
    usable = [(it, g, r) for it, g, r in results if it.usage_known and it.daily_usage_g > 0 and r.days_left is not None]
    default = [it.name for it, _g, _r in sorted(usable, key=lambda x: x[2].days_left)[:8]]
    cand = {it.name for it in item_filter("fc", [it for it, _g, _r in usable])}
    options = [it.name for it, _g, _r in usable if it.name in cand or it.name in ss.get("fc_items", default)]    # 이미 고른 품목은 필터에 가려져도 남긴다
    picked = st.multiselect("품목", options, default=[n for n in default if n in options], key="fc_items")
    days = range(0, 15)
    chart = pd.DataFrame({it.name: [max(0.0, (g - it.daily_usage_g * d) / it.pk_weight_g / units_of(it).per) for d in days]
                          for it, g, _r in usable if it.name in picked}, index=list(days))
    if chart.empty:
        st.caption("표시할 품목을 선택하세요.")
    else:
        axis_chart("line", chart, x_label="일 후", y_label="재고(품목별 발주단위)", alt_text="품목별 14일 재고 예측")
