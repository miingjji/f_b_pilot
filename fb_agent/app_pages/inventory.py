import pandas as pd
import streamlit as st

from converter import parse_count, to_boxes, to_grams
from data import ITEMS
from errors import InvalidInputError
from importer import TEMPLATE_CSV, parse_inventory_file
from reorder import fmt_date, recommend
from state import get_calendar, get_today

# 상태: (라벨, 배지 색, 아이콘)
STATUS = {
    "URGENT": ("긴급", "red", ":material/error:"),
    "ORDER_NOW": ("지금 발주", "orange", ":material/shopping_cart:"),
    "ORDER_SOON": ("곧 발주", "yellow", ":material/schedule:"),
    "OK": ("양호", "green", ":material/check_circle:"),
    "NO_USAGE": ("소비 없음", "gray", ":material/remove_circle:"),
}
ACTION = ("URGENT", "ORDER_NOW", "ORDER_SOON")
STATUS_ORDER = {s: i for i, s in enumerate(STATUS)}

ss = st.session_state
today, cal = get_today(), get_calendar()


def status_badge(status: str):
    label, color, icon = STATUS[status]
    st.badge(label, icon=icon, color=color)


def rec_card(item, g, r):
    """품목 하나의 재고 상태와 발주 추천."""
    box, pk, loose = to_boxes(item, g)
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            status_badge(r.status)
            st.markdown(f"**{item.name}** · {item.supplier.name}")
        st.markdown(r.message)
        with st.container(horizontal=True):
            st.metric("재고", f"{g:,.0f}g", f"{box}BOX {pk}PK {loose:,.0f}g", delta_color="off", delta_arrow="off",
                      border=True)
            st.metric("잔여", "-" if r.days_left is None else f"{r.days_left:.1f}일",
                      f"소진 {fmt_date(r.stockout_date)}", delta_color="off", delta_arrow="off", border=True)
            st.metric("발주 → 입고", fmt_date(r.order_date), fmt_date(r.arrival_date), delta_color="off",
                      delta_arrow="off", border=True)
            st.metric("추천 수량", f"{r.order_packs} PK", f"{r.order_packs / item.box_pk:.1f} BOX",
                      delta_color="off", delta_arrow="off", border=True)


tab_check, tab_all = st.tabs([":material/search: 품목별 확인", ":material/list_alt: 전체 요약 · 발주 추천"])

with tab_check:
    name = st.selectbox("품목", list(ITEMS))
    item = ITEMS[name]
    st.caption(f"1PK = {item.pk_weight_g:,.0f}g · 1BOX = {item.box_pk:g}PK ({item.box_weight_g:,.0f}g) · "
               f"일 소비 {item.daily_usage_g:,.0f}g · {item.supplier.name} "
               f"({item.supplier.order_days_label}, D+{item.lead_time_days})")
    mode = st.segmented_control("입력 방식", ["칸별 입력", "자유 입력"], default="칸별 입력") or "칸별 입력"
    if mode == "칸별 입력":
        with st.container(horizontal=True):
            # min_value 없이 받아 음수 입력도 앱의 예외 처리 로직으로 검증
            boxes = st.number_input("BOX", value=0.0, step=1.0)
            packs = st.number_input("PK", value=0.0, step=1.0)
            loose = st.number_input("낱개 잔량 (g)", value=0.0, step=50.0)
    else:
        text = st.text_input("예: 1BOX 2PK 300g, 2.5kg, 10EA", value="1pk 300g")
    if st.button("발주 상태 확인", type="primary"):
        try:
            g = to_grams(item, packs, loose, boxes=boxes) if mode == "칸별 입력" else parse_count(item, text)
            rec_card(item, g, recommend(item, g, today, cal))
        except InvalidInputError as e:
            st.error(f"입력 오류: {e}")

