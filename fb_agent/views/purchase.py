"""발주 및 재고관리: 발주관리 · 입고관리 · 기타입출고 · 수불관리."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from converter import parse_count, to_boxes
from data import ITEMS, SUPPLIERS
from errors import InvalidInputError
from importer import TEMPLATE_CSV, parse_inventory_file
from insights import build_table, stock_from_table
from menu import STORES, Leaf
from reorder import fmt_date, order_days, recommend, safety_stock
from state import get_calendar, get_store, get_today, inv_state
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
}
ACTION = ("URGENT", "ORDER_NOW", "ORDER_SOON")
MAX_CARDS = 8   # 우선 처리 카드를 한 번에 펼치는 최대 개수 (나머지는 접어 둠)
STATUS_ORDER = {s: i for i, s in enumerate(STATUS)}


# ---------------- 공통 ----------------
def current_results():
    """(품목, 총 재고(기본단위), 추천) 목록. 현재 매장의 재고 기준."""
    stock = inv_state()["stock_g"]
    today, cal = get_today(), get_calendar()
    out = [(ITEMS[n], g, recommend(ITEMS[n], g, today, cal)) for n, g in stock.items() if n in ITEMS]
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
    box, pk, loose = to_boxes(item, g)
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            status_badge(r.status)
            st.markdown(f"**{item.name}** · {item.supplier.name}")
        st.markdown(r.message)
        with st.container(horizontal=True):
            st.metric("재고", item.fmt(g), f"{box}BOX {pk}PK {item.fmt(loose)}", delta_color="off", delta_arrow="off", border=True)
            st.metric("잔여", "-" if r.days_left is None else f"{r.days_left:.1f}일", f"소진 {fmt_date(r.stockout_date)}",
                      delta_color="off", delta_arrow="off", border=True)
            st.metric("발주 → 입고", fmt_date(r.order_date), fmt_date(r.arrival_date), delta_color="off", delta_arrow="off", border=True)
            st.metric("추천 수량", f"{r.order_packs} PK", f"{r.order_packs / item.box_pk:.1f} BOX", delta_color="off",
                      delta_arrow="off", border=True)
        if request_button and r.status in ACTION:
            st.button("구매청구 만들기", key=f"mkreq_{item.name}", icon=":material/add_shopping_cart:",
                      on_click=add_request, args=(item.name, r.order_packs, r.arrival_date, "자동 발주 추천"))


# ---------------- 발주관리 ----------------
def add_request(item: str, packs: float, want: date | None, memo: str):
    ss.purchase_requests = [*ss.purchase_requests, {
        "청구번호": f"PR-{len(ss.purchase_requests) + 1:04d}", "청구일": get_today(), "품목": item,
        "거래처": ITEMS[item].supplier.name, "수량(PK)": packs, "희망입고일": want, "메모": memo, "상태": "청구"}]
    st.toast(f"구매청구를 만들었어요: {item} {packs}PK", icon=":material/check_circle:")


def convert_to_po(req_no: str):
    for r in ss.purchase_requests:
        if r["청구번호"] == req_no and r["상태"] == "청구":
            lead = ITEMS[r["품목"]].lead_time_days
            ss.purchase_orders = [*ss.purchase_orders, {
                "발주번호": f"PO-{len(ss.purchase_orders) + 1:04d}", "거래처": r["거래처"], "품목": r["품목"],
                "수량(PK)": r["수량(PK)"], "발주일": get_today(),
                "입고예정": r["희망입고일"] or get_today() + timedelta(days=lead), "상태": "입고대기"}]
            r["상태"] = "발주완료"
            st.toast(f"{req_no}을(를) 발주서로 전환했어요.", icon=":material/check_circle:")
            return


@register("po.request")
def po_request(leaf: Leaf):
    st.caption("필요한 품목을 청구하고, 승인되면 발주서로 전환합니다.")
    with st.form("new_request", border=True):
        c1, c2, c3 = st.columns(3)
        item = c1.selectbox("품목", list(ITEMS), format_func=item_label)
        packs = c2.number_input("수량 (PK)", min_value=0.5, value=2.0, step=0.5)
        want = c3.date_input("희망 입고일", value=get_today() + timedelta(days=2), min_value=get_today())
        memo = st.text_input("메모", placeholder="선택")
        if st.form_submit_button("청구 등록", type="primary", icon=":material/add:"):
            add_request(item, packs, want, memo)
    st.subheader("청구 목록")
    reqs = ss.purchase_requests
    if not reqs:
        st.caption("등록된 구매청구가 없어요.")
    for r in reversed(reqs):
        with st.container(border=True):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.markdown(f"**{r['청구번호']}** · {r['품목']} {r['수량(PK)']:g}PK · {r['거래처']} · 희망입고 {fmt_date(r['희망입고일'])}")
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
    df = pd.DataFrame(reqs)
    st.dataframe(df if status == "전체" else df[df["상태"] == status], hide_index=True, width="stretch", alt="구매청구 상세내역")


@register("po.leadtime")
def po_leadtime(leaf: Leaf):
    today, cal = get_today(), get_calendar()
    st.subheader("거래처")
    st.dataframe(pd.DataFrame([{"거래처": s.name, "발주 요일": s.order_days_label, "리드타임": f"D+{s.lead_time_days}"}
                               for s in SUPPLIERS.values()]), hide_index=True, width="stretch", alt="거래처 리드타임")
    st.subheader("품목별 다음 발주 가능일")
    st.caption("거래처 발주 요일, 매장 휴무, 입고일 영업 여부를 모두 반영합니다.")
    rows = []
    for it in ITEMS.values():
        days = order_days(it, today, cal)[:3]
        rows.append({"품목": it.name, "거래처": it.supplier.name, "리드타임": f"D+{it.lead_time_days}",
                     "다음 발주 가능일": " · ".join(fmt_date(d) for d in days) or "-",
                     "입고 예정": " · ".join(fmt_date(d + timedelta(days=it.lead_time_days)) for d in days) or "-"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", alt="품목별 다음 발주 가능일")


@register("po.auto")
def po_auto(leaf: Leaf):
    results = current_results()
    n = {s: sum(r.status == s for _, _, r in results) for s in STATUS}
    kpis([("긴급", f"{n['URGENT']}개", None), ("발주 필요", f"{n['ORDER_NOW'] + n['ORDER_SOON']}개", None),
          ("양호", f"{n['OK'] + n['NO_USAGE']}개", None)])
    st.caption(f"'{get_store()}' 현재 재고 기준입니다. 실제 재고는 '매장별 재고입력'에서 바꿀 수 있어요.")
    st.subheader("우선 처리")
    todo = [(it, g, r) for it, g, r in results if r.status in ACTION]
    if not todo:
        st.success("지금 발주할 품목이 없습니다.", icon=":material/check_circle:")
    for it, g, r in todo[:MAX_CARDS]:
        rec_card(it, g, r, request_button=True)
    if len(todo) > MAX_CARDS:
        with st.expander(f"나머지 {len(todo) - MAX_CARDS}개 보기"):
            for it, g, r in todo[MAX_CARDS:]:
                rec_card(it, g, r, request_button=True)

    st.subheader("전체 품목 현황")
    df = pd.DataFrame([{
        "상태": STATUS[r.status][0], "품목코드": it.code, "품목": it.name, "분류": it.mid, "거래처": it.supplier.name,
        "총재고": it.fmt(g),
        "잔여일": r.days_left, "소진예정": fmt_date(r.stockout_date), "발주예정일": fmt_date(r.order_date),
        "입고예정": fmt_date(r.arrival_date), "추천(PK)": r.order_packs,
        "추천(BOX)": round(r.order_packs / it.box_pk, 1), "비고": r.message} for it, g, r in results])
    st.dataframe(df, hide_index=True, width="stretch", alt="품목별 재고 상태와 발주 추천",
                 column_config={"잔여일": st.column_config.ProgressColumn("잔여일", min_value=0, max_value=14, format="%.1f일",
                                                                        help="14일을 가득 찬 값으로 표시"),
                                "비고": st.column_config.TextColumn(width="large")})
    st.subheader("거래처별 발주서")
    po = df[df["상태"].isin([STATUS[s][0] for s in ACTION])]
    if po.empty:
        st.caption("발주할 품목이 없습니다.")
    else:
        st.dataframe(po[["거래처", "품목", "추천(PK)", "추천(BOX)", "발주예정일", "입고예정", "상태"]]
                     .sort_values(["거래처", "발주예정일"]), hide_index=True, width="stretch", alt="거래처별 발주서")


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
            left.markdown(f"**{p['발주번호']}** · {p['품목']} {p['수량(PK)']:g}PK · {p['거래처']} · 입고예정 {fmt_date(p['입고예정'])}")
            right.button("입고 처리", key=f"rc_{p['발주번호']}", type="primary", on_click=receive_po, args=(p["발주번호"],))
    st.subheader("전체 발주서")
    st.dataframe(pd.DataFrame(ss.purchase_orders), hide_index=True, width="stretch", alt="발주서 목록")


@register("recv.general")
def recv_general(leaf: Leaf):
    st.caption("발주서 없이 들어온 물품을 입고 처리합니다. 입고하면 재고에 반영돼요.")
    sup = st.selectbox("거래처", list(SUPPLIERS))
    with st.form("general_receipt", border=True):
        c1, c2 = st.columns(2)
        item = c1.selectbox("품목", [n for n, i in ITEMS.items() if i.supplier.name == sup] or list(ITEMS))
        packs = c2.number_input("수량 (PK)", min_value=0.5, value=1.0, step=0.5)
        memo = st.text_input("비고", placeholder="선택")
        if st.form_submit_button("입고 등록", type="primary", icon=":material/move_to_inbox:"):
            add_receipt(get_today(), sup, item, packs, "일반입고", memo)
            st.toast(f"{item} {packs:g}PK 입고 완료", icon=":material/check_circle:")


@register("recv.detail")
def recv_detail(leaf: Leaf):
    df = pd.DataFrame(ss.receipts)
    kpis([("입고 건수", f"{len(df)}건", None), ("입고 수량", f"{df['수량(PK)'].sum():g}PK" if len(df) else "0PK", None)])
    if df.empty:
        st.caption("입고 내역이 없어요.")
        return
    kind = st.segmented_control("구분", ["전체", "구매발주서", "일반입고"], default="전체", key="recv_kind") or "전체"
    st.dataframe(df if kind == "전체" else df[df["구분"] == kind], hide_index=True, width="stretch", alt="입고 상세내역")


@register("recv.returns")
def recv_returns(leaf: Leaf):
    receipts = ss.receipts
    if not receipts:
        st.caption("반품할 입고 내역이 없어요.")
        return
    with st.form("return_form", border=True):
        idx = st.selectbox("입고 건", range(len(receipts)), format_func=lambda i: (
            f"{receipts[i]['입고일']} · {receipts[i]['품목']} {receipts[i]['수량(PK)']:g}PK ({receipts[i]['거래처']})"))
        c1, c2 = st.columns(2)
        packs = c1.number_input("반품 수량 (PK)", min_value=0.5, value=1.0, step=0.5)
        reason = c2.selectbox("사유", ["품질 불량", "오배송", "유통기한", "기타"])
        if st.form_submit_button("반품 등록", type="primary", icon=":material/assignment_return:"):
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
        st.dataframe(pd.DataFrame(ss.returns), hide_index=True, width="stretch", alt="반품 내역")
    else:
        st.caption("반품 내역이 없어요.")


# ---------------- 기타입출고 ----------------
@register("io.loss")
def io_loss(leaf: Leaf):
    with st.form("loss_form", border=True):
        c1, c2, c3 = st.columns(3)
        item = c1.selectbox("품목", list(ITEMS), format_func=item_label)
        packs = c2.number_input("수량 (PK)", min_value=0.0, value=1.0, step=0.5)
        reason = c3.selectbox("사유", ["폐기", "파손", "유통기한", "시식·샘플", "기타"])
        if st.form_submit_button("손망실 등록", type="primary", icon=":material/delete_forever:"):
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
    kpis([("건수", f"{len(df)}건", None), ("총량", f"{df['수량(PK)'].sum():g}PK", None)])
    st.bar_chart(df.groupby("사유")["수량(PK)"].sum(), alt="사유별 손망실 수량")
    st.dataframe(df, hide_index=True, width="stretch", alt="손망실 상세내역")


@register("io.transfer_request")
def io_transfer_request(leaf: Leaf):
    me = get_store()
    st.caption(f"'{me}'에서 다른 매장으로 물품 이체를 요청합니다.")
    with st.form("transfer_form", border=True):
        c1, c2, c3 = st.columns(3)
        to = c1.selectbox("받는 매장", [s for s in STORES if s != me])
        item = c2.selectbox("품목", list(ITEMS), format_func=item_label)
        packs = c3.number_input("수량 (PK)", min_value=0.5, value=1.0, step=0.5)
        memo = st.text_input("메모", placeholder="선택")
        if st.form_submit_button("이체 요청", type="primary", icon=":material/swap_horiz:"):
            ss.transfer_requests = [*ss.transfer_requests, {
                "번호": f"TR-{len(ss.transfer_requests) + 1:04d}", "요청일": get_today(), "보내는 매장": me, "받는 매장": to,
                "품목": item, "수량(PK)": packs, "메모": memo, "상태": "요청"}]
            st.toast("이체를 요청했어요.", icon=":material/check_circle:")
    for r in ss.transfer_requests:
        if r["상태"] != "요청":
            continue
        with st.container(border=True):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.markdown(f"**{r['번호']}** · {r['보내는 매장']} → {r['받는 매장']} · {r['품목']} {r['수량(PK)']:g}PK")
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
    st.dataframe(pd.DataFrame(ss.transfers), hide_index=True, width="stretch", alt="이체 상세내역")


# ---------------- 수불관리 ----------------
@register("stock.flow")
def stock_flow(leaf: Leaf):
    today = get_today()
    week_ago = today - timedelta(days=7)
    rows = []
    for it, g, _r in current_results():
        pk = it.pk_weight_g
        inn = sum(r["수량(PK)"] for r in ss.receipts if r["품목"] == it.name and r["입고일"] > week_ago)
        out = it.daily_usage_g * 7 / pk
        loss = sum(r["수량(PK)"] for r in ss.losses if r["품목"] == it.name and r["일자"] > week_ago)
        ret = sum(r["수량(PK)"] for r in ss.returns if r["품목"] == it.name and r["반품일"] > week_ago)
        end = g / pk
        rows.append({"품목": it.name, "기초(PK)": round(end - inn + out + loss + ret, 1), "입고(PK)": round(inn, 1),
                     "소비(PK)": round(out, 1), "손망실(PK)": round(loss, 1), "반품(PK)": round(ret, 1),
                     "기말(PK)": round(end, 1)})
    st.caption("최근 7일 수불: 기초 + 입고 − 소비 − 손망실 − 반품 = 기말 (소비는 일 소비량 기준 추정)")
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
          ("양호", f"{n['OK'] + n['NO_USAGE']}개", None), ("입력 오류", f"{len(errors)}개", None)])
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
    rows = [{"품목코드": it.code, "품목": it.name, "분류": it.mid, "재고": it.fmt(g), "일 소비": it.fmt(it.daily_usage_g),
             "안전재고": it.fmt(safety_stock(it)),
             "소진율(%/일)": round(it.daily_usage_g / g * 100, 1) if g else None,
             "잔여일": r.days_left, "상태": STATUS[r.status][0]} for it, g, r in results]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", alt="안전재고와 소진율 예측",
                 column_config={"잔여일": st.column_config.ProgressColumn("잔여일", min_value=0, max_value=14, format="%.1f일")})
    st.subheader("14일 재고 예측")
    st.caption("현재 재고에서 일 소비량만큼 줄어드는 단순 예측입니다 (입고 미반영). 기본으로 잔여일이 짧은 8개를 보여줘요.")
    usable = [(it, g, r) for it, g, r in results if it.daily_usage_g > 0]
    default = [it.name for it, _g, _r in sorted(usable, key=lambda x: x[2].days_left)[:8]]
    picked = st.multiselect("품목", [it.name for it, _g, _r in usable], default=default, key="fc_items")
    days = range(0, 15)
    chart = pd.DataFrame({it.name: [max(0.0, (g - it.daily_usage_g * d) / it.pk_weight_g) for d in days]
                          for it, g, _r in usable if it.name in picked}, index=list(days))
    if chart.empty:
        st.caption("표시할 품목을 선택하세요.")
    else:
        st.line_chart(chart, x_label="일 후", y_label="재고(PK)", alt="품목별 14일 재고 예측")
