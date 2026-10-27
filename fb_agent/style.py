"""화면 공통 CSS. 색·글씨체·크기는 .streamlit/config.toml 의 테마(장부: 종이색 바탕, 먹색 글자, 깊은 녹색 포인트, Pretendard)를 따르고,
여기서는 카드·여백·탭·표·지표 모양처럼 테마로 못 정하는 것만 다듬는다.

st.container(key=...) 가 붙이는 `st-key-<키>` 클래스를 선택자로 써서 Streamlit 내부 클래스명에 기대지 않는다.
색 규칙: 포인트색(녹색)은 행동·선택에만 쓰고, 빨강·주황은 '문제가 있는 곳'에만 쓴다. 정상 상태는 색을 입히지 않는다.
"""
import streamlit as st

# 장부 팔레트 (config.toml 의 값과 같다): 포인트, 선, 먹색 글자, 보조 글자, 바탕, 카드 면, 포인트 연한 면, 위험, 주의
ACCENT, LINE, INK, MUTED = "#1F5F4A", "#DDD6C6", "#1B2A22", "#56645B"
PAPER, SURFACE, TINT, DANGER, WARN = "#F5F2EA", "#FFFDF8", "#E4EEE8", "#B3261E", "#9A5600"
BLUE = ACCENT   # (옛 이름: 선택·강조색)
ICON_COLOR = "#66746B"
CHIPS = [(ICON_COLOR, "transparent")]   # 지표 아이콘은 색 칩 없이 한 가지 먹색 선 아이콘
ICONS = [("매출", "payments"), ("객단가", "receipt_long"), ("객수", "groups"), ("근무", "badge"), ("인건", "badge"),
         ("긴급", "notification_important"), ("발주", "local_shipping"), ("양호", "task_alt"), ("재고", "inventory_2"),
         ("품목", "inventory_2"), ("일정", "event_available"), ("취소", "cancel"), ("입금", "account_balance_wallet"),
         ("수수료", "percent"), ("입고", "move_to_inbox"), ("달성", "flag"), ("목표", "flag")]

