"""세션 공통 상태. 페이지가 바뀌면 위젯 상태는 사라지므로 값은 cfg_* 같은 일반 키에 보관."""
from datetime import date, timedelta

import streamlit as st

import store_calendar
from config import default_today
from data import DEFAULT_CALENDAR, ITEMS
from insights import build_table, master_stock_g, recommendations, sim_on_order, sim_stock_note, stock_from_table
from menu import STORES
from models import StoreCalendar
from viewport import is_mobile, viewport



def init_state():
    ss = st.session_state
    if "initialized" in ss:
        return
    today = default_today()
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
    ss.cfg_closed_dates = sorted(d for d in store_calendar.closures() if d >= today - timedelta(days=7))   # 확정 휴점일 (신정·설·추석 전날과 당일, 무매출일, 입력한 휴점일)
    ss.events = []                      # 직접 추가한 일정 (현재 세션에만 저장)
    ss.sel_day = today
    ss.cal_month = today.replace(day=1)
    ss.inv = {}                         # 매장별 재고 상태 (inv_state 참고)
    # 구매·입출고·인력 업무 데이터 (세션 동안만 유지)
    ss.purchase_requests = []
    ss.purchase_orders = []
    ss.receipts = []
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
    """현재 매장의 재고 상태: table(BOX/PK/낱개 표), ver(data_editor 키), applied(적용한 업로드 파일), stock_g, seed(시드 표·기준일).
    사용자가 손대지 않은 시드 재고는 기준일이 바뀌면 그 날의 시뮬레이션 재고로 다시 만든다."""
    inv = st.session_state.inv
    store, today = get_store(), get_today()
    s = inv.get(store)
    if s is None or (s["applied"] is None and s["seed"][0] != today and s["table"].equals(s["seed"][1])):
        table = build_table(master_stock_g(today))
        s = inv[store] = {"table": table, "ver": 0 if s is None else s["ver"] + 1, "applied": None, "stock_g": stock_from_table(table)[0], "seed": (today, table.copy()), "on_order": sim_on_order(today)}
    return s


def _simulated(s: dict) -> bool:
    """재고가 시뮬레이션 시드 그대로인가 (사용자가 고치거나 실사 파일을 올리지 않았다)."""
    return s["applied"] is None and s["table"].equals(s["seed"][1])


def on_order_g() -> dict:
    """{품목명: 이미 오는 중인 입고(기본단위)}. 시뮬레이션 재고를 그대로 쓰는 동안만 — 실사를 직접 입력했으면 그 시점의 입고는 알 수 없어 비운다."""
    s = inv_state()
    return s["on_order"] if _simulated(s) else {}


def position_g() -> dict:
    """발주 판단에 쓰는 재고 포지션 = 현재 재고 + 이미 오는 중인 입고."""
    s = inv_state()
    oo = on_order_g()
    return {n: g + oo.get(n, 0.0) for n, g in s["stock_g"].items()}


def stock_note() -> str:
    """재고가 시뮬레이션 값 그대로이면 그 안내, 사용자가 고쳤거나 실사 파일을 올렸으면 빈 문자열."""
    s = inv_state()
    if not _simulated(s):
        return ""
    note = sim_stock_note(s["seed"][0])
    return note + (f" 발주 판단(잔여일·소진일·긴급)에는 이미 오는 중인 입고 {len(s['on_order'])}개 품목분을 더했습니다 — 구매청구에 기록된 오는 중인 주문, 구매청구 이력이 없는 품목(CK 등)은 시뮬레이션 예상 입고." if s["on_order"] else "")


def get_today() -> date:
    return st.session_state.cfg_today or default_today()


def get_calendar() -> StoreCalendar:
    ss = st.session_state
    return StoreCalendar(frozenset(ss.cfg_closed_wd), frozenset(ss.cfg_closed_dates))


def get_recs():
    """재고 화면을 아직 열지 않았다면 예시 재고로 계산."""
    return recommendations(position_g(), get_today(), get_calendar())


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
