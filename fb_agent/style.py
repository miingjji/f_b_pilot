"""화면 공통 CSS. 색은 .streamlit/config.toml 의 테마를 따르고, 여기서는 카드·여백·탭·지표 아이콘 같은 모양만 다듬는다.

st.container(key=...) 가 붙이는 `st-key-<키>` 클래스를 선택자로 써서 Streamlit 내부 클래스명에 기대지 않는다.
"""
import streamlit as st

BLUE, LINE, INK, MUTED = "#2563C9", "#E1E7F0", "#1F2A44", "#6B7A94"
# 지표 카드 아이콘 칩 색 (글자색, 배경색). 카드 순서대로 돌려 쓴다.
CHIPS = [("#2563C9", "#E4EDFB"), ("#0E9F94", "#DDF4F1"), ("#E0801A", "#FDEBD6"), ("#7C4DDB", "#EBE3FA"), ("#D9444A", "#FBE4E5")]
ICONS = [("매출", "payments"), ("객단가", "receipt_long"), ("객수", "groups"), ("근무", "badge"), ("인건", "badge"),
         ("긴급", "notification_important"), ("발주", "local_shipping"), ("양호", "task_alt"), ("재고", "inventory_2"),
         ("품목", "inventory_2"), ("일정", "event_available"), ("취소", "cancel"), ("입금", "account_balance_wallet"),
         ("수수료", "percent"), ("입고", "move_to_inbox"), ("달성", "flag"), ("목표", "flag")]

CSS = f"""
/* ---- 여백: 본문을 넓게 쓰고 요소 사이를 띄운다 ---- */
.stMainBlockContainer {{ padding: 5rem 3rem 4rem; max-width: 1680px; }}
.stMainBlockContainer > [data-testid="stVerticalBlock"] {{ gap: 1.4rem; }}      /* 화면 최상위만 (달력 같은 중첩 격자는 그대로) */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0.5rem; }}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {{ gap: 0.4rem; }}

/* ---- 제목 ---- */
h1 {{ color: {INK}; letter-spacing: -0.02em; padding-bottom: 0.25rem; }}
h2, h3 {{ color: {INK}; letter-spacing: -0.01em; }}
[data-testid="stCaptionContainer"] {{ color: {MUTED}; }}

/* ---- 카드 공통 ---- */
[class*="st-key-kpi-"], .st-key-filterbar, [data-testid="stForm"], [data-testid="stExpander"] details {{
  background: #FFFFFF; border: 1px solid {LINE}; border-radius: 14px; box-shadow: 0 1px 3px rgba(31,42,68,.06), 0 4px 14px rgba(31,42,68,.04);
}}

/* ---- KPI 카드: 왼쪽에 고정한 아이콘 칩 + 오른쪽 라벨·값 ---- */
[class*="st-key-kpi-"] {{ position: relative; flex: 1 1 0; min-width: 0; align-self: stretch; padding: 1rem 1.2rem 1rem 5rem;
  display: flex; flex-direction: column; justify-content: center; transition: box-shadow .15s ease; }}
[class*="st-key-kpi-"]:hover {{ box-shadow: 0 2px 6px rgba(31,42,68,.08), 0 10px 24px rgba(31,42,68,.08); }}
[class*="st-key-kpi-"] [data-testid="stElementContainer"]:has(.kpi-chip) {{ position: absolute; left: 1.2rem; top: 50%; transform: translateY(-50%); width: auto; }}
[class*="st-key-kpi-"] [data-testid="stMetric"] {{ text-align: left; align-items: flex-start; }}
[class*="st-key-kpi-"] [data-testid="stMetricLabel"] {{ color: {MUTED}; font-weight: 600; justify-content: flex-start; }}
[class*="st-key-kpi-"] [data-testid="stMetricValue"], [class*="st-key-kpi-"] [data-testid="stMetricDelta"] {{ justify-content: flex-start; }}
[class*="st-key-kpi-"] [data-testid="stMetricDelta"] > div {{ white-space: normal; overflow: visible; text-overflow: clip; }}
[class*="st-key-kpi-"] [data-testid="stMetricValue"] {{ color: {INK}; font-size: 1.7rem; }}
.kpi-chip {{ width: 2.9rem; height: 2.9rem; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; }}
.kpi-chip span {{ font-family: "Material Symbols Rounded", "Material Symbols Outlined"; font-size: 1.6rem; line-height: 1;
  font-weight: normal; font-variation-settings: "FILL" 1; }}

/* ---- 달력 날짜 버튼: 좁은 칸에서도 숫자가 꺾이지 않게 ---- */
[class*="st-key-day_"] button {{ white-space: nowrap; min-width: 0; padding: 0.15rem 0.6rem; min-height: 1.9rem; }}

/* ---- 필터 바 ---- */
.st-key-filterbar {{ padding: 1rem 1.25rem; }}

/* ---- 표 ---- */
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(31,42,68,.06); }}

/* ---- 탭 ---- */
[data-baseweb="tab-list"] {{ gap: 0.5rem; }}
button[data-baseweb="tab"] {{ padding: 0.6rem 1.1rem; font-weight: 600; border-radius: 10px 10px 0 0; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: {BLUE}; background: #E9F0FC; }}
[data-baseweb="tab-highlight"] {{ background-color: {BLUE}; height: 3px; }}
[data-baseweb="tab-panel"] {{ padding-top: 1.25rem; }}

/* ---- 버튼 ---- */
.stMainBlockContainer button[kind="primary"] {{ box-shadow: 0 2px 6px rgba(37,99,201,.28); }}
.stMainBlockContainer button[kind="secondary"] {{ border-color: {LINE}; background: #FFFFFF; }}

/* ---- 사이드바: 흰 배경, 선택된 메뉴는 연한 파랑 ---- */
[data-testid="stSidebar"] {{ border-right: 1px solid {LINE}; box-shadow: 2px 0 14px rgba(31,42,68,.05); }}
[data-testid="stSidebar"] button[kind="tertiary"] {{ color: #44516D; }}
[data-testid="stSidebar"] button[kind="tertiary"]:hover {{ background: #EEF3FB; color: {BLUE}; }}
[data-testid="stSidebar"] [data-testid="stExpander"] details {{ background: #FAFBFD; box-shadow: none; }}

/* style 만 담은 st.html 이 빈 줄을 만들지 않게 */
[data-testid="stHtml"]:has(> style) {{ display: none; }}
"""


def inject():
    """모든 화면 맨 위에서 한 번 호출."""
    st.html(f"<style>{CSS}</style>")


def kpi_chip(label: str, index: int) -> str:
    """지표 라벨에서 어울리는 아이콘을 골라 둥근 색 칩 HTML 로 만든다 (모르는 라벨은 일반 차트 아이콘)."""
    icon = next((ic for key, ic in ICONS if key in label), "analytics")
    fg, bg = CHIPS[index % len(CHIPS)]
    return f'<div class="kpi-chip" style="background:{bg};color:{fg}"><span>{icon}</span></div>'
