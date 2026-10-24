"""발주 및 재고관리: 발주관리 · 입고관리 · 기타입출고 · 수불관리."""
import re
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import inventory_sim
import sales_data
import reorder_engine
import stock_sim
import store_calendar
from converter import parse_count
from data import ITEMS, SUPPLIERS
from errors import InvalidInputError
from importer import TEMPLATE_CSV, parse_inventory_file
from insights import build_table, stock_from_table
from menu import STORES, Leaf
from models import fmt_amount
from order_units import UNIT_SHORT, WHOLE_UNITS, packs_for
from reorder import fmt_date, is_order_day, order_days, recommend, safety_stock
from state import get_calendar, get_store, get_today, inv_state, on_order_g, position_g, stock_note
from unit_info import display_unit, qty_for, qty_of, stock_of, unit_name, units_of
from views import register
from views.common import kpis

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
MAX_CARDS = 8   # 우선 처리 카드를 한 번에 펼치는 최대 개수 (나머지는 접어 둠)
STATUS_ORDER = {s: i for i, s in enumerate(STATUS)}


# ---------------- 공통 ----------------
def current_results():
    """(품목, 총 재고(기본단위), 추천) 목록. 현재 매장의 재고 기준. 추천은 재고에 이미 오는 중인 입고(시뮬레이션 예측)를 더한 값으로 계산한다."""
    stock, pos = inv_state()["stock_g"], position_g()
    today, cal = get_today(), get_calendar()
    out = [(ITEMS[n], g, recommend(ITEMS[n], pos[n], today, cal)) for n, g in stock.items() if n in ITEMS]     # 판단은 재고 + 이미 오는 중인 입고
    return sorted(out, key=lambda x: STATUS_ORDER[x[2].status])


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
                      on_click=add_request, args=(item.name, r.order_packs, r.arrival_date, "자동 발주 추천"))


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


def add_requests_bulk(todo):
    """우선 처리 품목 전체를 한 번에 구매청구로 (이미 청구한 품목은 건너뜀)."""
    pending = {r["품목"] for r in ss.purchase_requests if r["상태"] == "청구"}
    made = 0
    for it, _g, r in todo:
        if it.name not in pending:
            add_request(it.name, r.order_packs, r.arrival_date, "자동 발주 추천", toast=False)
            made += 1
    st.toast(f"구매청구 {made}건을 만들었어요 (이미 청구한 {len(todo) - made}건은 건너뜀).", icon=":material/check_circle:")


def convert_to_po(req_no: str):
    for r in ss.purchase_requests:
        if r["청구번호"] == req_no and r["상태"] == "청구":
            lead = ITEMS[r["품목"]].lead_time_days or 0
            ss.purchase_orders = [*ss.purchase_orders, {
                "발주번호": f"PO-{len(ss.purchase_orders) + 1:04d}", "거래처": r["거래처"], "품목": r["품목"],
                "수량(PK)": r["수량(PK)"], "발주일": r.get("발주예정일") or get_today(),
                "입고예정": r["희망입고일"] or get_today() + timedelta(days=lead), "상태": "입고대기"}]
            r["상태"] = "발주완료"
            st.toast(f"{req_no}을(를) 발주서로 전환했어요.", icon=":material/check_circle:")
            return


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


def sup_days(sup: str) -> list[date]:
    """담긴 품목 모두에 맞는 발주 가능일 (업체 발주 요일·매장 영업일·입고일 영업일)."""
    items, today, cal = _cart_items(sup), get_today(), get_calendar()
    return [today + timedelta(days=i) for i in range(CAL_WEEKS * 7)
            if items and all(is_order_day(it, today + timedelta(days=i), cal) for it in items)]


def chosen_day(sup: str) -> date | None:
    """사용자가 고른 발주일. 고른 적이 없거나 더는 가능하지 않으면 가장 빠른 발주 가능일."""
    days = sup_days(sup)
    pick = ss.get(f"req_day_{sup}")
    return pick if pick in days else (days[0] if days else None)


def item_schedule(it) -> tuple[date | None, date | None]:
    """(발주일, 입고 예정일). 업체 카드에서 고른 날이 있으면 그 날, 없으면 가장 빠른 발주 가능일."""
    od = chosen_day(it.supplier.name)
    return (od, od + timedelta(days=it.lead_time_days)) if od and it.lead_time_days is not None else (None, None)


