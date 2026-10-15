import math
from dataclasses import dataclass
from datetime import date, timedelta
from converter import _check
from models import Item, StoreCalendar, WEEKDAY_KR

SAFETY_DAYS = 1    # 안전재고 일수
COVER_DAYS = 7     # 입고 후 확보할 목표 운영 일수
SOON_DAYS = 2      # 발주 기한까지 이 일수 이하면 ORDER_SOON
SEARCH_DAYS = 60   # 발주 가능일 탐색 범위


@dataclass
class Recommendation:
    item: str
    supplier: str
    status: str                 # URGENT / ORDER_NOW / ORDER_SOON / OK / NO_USAGE
    days_left: float | None
    stockout_date: date | None
    order_date: date | None     # 발주 예정일(기한)
    arrival_date: date | None   # 입고 예정일
    order_packs: int
    shortage_days: int          # 입고 전 예상 결품 일수
    message: str


def fmt_date(d: date | None) -> str:
    return "-" if d is None else f"{d:%m/%d}({WEEKDAY_KR[d.weekday()]})"


def is_order_day(item: Item, d: date, cal: StoreCalendar) -> bool:
    """발주 가능일: 거래처 발주 요일 + 매장 영업일 + 입고일이 매장 영업일."""
    return (d.weekday() in item.supplier.order_weekdays and cal.is_open(d)
            and cal.is_open(d + timedelta(days=item.lead_time_days)))


def order_days(item: Item, start: date, cal: StoreCalendar, n=SEARCH_DAYS) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)
            if is_order_day(item, start + timedelta(days=i), cal)]


def recommend(item: Item, stock_g, today: date | None = None, cal: StoreCalendar | None = None,
              safety_days=SAFETY_DAYS, cover_days=COVER_DAYS) -> Recommendation:
    today = today or date.today()
    cal = cal or StoreCalendar()
    stock = _check(stock_g, "재고(g)")
    usage, lead, sup = item.daily_usage_g, item.lead_time_days, item.supplier.name

    if usage == 0:
        return Recommendation(item.name, sup, "NO_USAGE", None, None, None, None, 0, 0,
                              "소비 없음 - 발주 불필요")

    days_left = stock / usage
    stockout = today + timedelta(days=math.floor(days_left))
    deadline = stockout - timedelta(days=safety_days)   # 이 날까지는 입고되어야 안전
    candidates = order_days(item, today, cal)

    def packs_for(order_d: date) -> int:
        until_arrival = (order_d - today).days + lead
        need = usage * (until_arrival + safety_days + cover_days) - stock
        return max(1, math.ceil(need / item.pk_weight_g))

    if not candidates:
        return Recommendation(item.name, sup, "URGENT", days_left, stockout, None, None, 1, 0,
                              f"{SEARCH_DAYS}일 내 발주 가능일 없음 - 거래처/휴무 설정 확인")

    safe = [d for d in candidates if d + timedelta(days=lead) <= deadline]
    if stock == 0 or not safe:
        # 안전하게 맞출 수 없음 -> 가장 빠른 발주일에 긴급 발주
        first = candidates[0]
        arrival = first + timedelta(days=lead)
        gap = max(0, (arrival - stockout).days)
        where = "오늘" if first == today else fmt_date(first)
        return Recommendation(item.name, sup, "URGENT", days_left, stockout, first, arrival,
            packs_for(first), gap,
            f"긴급! 소진 {fmt_date(stockout)} vs 입고 {fmt_date(arrival)} -> 약 {gap}일 결품 예상. "
            f"{where} {sup}에 발주 + 긴급배송 요청")

    last = safe[-1]   # 안전 입고를 맞출 수 있는 마지막 발주일
    arrival = last + timedelta(days=lead)
    packs = packs_for(last)
    wait = (last - today).days
    if wait == 0:
        return Recommendation(item.name, sup, "ORDER_NOW", days_left, stockout, last, arrival, packs, 0,
                              f"오늘 {sup}에 발주 ({packs} PK), 입고 {fmt_date(arrival)}")
    if wait <= SOON_DAYS:
        return Recommendation(item.name, sup, "ORDER_SOON", days_left, stockout, last, arrival, packs, 0,
                              f"{fmt_date(last)}까지 발주 ({packs} PK), 다음 발주 가능일은 늦음")
    return Recommendation(item.name, sup, "OK", days_left, stockout, last, arrival, 0, 0,
                          f"충분. 발주 기한 {fmt_date(last)}")
