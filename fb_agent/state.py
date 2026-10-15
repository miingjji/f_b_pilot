"""세션 공통 상태. 페이지가 바뀌면 위젯 상태는 사라지므로 값은 cfg_* 같은 일반 키에 보관."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from calendar_data import sample_events
from data import DEFAULT_CALENDAR, ITEMS, SAMPLE_COUNTS
from insights import recommendations, sample_stock_g
from menu import STORES
from models import StoreCalendar
from viewport import is_mobile, viewport


def _sample_table() -> pd.DataFrame:
    return pd.DataFrame([{"품목": n, "BOX": float(SAMPLE_COUNTS[n][0]), "PK": float(SAMPLE_COUNTS[n][1]),
                          "낱개(g)": float(SAMPLE_COUNTS[n][2])} for n in ITEMS])


def _seed_purchase_orders(today: date) -> list[dict]:
    return [
        {"발주번호": "PO-0001", "거래처": "A식자재", "품목": "짜사이", "수량(PK)": 6,
         "발주일": today - timedelta(days=2), "입고예정": today + timedelta(days=1), "상태": "입고대기"},
        {"발주번호": "PO-0002", "거래처": "B유통", "품목": "단무지", "수량(PK)": 4,
         "발주일": today - timedelta(days=1), "입고예정": today + timedelta(days=2), "상태": "입고대기"},
        {"발주번호": "PO-0003", "거래처": "C농산", "품목": "청양고추", "수량(PK)": 8,
         "발주일": today - timedelta(days=6), "입고예정": today - timedelta(days=3), "상태": "입고완료"},
    ]


def init_state():
    ss = st.session_state
    if "initialized" in ss:
        return
    today = date.today()
    ss.initialized = True
    ss.user = None                      # 데모 로그인 사용자
    ss.store = STORES[0]                # 선택된 매장
    ss.rail = None                      # 서브 패널에 펼친 레일 (None이면 현재 화면 기준)
    ss.favorites = []                   # 즐겨찾기한 소메뉴 id
    ss.agent_open = True
    ss.cfg_agent_mode = "auto"          # auto | dock | drawer
    ss.messages = []
    ss.cfg_today = None                 # None이면 실제 오늘
    ss.cfg_closed_wd = sorted(DEFAULT_CALENDAR.closed_weekdays)
    ss.cfg_closed_dates = []
    ss.events = sample_events(today)
    ss.sel_day = today
    ss.cal_month = today.replace(day=1)
    ss.inv = {}                         # 매장별 재고 상태 (inv_state 참고)
    # 구매·입출고·인력 업무 데이터 (세션 동안만 유지)
    ss.purchase_requests = []
    ss.purchase_orders = _seed_purchase_orders(today)
    ss.receipts = [{"입고일": today - timedelta(days=3), "거래처": "C농산", "품목": "청양고추", "수량(PK)": 8,
                    "구분": "구매발주서", "비고": "PO-0003"}]
    ss.returns, ss.losses, ss.transfers, ss.transfer_requests = [], [], [], []
    ss.shift_requests = []
    ss.inv_history = []


def toggle_favorite(leaf_id: str):
    favs = list(st.session_state.favorites)
    favs.remove(leaf_id) if leaf_id in favs else favs.append(leaf_id)
    st.session_state.favorites = favs


def get_store() -> str:
    return st.session_state.store


def inv_state() -> dict:
    """현재 매장의 재고 상태: table(BOX/PK/낱개 표), ver(data_editor 키), applied(적용한 업로드 파일), stock_g."""
    inv = st.session_state.inv
    return inv.setdefault(get_store(), {"table": _sample_table(), "ver": 0, "applied": None, "stock_g": {}})


def get_today() -> date:
    return st.session_state.cfg_today or date.today()


def get_calendar() -> StoreCalendar:
    ss = st.session_state
    return StoreCalendar(frozenset(ss.cfg_closed_wd), frozenset(ss.cfg_closed_dates))


def get_recs():
    """재고 화면을 아직 열지 않았다면 예시 재고로 계산."""
    return recommendations(inv_state()["stock_g"] or sample_stock_g(), get_today(), get_calendar())


DOCK_MIN_VIEWPORT = 1760        # 자동 모드에서 에이전트를 옆에 고정하는 최소 창 폭
DOCK_RATIO = (3, 1.25)          # (본문, 에이전트) 열 비율
DOCK_GAP = 16


def agent_mode() -> str:
    """'dock'(우측 고정 패널) 또는 'drawer'(버튼으로 여는 우측 서랍).

    자동: 창이 넓으면 고정, 아니면 서랍 (고정하면 달력 셀이 좁아지기 때문). 휴대폰은 항상 서랍."""
    vw, _ = viewport()
    if is_mobile():
        return "drawer"
    mode = st.session_state.cfg_agent_mode
    if mode == "auto":
        return "dock" if vw >= DOCK_MIN_VIEWPORT else "drawer"
    return mode


def main_width() -> float:
    """중앙 영역의 예상 폭(px)."""
    _, cw = viewport()
    if agent_mode() == "dock" and st.session_state.agent_open:
        a, b = DOCK_RATIO
        return (cw - DOCK_GAP) * a / (a + b)
    return cw