def pick_day(sup: str, d: date):
    ss[f"req_day_{sup}"] = d


def cart_submit():
    cart = _cart()
    memo = ss.get("req_memo", "")
    for name, qty in cart.items():
        od, arr = item_schedule(ITEMS[name])
        add_request(name, round(qty * units_of(ITEMS[name]).per, 2), arr, memo, toast=False, order_day=od)
    st.toast(f"구매청구 {len(cart)}건을 등록했어요.", icon=":material/check_circle:")
    ss.req_cart = {}


def schedule_calendar():
    """청구 목록에 담긴 거래처마다 카드형 달력: 발주 가능한 날을 눌러 발주일을 정하면 입고일이 따라온다."""
    sups = sorted({ITEMS[n].supplier.name for n in _cart()})
    if not sups:
        return
    today = get_today()
    st.markdown("##### 3. 발주일 · 입고일")
    st.caption("거래처마다 발주 가능한 날만 눌러서 고를 수 있어요. 날짜를 누르면 입고 예정일이 함께 정해집니다. 회색 날짜는 발주 요일이 아니거나 휴점·입고 불가일이에요.")
    start = today - timedelta(days=today.weekday())
    for sup in sups:
        items, days = _cart_items(sup), set(sup_days(sup))
        cur = chosen_day(sup)
        leads = sorted({it.lead_time_days for it in items if it.lead_time_days is not None})
        lead = "데이터 없음" if not leads else f"D+{leads[0]}" if len(leads) == 1 else f"D+{leads[0]}~{leads[-1]}"
        with st.container(border=True):
            st.markdown(f"**{sup}** · {len(items)}개 품목 · 발주 {SUPPLIERS[sup].order_days_label} · 리드타임 {lead}")
            if cur:
                od, arr = item_schedule(items[0])
                st.caption(f"선택: 발주 {fmt_date(cur)}" + (f" → 입고 {fmt_date(arr)}" if len(leads) == 1 else f" → 입고 {lead}"))
            else:
                st.warning(f"앞으로 {CAL_WEEKS}주 안에 발주 가능한 날이 없어요.", icon=":material/event_busy:")
            head = st.columns(7)
            for c, w in zip(head, "월화수목금토일"):
                c.caption(f"**{w}**")
            for wk in range(CAL_WEEKS):
                row = st.columns(7)
                for i, c in enumerate(row):
                    d = start + timedelta(days=wk * 7 + i)
                    if d < today:
                        c.button(" ", key=f"cal_{sup}_{d:%m%d}", disabled=True, width="stretch")
                    elif d in days:
                        label = f"{d:%m/%d}" + (f"\n→ {(d + timedelta(days=leads[0])):%m/%d}" if len(leads) == 1 else "")
                        c.button(label, key=f"cal_{sup}_{d:%m%d}", type="primary" if d == cur else "secondary", width="stretch",
                                 on_click=pick_day, args=(sup, d), help=f"{fmt_date(d)} 발주")
                    else:
                        c.button(f"{d:%m/%d}", key=f"cal_{sup}_{d:%m%d}", disabled=True, width="stretch")


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


