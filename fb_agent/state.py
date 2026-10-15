"""세션 공통 상태. 페이지가 바뀌면 위젯 상태는 사라지므로 값은 cfg_* 같은 일반 키에 보관."""
from datetime import date

import pandas as pd
import streamlit as st

from calendar_data import sample_events
from data import DEFAULT_CALENDAR, ITEMS, SAMPLE_COUNTS
from insights import recommendations
from models import StoreCalendar
from viewport import is_mobile, viewport


def _sample_table() -> pd.DataFrame:
    return pd.DataFrame([{"품목": n, "BOX": float(SAMPLE_COUNTS[n][0]), "PK": float(SAMPLE_COUNTS[n][1]),
                          "낱개(g)": float(SAMPLE_COUNTS[n][2])} for n in ITEMS])


def init_state():
    ss = st.session_state
    if "initialized" in ss:
        return
    today = date.today()
    ss.initialized = True
    ss.user = None                      # 데모 로그인 사용자
    ss.agent_open = True
    ss.cfg_agent_mode = "auto"          # auto | dock | drawer
    ss.messages = []
    ss.cfg_today = None                 # None이면 실제 오늘
    ss.cfg_closed_wd = sorted(DEFAULT_CALENDAR.closed_weekdays)
    ss.cfg_closed_dates = []
    ss.events = sample_events(today)
    ss.sel_day = today
    ss.cal_month = today.replace(day=1)
    ss.inv_table = _sample_table()      # 실사 재고 표 (BOX/PK/낱개)
    ss.inv_ver = 0                      # 업로드로 표를 교체할 때마다 증가 (data_editor 키)
    ss.inv_applied_file = None
    ss.stock_g = {}                     # 재고 페이지가 계산한 품목별 총 g (달력·에이전트가 사용)


def get_today() -> date:
    return st.session_state.cfg_today or date.today()


def get_calendar() -> StoreCalendar:
    ss = st.session_state
    return StoreCalendar(frozenset(ss.cfg_closed_wd), frozenset(ss.cfg_closed_dates))


def get_recs():
    """재고 페이지를 아직 열지 않았다면 예시 재고로 계산."""
    from insights import sample_stock_g
    ss = st.session_state
    return recommendations(ss.stock_g or sample_stock_g(), get_today(), get_calendar())


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
