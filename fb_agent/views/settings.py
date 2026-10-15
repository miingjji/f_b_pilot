"""설정/계정."""
from datetime import date

import pandas as pd
import streamlit as st

from auth_ui import current_user, logout, open_auth
from config import MASTER_MODE, default_today
from data import DATASET_LABEL, ITEMS, SUPPLIERS
from master import item_rows, to_json
from menu import Leaf
from models import WEEKDAY_KR
from state import get_store
from views import register

ss = st.session_state
DOW = "일월화수목금토"


def _add_closed():
    d = ss.set_new_closed
    if d not in ss.cfg_closed_dates:
        ss.cfg_closed_dates = sorted([*ss.cfg_closed_dates, d])


def _fmt(d: date) -> str:
    return f"{d:%Y-%m-%d} ({DOW[(d.weekday() + 1) % 7]})"


@register("set.store")
def store(leaf: Leaf):
    st.caption("정기 휴무와 임시 휴무는 달력과 발주 계산(입고일 영업 여부)에 모두 반영돼요.")
    with st.container(border=True):
        ss.cfg_closed_wd = st.multiselect(
            "정기 휴무 요일", range(7), default=ss.cfg_closed_wd, format_func=lambda d: WEEKDAY_KR[d] + "요일")

        st.markdown("**임시 휴무일** (공휴일·임시 휴무)")
        with st.container(horizontal=True, vertical_alignment="bottom"):
            st.date_input("날짜 선택", value=date.today(), key="set_new_closed")
            st.button("추가", icon=":material/add:", on_click=_add_closed)
        ss.cfg_closed_dates = st.multiselect(
            "등록된 임시 휴무일 (선택 해제하면 삭제)", options=sorted(ss.cfg_closed_dates),
            default=sorted(ss.cfg_closed_dates), format_func=_fmt)

        picked = st.date_input("기준일 (시뮬레이션용)", value=ss.cfg_today or default_today(),
                               help=("기본값은 실제 데이터의 마지막 날(2025-12-31)입니다." if MASTER_MODE == "real" else "기본값은 오늘입니다.") +" 다른 날짜로 바꾸면 발주·일정 계산의 기준일이 바뀝니다.")
        ss.cfg_today = None if picked == default_today() else picked


@register("set.items")
def items(leaf: Leaf):
    src = "data/real" if MASTER_MODE == "real" else "data"
    st.caption(f"품목 마스터입니다 ({DATASET_LABEL}). 원본은 `{src}/items.csv`(거래처는 `{src}/suppliers.csv`)이며, 엑셀에서 편집한 뒤 앱을 다시 시작하면 반영돼요.")
    if MASTER_MODE == "real":
        st.info("일 소비량·재고·리드타임·발주 요일의 **가상 값**은 `data/real/items.csv`의 출처 열(일소비량_출처, 재고_출처, 리드타임_출처)로 구분할 수 있어요.",
                icon=":material/science:")
    rows = pd.DataFrame(item_rows(ITEMS.values()))
    c1, c2, c3 = st.columns(3)
    major = c1.pills("대분류", ["전체", *dict.fromkeys(rows["대분류"])], default="전체", key="mst_major") or "전체"
    mids = ["전체", *dict.fromkeys(rows[rows["대분류"] == major]["중분류"] if major != "전체" else rows["중분류"])]
    mid = c2.selectbox("중분류", mids, key="mst_mid")
    q = c3.text_input("검색", placeholder="품목명·코드·거래처", key="mst_q", icon=":material/search:").strip()
    view = rows
    if major != "전체":
        view = view[view["대분류"] == major]
    if mid != "전체":
        view = view[view["중분류"] == mid]
    if q:
        hay = view["품목명"] + " " + view["품목코드"] + " " + view["거래처"]
        view = view[hay.str.contains(q, case=False, regex=False)]

    shown = view.assign(
        안전재고량=[ITEMS[n].fmt(v) for n, v in zip(view["품목명"], view["안전재고량"])],
        현재재고량=[ITEMS[n].fmt(v) for n, v in zip(view["품목명"], view["현재재고량"])],
    ).drop(columns=["기본단위"])
    st.dataframe(shown, hide_index=True, width="stretch", alt="품목 마스터",
                 column_config={"리드타임(일)": st.column_config.NumberColumn(format="D+%d")})
    st.caption(f"{len(view)}개 / 전체 {len(rows)}개 · 현재재고량은 시드(기본) 값이고, 매장별 실제 재고는 '매장별 재고입력'에서 관리해요.")
    with st.container(horizontal=True):
        st.download_button("CSV 내려받기", view.to_csv(index=False).encode("utf-8-sig"), "품목마스터.csv", "text/csv",
                           icon=":material/download:")
        st.download_button("JSON 내려받기", to_json(ITEMS[n] for n in view["품목명"]), "품목마스터.json", "application/json",
                           icon=":material/data_object:")


@register("set.suppliers")
def suppliers(leaf: Leaf):
    st.dataframe(pd.DataFrame([{"거래처": s.name, "발주 요일": s.order_days_label, "리드타임": f"D+{s.lead_time_days}"}
                               for s in SUPPLIERS.values()]), hide_index=True, width="stretch", alt="거래처별 발주 요일과 리드타임")
    st.caption("거래처 정보는 현재 코드(data.py)에서 관리합니다. 파일/DB로 옮기는 작업은 다음 단계예요.")


@register("set.agent")
def agent(leaf: Leaf):
    with st.container(border=True):
        labels = {"auto": "자동 (창이 넓으면 고정, 좁으면 서랍)", "dock": "항상 우측에 고정", "drawer": "항상 서랍으로 열기"}
        ss.cfg_agent_mode = st.radio("F&B Agent 패널 방식", list(labels), index=list(labels).index(ss.cfg_agent_mode),
                                     format_func=labels.get,
                                     help="고정하면 달력 칸이 좁아져요. 서랍은 버튼을 눌렀을 때만 우측에서 열립니다.")


@register("set.account")
def account(leaf: Leaf):
    user = current_user()
    with st.container(border=True):
        if user:
            st.markdown(f"**{user['name']}**")
            st.caption(user["email"] or "데모 사용자")
            st.caption(f"선택한 매장: {get_store()}")
            st.button("로그아웃", icon=":material/logout:", on_click=logout)
        else:
            st.markdown("로그인하지 않았어요.")
            with st.container(horizontal=True):
                if st.button("로그인", icon=":material/login:"):
                    open_auth("login")
                if st.button("회원가입"):
                    open_auth("signup")
    st.caption("데모 모드에서는 이름·이메일만 받으며 비밀번호는 저장하지 않습니다.")