@register("po.request")
def po_request(leaf: Leaf):
    st.caption("거래처를 고르고 품목 카드에서 수량을 정해 '담기' → 오른쪽 청구 목록에서 한 번에 등록합니다. 승인되면 발주서로 전환해요.")
    today, cal = get_today(), get_calendar()
    stock, pos = inv_state()["stock_g"], position_g()
    info = {it.name: (stock.get(it.name, 0.0), recommend(it, pos.get(it.name, 0.0), today, cal)) for it in ITEMS.values()}
    need = [n for n, (_g, r) in info.items() if r.status in ACTION]
    by_sup: dict = {}
    for it in ITEMS.values():
        by_sup.setdefault(it.supplier.name, []).append(it)
    labels = {f"{REQ_NEED} ({len(need)})": REQ_NEED, f"{REQ_ALL} ({len(ITEMS)})": REQ_ALL,
              **{f"{n} ({len(v)})": n for n, v in sorted(by_sup.items(), key=lambda kv: (-len(kv[1]), kv[0]))}}

    main, side = st.columns([3, 1], gap="medium")
    with main:
        st.markdown("##### 1. 거래처")
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
        st.markdown(f"##### 2. 품목 ({len(items)}개)")
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
        with st.container(border=True):
            cart = _cart()
            st.markdown(f"##### 청구 목록 ({len(cart)})")
            if not cart:
                st.caption("카드에서 '담기'를 누르면 여기에 쌓여요.")
            for name, packs in list(cart.items()):
                with st.container(horizontal=True, vertical_alignment="center"):
                    od, arr = item_schedule(ITEMS[name])
                    st.markdown(f"**{name}**  \n{ITEMS[name].supplier.name} · {qty_of(ITEMS[name], round(packs * units_of(ITEMS[name]).per, 2))}  \n"
                                f"발주 {fmt_date(od)} → 입고 {fmt_date(arr)}")
                    st.button("", key=f"rqx_{name}", icon=":material/close:", type="tertiary", on_click=cart_remove, args=(name,), help="목록에서 빼기")
            st.caption("발주일·입고일은 왼쪽 아래 '3. 발주일 · 입고일' 달력에서 거래처별로 고를 수 있어요. 고르지 않으면 가장 빠른 날로 정해져요.")
            st.text_input("메모", placeholder="선택", key="req_memo")
            st.button(f"청구 등록 ({len(cart)}건)", type="primary", icon=":material/add:", width="stretch", disabled=not cart, on_click=cart_submit)

    with main:
        schedule_calendar()

    st.subheader("청구 목록")
    reqs = ss.purchase_requests
    if not reqs:
        st.caption("등록된 구매청구가 없어요.")
    for r in reversed(reqs):
        with st.container(border=True):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.markdown(f"**{r['청구번호']}** · {r['품목']} {qty_for(r['품목'], r['수량(PK)'])} · {r['거래처']} · 발주 {fmt_date(r.get('발주예정일'))} → 입고 {fmt_date(r['희망입고일'])}")
            if r["상태"] == "청구":
                right.button("발주 전환", key=f"cv_{r['청구번호']}", on_click=convert_to_po, args=(r["청구번호"],))
            else:
                right.caption(r["상태"])


@register("po.request_detail")
def po_request_detail(leaf: Leaf):
    reqs = ss.purchase_requests
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
    head, search = st.columns([3, 2], vertical_alignment="bottom")
    head.subheader("품목별 다음 발주 가능일")
    q = search.text_input("품목 검색", placeholder="품목명 · 거래처 · 품목코드", key="lt_q").strip().lower()
    st.caption("거래처 발주 요일, 매장 휴무, 입고일 영업 여부를 모두 반영합니다.")
    rows = []
    for it in ITEMS.values():
        if q and q not in f"{it.name} {it.supplier.name} {it.code}".lower():
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