with tab_all:
    with st.expander("실사 재고 파일로 불러오기 (엑셀 · CSV · JSON · 텍스트)", icon=":material/upload_file:"):
        up_col, tpl_col = st.columns([3, 1], vertical_alignment="bottom")
        up = up_col.file_uploader("파일 선택", type=["csv", "tsv", "txt", "md", "json", "xlsx", "xls", "ods"],
                                  label_visibility="collapsed")
        tpl_col.download_button("양식 받기 (CSV)", TEMPLATE_CSV, "실사재고_양식.csv", "text/csv",
                                icon=":material/download:")
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
                if ss.inv_applied_file != up.file_id:  # 같은 파일을 rerun마다 다시 덮어쓰지 않음 (사용자 수정 보존)
                    counts = {n: to_boxes(ITEMS[n], imp.grams.get(n, 0.0)) for n in ITEMS}
                    ss.inv_table = pd.DataFrame([{"품목": n, "BOX": float(counts[n][0]), "PK": float(counts[n][1]),
                                                  "낱개(g)": float(counts[n][2])} for n in ITEMS])
                    ss.inv_ver += 1
                    ss.inv_applied_file = up.file_id
                st.success(f"{len(imp.grams)}개 품목을 불러왔습니다. 아래 표에서 수정할 수 있습니다.")

    st.markdown("**실사 재고 입력**")
    st.caption("BOX·PK·낱개(g) 값을 직접 수정하면 즉시 반영됩니다. 단위는 품목별 입수 기준으로 자동 환산됩니다.")
    edited = st.data_editor(ss.inv_table, hide_index=True, disabled=["품목"], width="stretch",
                            key=f"inv_editor_{ss.inv_ver}", alt="품목별 실사 재고 입력 표")
    ss.inv_table = edited  # 페이지를 옮겨도 수정값 유지 (수정은 셀 값 덮어쓰기라 다시 적용해도 같은 결과)

    results, errors, stock = [], [], {}
    for _, row in edited.iterrows():
        it = ITEMS[row["품목"]]
        try:
            g = to_grams(it, row["PK"], row["낱개(g)"], boxes=row["BOX"])
        except InvalidInputError as e:
            errors.append((it.name, str(e)))
            continue
        stock[it.name] = g
        results.append((it, g, recommend(it, g, today, cal)))
    ss.stock_g = stock  # 달력·에이전트가 같은 재고로 계산
    results.sort(key=lambda x: STATUS_ORDER[x[2].status])

    # ---- 요약 ----
    n = {s: sum(r.status == s for _, _, r in results) for s in STATUS}
    with st.container(horizontal=True):
        for label, value in [("긴급", n["URGENT"]), ("발주 필요", n["ORDER_NOW"] + n["ORDER_SOON"]),
                             ("양호", n["OK"] + n["NO_USAGE"]), ("입력 오류", len(errors))]:
            with st.container(border=True):
                st.metric(label, f"{value}개")
    for name_, msg in errors:
        st.error(f"{name_}: {msg}")

    # ---- 우선 처리 ----
    st.subheader("우선 처리")
    todo = [(it, g, r) for it, g, r in results if r.status in ACTION]
    if not todo:
        st.success("지금 발주할 품목이 없습니다.", icon=":material/check_circle:")
    for it, g, r in todo:
        rec_card(it, g, r)

    # ---- 전체 현황 ----
    st.subheader("전체 품목 현황")
    df = pd.DataFrame([{
        "상태": STATUS[r.status][0], "품목": it.name, "거래처": it.supplier.name, "총재고(g)": int(g),
        "잔여일": r.days_left, "소진예정": fmt_date(r.stockout_date), "발주예정일": fmt_date(r.order_date),
        "입고예정": fmt_date(r.arrival_date), "추천(PK)": r.order_packs,
        "추천(BOX)": round(r.order_packs / it.box_pk, 1), "비고": r.message} for it, g, r in results])
    if not df.empty:
        st.dataframe(df, hide_index=True, width="stretch", alt="품목별 재고 상태와 발주 추천",
                     column_config={
                         "총재고(g)": st.column_config.NumberColumn(format="%d"),
                         "잔여일": st.column_config.ProgressColumn("잔여일", min_value=0, max_value=14,
                                                                 format="%.1f일", help="14일을 가득 찬 값으로 표시"),
                         "비고": st.column_config.TextColumn(width="large"),
                     })

    # ---- 발주서 ----
    st.subheader("거래처별 발주서")
    po = df[df["상태"].isin([STATUS[s][0] for s in ACTION])] if not df.empty else df
    if po.empty:
        st.caption("발주할 품목이 없습니다.")
    else:
        st.dataframe(po[["거래처", "품목", "추천(PK)", "추천(BOX)", "발주예정일", "입고예정", "상태"]]
                     .sort_values(["거래처", "발주예정일"]), hide_index=True, width="stretch", alt="거래처별 발주서")
