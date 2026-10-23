"""세션 공통 상태. 페이지가 바뀌면 위젯 상태는 사라지므로 값은 cfg_* 같은 일반 키에 보관."""
from datetime import date, timedelta

import streamlit as st

from calendar_data import sample_events
from config import default_today
from data import DEFAULT_CALENDAR, ITEMS
from insights import build_table, recommendations, sample_stock_g, stock_from_table
from menu import STORES
from models import StoreCalendar
from viewport import is_mobile, viewport


DEMO_NAMES = ("짜사이", "단무지", "청양고추")      # 샘플 마스터의 데모 품목


def demo_items(items: dict) -> list:
    """시드 발주서·입고에 쓸 품목 최대 3개. 샘플 마스터는 원래 데모 품목, 그 외에는 소비가 있는 품목을 업체가 겹치지 않게."""
    if all(n in items for n in DEMO_NAMES):
        return [items[n] for n in DEMO_NAMES]
    pool = [it for it in items.values() if it.usage_known and it.daily_usage_g > 0] or list(items.values())
    picked, seen = [], set()
    for it in pool:
        if it.supplier.name not in seen:
            picked.append(it)
            seen.add(it.supplier.name)
        if len(picked) == 3:
            break
    for it in pool:                                        # 업체가 모자라면 같은 업체에서 채움
        if len(picked) >= 3:
            break
        if it not in picked:
            picked.append(it)
    return picked


def _seed_purchase_orders(today: date) -> list[dict]:
    spec = [("입고대기", 6, -2, 1), ("입고대기", 4, -1, 2), ("입고완료", 8, -6, -3)]       # (상태, 수량, 발주일 오프셋, 입고예정 오프셋)
    return [{"발주번호": f"PO-{i:04d}", "거래처": it.supplier.name, "품목": it.name, "수량(PK)": qty,
             "발주일": today + timedelta(days=o), "입고예정": today + timedelta(days=a), "상태": status}
            for i, (it, (status, qty, o, a)) in enumerate(zip(demo_items(ITEMS), spec), start=1)]


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
    ss.cfg_closed_dates = []
    ss.events = sample_events(today)
    ss.sel_day = today
    ss.cal_month = today.replace(day=1)
    ss.inv = {}                         # 매장별 재고 상태 (inv_state 참고)
    # 구매·입출고·인력 업무 데이터 (세션 동안만 유지)
    ss.purchase_requests = []
    ss.purchase_orders = _seed_purchase_orders(today)
    done = [p for p in ss.purchase_orders if p["상태"] == "입고완료"]
    ss.receipts = [{"입고일": p["입고예정"], "거래처": p["거래처"], "품목": p["품목"], "수량(PK)": p["수량(PK)"],
                    "구분": "구매발주서", "비고": p["발주번호"]} for p in done]
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
    store = get_store()
    if store not in inv:
        table = build_table(sample_stock_g(store))
        inv[store] = {"table": table, "ver": 0, "applied": None, "stock_g": stock_from_table(table)[0]}
    return inv[store]


def get_today() -> date:
    return st.session_state.cfg_today or default_today()


def get_calendar() -> StoreCalendar:
    ss = st.session_state
    return StoreCalendar(frozenset(ss.cfg_closed_wd), frozenset(ss.cfg_closed_dates))


def get_recs():
    """재고 화면을 아직 열지 않았다면 예시 재고로 계산."""
    return recommendations(inv_state()["stock_g"], get_today(), get_calendar())


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