@register("po.auto")
def po_auto(leaf: Leaf):
    results = current_results()
    n = {s: sum(r.status == s for _, _, r in results) for s in STATUS}
    kpis([("긴급", f"{n['URGENT']}개", None), ("발주 필요", f"{n['ORDER_NOW'] + n['ORDER_SOON']}개", None),
          ("양호", f"{n['OK'] + n['NO_USAGE']}개", None), ("데이터 없음", f"{n['NO_DATA']}개", None)])
    st.caption(f"'{get_store()}' 현재 재고 기준입니다. 실제 재고는 '매장별 재고입력'에서 바꿀 수 있어요.")
    if note := stock_note():
        st.info(note, icon=":material/query_stats:")
    st.subheader("우선 처리")
    todo = [(it, g, r) for it, g, r in results if r.status in ACTION]
    if not todo:
        st.success("지금 발주할 품목이 없습니다.", icon=":material/check_circle:")
    if todo:
        st.button(f"위 {len(todo)}개 전체 구매청구 만들기", icon=":material/add_shopping_cart:", on_click=add_requests_bulk, args=(todo,),
                  help="우선 처리 품목을 한 번에 구매청구로 만듭니다. 이미 청구한 품목은 건너뜁니다.")
    for it, g, r in todo[:MAX_CARDS]:
        rec_card(it, g, r, request_button=True)
    if len(todo) > MAX_CARDS:
        st.caption(f"급한 순서로 {MAX_CARDS}개만 카드로 보여줘요. 나머지 {len(todo) - MAX_CARDS}개는 아래 '전체 품목 현황' 표에서 확인하세요 "
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


@register("po.engine")
def po_engine(leaf: Leaf):
    st.caption("거래처 청구·입고 이력(2024~2026)과 매출 예측으로 '무엇을 · 언제 · 얼마나' 발주할지 제안합니다. "
               "월말 실사재고(수불부)가 있으면 재고를 추정해 참고로 보여 주고, 주문 간격이 길어 습관으로 판단할 수 없는 품목은 재고로 판단합니다.")
    has_data = (reorder_engine.DATA / "2026" / "구매청구_정제.csv").exists()
    if get_store() != sales_data.STORE or not has_data:
        st.info(f"이력 기반 발주 추천은 실제 청구·입고 이력이 있는 '{sales_data.STORE}'에서만 제공합니다.", icon=":material/info:")
        return
    stamp = _engine_stamp()
    e = _engine(stamp)
    day = st.date_input("기준일 (발주하는 날)", value=get_today(), key="po_engine_day")
    if day > e.last + timedelta(days=3):
        st.warning(f"매출·발주 자료가 {e.last:%Y-%m-%d}까지라, {(day - e.last).days}일 뒤 날짜는 최근 주문 이력이 빠져 결과가 부정확합니다. "
                   "구매청구·일자별 매출을 갱신한 뒤 모델을 다시 학습해 주세요 (python reorder_engine.py --fit).", icon=":material/warning:")
    status, why = store_calendar.status(day)
    if status != "영업":
        st.caption(f":material/event: {day:%m/%d} {status}{f' · {why}' if why else ''}")
    t = _engine_table(day, stamp)
    counted = e.latest_count(day)
    if counted is None:
        st.caption(":material/inventory_2: 재고 반영 없음 — 월말 실사재고 자료가 없습니다.")
    elif (day - counted).days > reorder_engine.STALE_DAYS:
        n_ref = int(t["재고"].notna().sum())
        if n_ref:
            st.caption(f":material/inventory_2: 최근 월말 실사는 {counted:%Y-%m-%d}({(day - counted).days}일 전)라 실사 추정 대신 시뮬레이션 재고를 참고로 보여 줍니다 ({n_ref}개 품목). "
                       "발주할 시점 판단에는 쓰지 않고 '재고 넉넉' 주의와 '재고 확인' 품목의 근거에만 씁니다 (시뮬레이션 재고로 판정하면 맞은 비율이 낮아서).")
        else:
            st.caption(f":material/inventory_2: 최근 월말 실사는 {counted:%Y-%m-%d}({(day - counted).days}일 전)라 재고 추정은 쓰지 않았습니다 "
                       f"(실사 후 {reorder_engine.STALE_DAYS}일 안에만 반영). 시뮬레이션 예측이 없는 날짜입니다.")
    else:
        st.caption(f":material/inventory_2: {counted:%Y-%m-%d} 월말 실사 + 그 뒤 입고 − 예상 소비로 재고를 추정했습니다 ({int(t['재고'].notna().sum())}개 품목).")
    orders = t[t["상태"] == "발주"].sort_values(["거래처", "확률"], ascending=[True, False])
    n_season, n_check = int((t["상태"] == "시즌 시작 예상").sum()), int((t["상태"] == "재고 확인").sum())
    kpis([("발주 추천", f"{len(orders)}건", None), ("거래처", f"{orders['거래처'].nunique()}곳", None),
          ("시즌 시작 예상", f"{n_season}건", None), ("재고 확인 필요", f"{n_check}건", None)])

    st.subheader("오늘 발주 추천")
    if orders.empty:
        n_day, n_wait = int((t["상태"].isin(["발주", "보류", "재고 확인"])).sum()), int((t["상태"] == "보류").sum())
        if n_day == 0:
            st.success(f"{day:%m/%d}은 거래처 발주 요일이 아니거나 휴점이라 발주할 품목이 없습니다.", icon=":material/check_circle:")
        else:
            st.success(f"{day:%m/%d} 발주 가능한 정기 품목 {n_day}개 중 지금 발주할 시점인 품목은 없습니다 ({n_wait}개는 아직 이른 상태).", icon=":material/check_circle:")
    else:
        pick = st.multiselect("거래처", sorted(orders["거래처"].unique()), default=sorted(orders["거래처"].unique()), key="po_engine_sup")
        o = orders[orders["거래처"].isin(pick)]
        reqs, missing = engine_requests(o)
        by_code = {it.code: it.name for it in ITEMS.values() if it.code}
        pk = {r["item"]: r["packs"] for r in reqs}
        df = pd.DataFrame({
            "거래처": o["거래처"], "품목": o["품목"], "규격": o["규격"],
            "권장 수량": [_qty(q, u) for q, u in zip(o["권장수량"], o["단위"])], "상한": [_qty(q, u) for q, u in zip(o["상한수량"], o["단위"])],
            "앱 청구 수량": [qty_for(by_code[c], pk[by_code[c]]) if c in by_code else "마스터 미등록" for c in o["코드"]],
            "입고 예정": [fmt_date(d) for d in o["입고예정일"]], "직전 발주": o["직전발주"],
            "예상 재고": [_qty(round(r, 1), u) if pd.notna(r) else "" for r, u in zip(o["재고"], o["단위"])], "재고 주의": o["재고주의"],
            "발주 확률": (o["확률"] * 100).round(), "시즌": o["시즌"], "근거": o["사유"]})
        view_cols = [c for c in df.columns if c not in ("거래처", "근거")]
        st.button(f"구매청구 만들기 ({len(reqs)}건)", icon=":material/add_shopping_cart:", on_click=add_engine_requests, args=(reqs,), disabled=not reqs,
                  help="선택한 모든 거래처의 추천을 한 번에 구매청구로 만듭니다. 이미 청구한 품목은 건너뜁니다. 업체별로 만들려면 아래 각 거래처의 버튼을 누르세요.")
        cols = {"발주 확률": st.column_config.ProgressColumn("발주 확률", min_value=0, max_value=100, format="%d%%",
                                                          help="이 품목을 오늘 발주할 가능성. 평소 주문 주기와 마지막 주문 후 경과일로 계산"),
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
                with st.expander("근거 보기"):
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
def add_receipt(day: date, supplier: str, item: str, packs: float, kind: str, memo: str = ""):
    ss.receipts = [*ss.receipts, {"입고일": day, "거래처": supplier, "품목": item, "수량(PK)": packs, "구분": kind, "비고": memo}]
    add_stock(item, packs)


def receive_po(po_no: str):
    for po in ss.purchase_orders:
        if po["발주번호"] == po_no and po["상태"] == "입고대기":
            po["상태"] = "입고완료"
            add_receipt(get_today(), po["거래처"], po["품목"], po["수량(PK)"], "구매발주서", po_no)
            st.toast(f"{po_no} 입고 처리 완료 — 재고에 반영했어요.", icon=":material/check_circle:")
            return


@register("recv.by_po")
def recv_by_po(leaf: Leaf):
    pending = [p for p in ss.purchase_orders if p["상태"] == "입고대기"]
    kpis([("입고 대기", f"{len(pending)}건", None),
          ("입고 완료", f"{sum(p['상태'] == '입고완료' for p in ss.purchase_orders)}건", None)])
    st.subheader("입고 대기 발주서")
    if not pending:
        st.caption("입고 대기 중인 발주서가 없어요.")
    for p in pending:
        with st.container(border=True):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.markdown(f"**{p['발주번호']}** · {p['품목']} {qty_for(p['품목'], p['수량(PK)'])} · {p['거래처']} · 입고예정 {fmt_date(p['입고예정'])}")
            right.button("입고 처리", key=f"rc_{p['발주번호']}", type="primary", on_click=receive_po, args=(p["발주번호"],))
    st.subheader("전체 발주서")
    st.dataframe(pk_df(pd.DataFrame(ss.purchase_orders)), hide_index=True, width="stretch", alt="발주서 목록")


@register("recv.general")
def recv_general(leaf: Leaf):
    st.caption("발주서 없이 들어온 물품을 입고 처리합니다. 입고하면 재고에 반영돼요.")
    sup = st.selectbox("거래처", list(SUPPLIERS))
    with st.container(border=True):
        c1, c2 = st.columns(2)
        item = c1.selectbox("품목", [n for n, i in ITEMS.items() if i.supplier.name == sup] or list(ITEMS))
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
    st.dataframe(pk_df(df if kind == "전체" else df[df["구분"] == kind]), hide_index=True, width="stretch", alt="입고 상세내역")


@register("recv.returns")
def recv_returns(leaf: Leaf):
    receipts = ss.receipts
    if not receipts:
        st.caption("반품할 입고 내역이 없어요.")
        return
    with st.container(border=True):
        idx = st.selectbox("입고 건", range(len(receipts)), format_func=lambda i: (
            f"{receipts[i]['입고일']} · {receipts[i]['품목']} {qty_for(receipts[i]['품목'], receipts[i]['수량(PK)'])} ({receipts[i]['거래처']})"))
        c1, c2 = st.columns(2)
        packs = qty_input("반품 수량", ITEMS[receipts[idx]["품목"]], key=f"rt_qty_{receipts[idx]['품목']}", container=c1)
        reason = c2.selectbox("사유", ["품질 불량", "오배송", "유통기한", "기타"])
        if st.button("반품 등록", type="primary", icon=":material/assignment_return:"):
            r = receipts[idx]
            if packs > r["수량(PK)"]:
                st.error("입고 수량보다 많이 반품할 수 없어요.")
            else:
                ss.returns = [*ss.returns, {"반품일": get_today(), "거래처": r["거래처"], "품목": r["품목"],
                                           "수량(PK)": packs, "사유": reason}]
                add_stock(r["품목"], -packs)
                st.toast("반품을 등록했고 재고에서 차감했어요.", icon=":material/check_circle:")
    st.subheader("반품 내역")
    if ss.returns:
        st.dataframe(pk_df(pd.DataFrame(ss.returns)), hide_index=True, width="stretch", alt="반품 내역")
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
    st.bar_chart(df.groupby("사유").size(), alt="사유별 손망실 건수")
    st.dataframe(pk_df(df), hide_index=True, width="stretch", alt="손망실 상세내역")


@register("io.transfer_request")
def io_transfer_request(leaf: Leaf):
    me = get_store()
    st.caption(f"'{me}'에서 다른 매장으로 물품 이체를 요청합니다.")
    if not [x for x in STORES if x != me]:
        st.info("이체할 다른 매장이 등록되어 있지 않아요. 매장이 추가되면 이 화면에서 요청할 수 있어요.", icon=":material/database_off:")
        return
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        to = c1.selectbox("받는 매장", [s for s in STORES if s != me])
        item = c2.selectbox("품목", list(ITEMS), format_func=item_label)
        packs = qty_input("수량", ITEMS[item], key=f"tr_qty_{item}", container=c3)
        memo = st.text_input("메모", placeholder="선택")
        if st.button("이체 요청", type="primary", icon=":material/swap_horiz:"):
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
        ret = sum(r["수량(PK)"] for r in ss.returns if r["품목"] == it.name and r["반품일"] > week_ago)
        end = g / pk
        rows.append({"품목": it.name, "단위": unit, "기초": round((end - inn + out + loss + ret) * f, 1), "입고": round(inn * f, 1),
                     "소비": round(out * f, 1), "손망실": round(loss * f, 1), "반품": round(ret * f, 1), "기말": round(end * f, 1)})
    st.caption("최근 7일 수불: 기초 + 입고 − 소비 − 손망실 − 반품 = 기말 (소비는 일 소비량 기준 추정). 수량은 품목의 단위(병·박스·팩·개 등)로 보여줘요.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", alt="최근 7일 수불현황")


def stock_editor():
    """실사 재고 파일 업로드 + 입력 표. (품목, 총 g, 추천) 결과를 반환하고 현재 매장의 stock_g를 갱신."""
    s = inv_state()
    with st.expander("실사 재고 파일로 불러오기 (엑셀 · CSV · JSON · 텍스트)", icon=":material/upload_file:"):
        up_col, tpl_col = st.columns([3, 1], vertical_alignment="bottom")
        up = up_col.file_uploader("파일 선택", type=["csv", "tsv", "txt", "md", "json", "xlsx", "xls", "ods"],
                                  label_visibility="collapsed", key=f"inv_up_{get_store()}")
        tpl_col.download_button("양식 받기 (CSV)", TEMPLATE_CSV, "실사재고_양식.csv", "text/csv", icon=":material/download:")
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
                st.success(f"{len(imp.grams)}개 품목을 불러왔습니다. 아래 표에서 수정할 수 있습니다.")

    st.markdown(f"**실사 재고 입력 · {get_store()}**")
    if note := stock_note():
        st.info(note, icon=":material/query_stats:")
    st.caption("BOX·PK·낱개 값을 직접 수정하면 즉시 반영됩니다. 낱개는 품목의 기본단위(g·ml·개·장·롤 등)로 입력하고, "
               "BOX/PK 입수는 품목 마스터 기준으로 자동 환산됩니다.")
    table = s["table"]
    f_cat, f_q = st.columns([3, 2], vertical_alignment="bottom")
    cat = f_cat.pills("분류", ["전체", *dict.fromkeys(table["분류"])], default="전체", key="inv_cat") or "전체"
    q = f_q.text_input("품목 검색", placeholder="품목명 또는 코드", key="inv_q", icon=":material/search:").strip()
    mask = pd.Series(True, index=table.index)
    if cat != "전체":
        mask &= table["분류"] == cat
    if q:
        mask &= table["품목"].str.contains(q, case=False, regex=False) | table["품목코드"].str.contains(q, case=False, regex=False)
    view = table[mask]
    edited = st.data_editor(view, hide_index=True, disabled=["품목코드", "품목", "분류", "단위"], width="stretch",
                            key=f"inv_editor_{get_store()}_{s['ver']}_{cat}_{q}", alt="품목별 실사 재고 입력 표")
    t = table.copy()   # 보이는 행의 수정값만 전체 표에 반영 (필터로 가려진 행은 그대로)
    t.loc[edited.index, ["BOX", "PK", "낱개"]] = edited[["BOX", "PK", "낱개"]]
    s["table"] = t
    st.caption(f"{len(view)}개 표시 / 전체 {len(table)}개")

    today, cal = get_today(), get_calendar()
    stock, errors = stock_from_table(t)
    s["stock_g"] = stock  # 달력·에이전트가 같은 재고로 계산
    results = [(ITEMS[n], g, recommend(ITEMS[n], g, today, cal)) for n, g in stock.items()]
    for name_, msg in errors:
        st.error(f"{name_}: {msg}")
    return sorted(results, key=lambda x: STATUS_ORDER[x[2].status]), errors


def save_snapshot():
    s = inv_state()
    ss.inv_history = [*ss.inv_history, {"저장시각": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "매장": get_store(),
                                        "표": s["table"].copy()}]
    st.toast("현재 실사 재고를 이력에 저장했어요.", icon=":material/check_circle:")


@register("stock.input")
def stock_input(leaf: Leaf):
    results, errors = stock_editor()
    st.button("이력에 저장", icon=":material/save:", type="primary", on_click=save_snapshot,
              help="현재 입력값을 '매장별 재고입력 이력'에 남깁니다.")
    n = {s: sum(r.status == s for _, _, r in results) for s in STATUS}
    kpis([("긴급", f"{n['URGENT']}개", None), ("발주 필요", f"{n['ORDER_NOW'] + n['ORDER_SOON']}개", None),
          ("양호", f"{n['OK'] + n['NO_USAGE']}개", None), ("데이터 없음", f"{n['NO_DATA']}개", None), ("입력 오류", f"{len(errors)}개", None)])
    with st.expander("품목 하나만 빠르게 확인", icon=":material/search:"):
        name = st.selectbox("품목", list(ITEMS), key="quick_item")
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
    results = current_results()
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
    picked = st.multiselect("품목", [it.name for it, _g, _r in usable], default=default, key="fc_items")
    days = range(0, 15)
    chart = pd.DataFrame({it.name: [max(0.0, (g - it.daily_usage_g * d) / it.pk_weight_g / units_of(it).per) for d in days]
                          for it, g, _r in usable if it.name in picked}, index=list(days))
    if chart.empty:
        st.caption("표시할 품목을 선택하세요.")
    else:
        st.line_chart(chart, x_label="일 후", y_label="재고(품목별 발주단위)", alt="품목별 14일 재고 예측")