CSS = f"""
/* ---- 글: 숫자는 자리 폭을 맞추고, 한글은 단어 단위로 줄바꿈 ---- */
.stApp {{ font-variant-numeric: tabular-nums; word-break: keep-all; text-rendering: optimizeLegibility; }}

/* ---- 여백: 본문을 넓게 쓰고 요소 사이를 띄운다 ---- */
.stMainBlockContainer {{ padding: 4rem 3rem 4rem; max-width: 1680px; }}
.stMainBlockContainer > [data-testid="stVerticalBlock"] {{ gap: 1.25rem; }}      /* 화면 최상위만 (달력 같은 중첩 격자는 그대로) */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0.45rem; }}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {{ gap: 0.4rem; }}

/* ---- 제목 ---- */
h1 {{ color: {INK}; letter-spacing: -0.025em; line-height: 1.2; padding-bottom: 0.15rem; text-wrap: balance; }}
h2, h3 {{ color: {INK}; letter-spacing: -0.015em; text-wrap: balance; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{ color: {MUTED}; opacity: 1 !important; }}   /* 기본 캡션은 투명도 0.6이라 대비가 2.4:1 */

/* ---- 면 공통: 그림자 대신 가는 선. 종이 위에 놓은 장부 칸처럼 ---- */
[class*="st-key-kpi-"], .st-key-filterbar, [data-testid="stForm"], [data-testid="stExpander"] details {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; box-shadow: none;
}}

/* ---- 지표 칸: 라벨은 작게, 숫자는 크게. 아이콘은 오른쪽 위에 먹색 선으로만 ---- */
[class*="st-key-kpi-"] {{ position: relative; flex: 1 1 0; min-width: 0; align-self: stretch; padding: 0.85rem 1.1rem 0.9rem;
  display: flex; flex-direction: column; justify-content: center; }}
[class*="st-key-kpi-"] [data-testid="stElementContainer"]:has(.kpi-chip) {{ position: absolute; right: 0.9rem; top: 0.8rem; width: auto; }}
[class*="st-key-kpi-"] [data-testid="stMetric"] {{ text-align: left; align-items: flex-start; }}
[class*="st-key-kpi-"] [data-testid="stMetricLabel"] {{ color: {MUTED}; font-weight: 600; font-size: 0.87rem; justify-content: flex-start; }}
[class*="st-key-kpi-"] [data-testid="stMetricValue"], [class*="st-key-kpi-"] [data-testid="stMetricDelta"] {{ justify-content: flex-start; }}
[class*="st-key-kpi-"] [data-testid="stMetricDelta"] > div {{ white-space: normal; overflow: visible; text-overflow: clip; }}
[class*="st-key-kpi-"] [data-testid="stMetricValue"] {{ color: {INK}; font-size: 1.75rem; letter-spacing: -0.02em; }}
.kpi-chip {{ display: inline-flex; align-items: center; justify-content: center; }}
.kpi-chip span {{ font-family: "Material Symbols Rounded", "Material Symbols Outlined"; font-size: 1.35rem; line-height: 1;
  font-weight: normal; font-variation-settings: "FILL" 0, "wght" 300; opacity: 0.85; }}

/* ---- 달력 날짜 버튼: 좁은 칸에서도 숫자가 꺾이지 않게 ---- */
[class*="st-key-day_"] button {{ white-space: nowrap; min-width: 0; padding: 0.15rem 0.6rem; min-height: 1.9rem; }}

/* ---- 필터 바 ---- */
.st-key-filterbar {{ padding: 1rem 1.25rem; }}

/* ---- 표 ---- */
[data-testid="stDataFrame"] {{ border-radius: 8px; overflow: hidden; }}

/* ---- 탭 ---- */
[data-baseweb="tab-list"] {{ gap: 0.25rem; }}
button[data-baseweb="tab"] {{ padding: 0.55rem 1rem; font-weight: 600; border-radius: 6px 6px 0 0; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: {ACCENT}; background: {TINT}; }}
[data-baseweb="tab-highlight"] {{ background-color: {ACCENT}; height: 3px; }}
[data-baseweb="tab-panel"] {{ padding-top: 1.1rem; }}

/* ---- 버튼 ---- */
.stMainBlockContainer button[kind="primary"] {{ box-shadow: none; font-weight: 600; letter-spacing: -0.005em; }}
.stMainBlockContainer button[kind="secondary"] {{ border-color: {LINE}; background: {SURFACE}; }}

/* ---- 사이드바: 종이보다 한 겹 진한 바탕. 선택된 메뉴는 녹색 ---- */
[data-testid="stSidebar"] {{ border-right: 1px solid {LINE}; box-shadow: none; }}
[data-testid="stSidebar"] button[kind="tertiary"] {{ color: #34433A; }}
[data-testid="stSidebar"] button[kind="tertiary"]:hover {{ background: {TINT}; color: {ACCENT}; }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ background: transparent; border: 0; box-shadow: none; }}   /* 메뉴 묶음은 테두리 없이 (버튼 안에 또 테두리 상자를 겹치지 않는다) */

/* style 만 담은 st.html 이 빈 줄을 만들지 않게 */
[data-testid="stHtml"]:has(> style) {{ display: none; }}
"""


def inject():
    """모든 화면 맨 위에서 한 번 호출."""
    st.html(f"<style>{CSS}</style>")


def kpi_chip(label: str, index: int) -> str:
    """지표 라벨에서 어울리는 아이콘을 골라 먹색 선 아이콘 HTML 로 만든다 (모르는 라벨은 일반 차트 아이콘)."""
    icon = next((ic for key, ic in ICONS if key in label), "analytics")
    fg, bg = CHIPS[index % len(CHIPS)]
    return f'<div class="kpi-chip" style="background:{bg};color:{fg}"><span>{icon}</span></div>'
