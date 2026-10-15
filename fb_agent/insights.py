"""재고 현황 요약 (Streamlit 비의존) - 달력과 에이전트가 같은 계산을 공유."""
from datetime import date

from converter import to_grams
from data import ITEMS, SAMPLE_COUNTS
from errors import InvalidInputError
from models import StoreCalendar
from reorder import Recommendation, recommend


def sample_stock_g() -> dict:
    return {n: to_grams(ITEMS[n], p, l, boxes=b) for n, (b, p, l) in SAMPLE_COUNTS.items()}


def recommendations(stock_g: dict, today: date, cal: StoreCalendar) -> list[Recommendation]:
    """품목별 발주 추천. 등록되지 않았거나 잘못된 값은 건너뜀."""
    out = []
    for name, g in stock_g.items():
        if name not in ITEMS:
            continue
        try:
            out.append(recommend(ITEMS[name], g, today, cal))
        except InvalidInputError:
            continue
    return out
