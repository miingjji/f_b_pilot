"""달력 일정 모델과 합성 로직 (Streamlit 비의존)."""
from dataclasses import dataclass
from uuid import uuid4
from datetime import date, timedelta

from errors import InvalidInputError
from models import StoreCalendar
from reorder import Recommendation

# 분류 -> (라벨, 배지 색, 아이콘)
CATEGORIES = {
    "event": ("매장 이벤트", "blue", ":material/celebration:"),
    "sales": ("매출 이슈", "green", ":material/trending_up:"),
    "staff": ("인력 이슈", "violet", ":material/group:"),
    "order": ("발주·입고", "orange", ":material/local_shipping:"),
    "closed": ("휴무", "gray", ":material/event_busy:"),
}
MANUAL_CATEGORIES = ("event", "sales", "staff")  # 사용자가 직접 추가할 수 있는 분류
ORDER_STATUSES = ("URGENT", "ORDER_NOW", "ORDER_SOON")


@dataclass(frozen=True)
class Event:
    day: date
    title: str
    category: str
    detail: str = ""
    id: str = ""          # 수동 일정만 값이 있음 (삭제 가능)
    sample: bool = False  # 데모용 샘플 여부

    @property
    def deletable(self) -> bool:
        return bool(self.id)


def new_event(day: date, category: str, title: str, detail: str = "") -> Event:
    """사용자 입력 -> 수동 일정. 제목이 비었거나 분류가 잘못되면 InvalidInputError."""
    if category not in MANUAL_CATEGORIES:
        raise InvalidInputError(f"직접 추가할 수 없는 분류입니다: {category!r}")
    if not title or not title.strip():
        raise InvalidInputError("제목을 입력해 주세요.")
    return Event(day, title.strip(), category, (detail or "").strip(), id=uuid4().hex[:8])


def sample_events(today: date) -> list[Event]:
    """첫 실행 시 달력이 비어 보이지 않도록 넣는 데모 일정 (기준일 상대)."""
    d = lambda n: today + timedelta(days=n)  # noqa: E731
    return [
        Event(d(0), "오전 재고 실사", "event", "주방·창고 합동 실사", "s0", True),
        Event(d(1), "신메뉴 시식회", "event", "오후 3시, 단골 고객 초청", "s1", True),
        Event(d(3), "주말 프로모션 준비", "event", "배너·POP 교체", "s2", True),
        Event(d(-2), "점심 매출 전주 대비 -18%", "sales", "인근 공사로 유입 감소", "s3", True),
        Event(d(5), "카드 단말기 점검", "sales", "오전 10시 기사 방문", "s4", True),
        Event(d(2), "홀 직원 1명 결근 예정", "staff", "대체 인력 필요", "s5", True),
        Event(d(8), "신규 직원 교육", "staff", "위생 교육 포함", "s6", True),
    ]


def derived_events(recs: list[Recommendation], cal: StoreCalendar, start: date, end: date) -> list[Event]:
    """재고 추천(발주/입고)과 매장 휴무를 일정으로 변환."""
    out = []
    for r in recs:
        if r.status not in ORDER_STATUSES:
            continue
        if r.order_date:
            out.append(Event(r.order_date, f"발주 {r.item} {r.order_packs}PK", "order",
                             f"{r.supplier} · {r.message}"))
        if r.arrival_date:
            out.append(Event(r.arrival_date, f"입고 {r.item}", "order", f"{r.supplier} 입고 예정"))
    d = start
    while d <= end:
        if not cal.is_open(d):
            out.append(Event(d, "휴무", "closed"))
        d += timedelta(days=1)
    return [e for e in out if start <= e.day <= end]


def build_events(custom: list[Event], recs: list[Recommendation], cal: StoreCalendar,
                 start: date, end: date) -> dict[date, list[Event]]:
    """기간 내 모든 일정 -> {날짜: [일정...]} (분류 순서대로 정렬)."""
    order = list(CATEGORIES)
    by_day: dict[date, list[Event]] = {}
    for e in [*custom, *derived_events(recs, cal, start, end)]:
        if start <= e.day <= end:
            by_day.setdefault(e.day, []).append(e)
    for evs in by_day.values():
        evs.sort(key=lambda e: (order.index(e.category) if e.category in order else 99, e.title))
    return by_day


# ---- 달력 셀 크기 추정 (실측값에서 보정한 상수) ----
CELL_GAP = 8          # 열 사이 간격(px)
CELL_PADDING = 36     # 셀 테두리·안쪽 여백
CHAR_PX = 12.5        # 캡션 한글 한 글자 폭
ROW_BASE = 80         # 날짜 버튼 + 여백
LINE_PX = 22
EVENT_GAP = 12
ROW_MIN, ROW_MAX = 100, 320


def cell_width(main_width: float) -> float:
    return (main_width - 6 * CELL_GAP) / 7


def chars_per_line(cell_w: float) -> int:
    return max(3, int((cell_w - CELL_PADDING) / CHAR_PX) - 1)   # -1: 앞의 색 점


def max_cell_events(cell_w: float) -> int:
    return 3 if cell_w >= 150 else 2


def visible_events(shown: list, limit: int) -> tuple[list, int]:
    """셀에 표시할 일정과 숨긴 개수. 넘치면 (limit-1)개 + '+N건'."""
    if len(shown) <= limit:
        return shown, 0
    return shown[:limit - 1], len(shown) - (limit - 1)


def row_height(days: list[tuple[list, int, bool]], cpl: int) -> int:
    """한 주(행)의 셀 높이. days = [(표시할 일정, 숨긴 개수, 휴무 여부), ...] 중 가장 큰 칸에 맞춤."""
    best = 0
    for kept, hidden, closed in days:
        lines = sum(max(1, -(-len(e.title) // cpl)) for e in kept) + (1 if hidden else 0) + (1 if closed else 0)
        best = max(best, ROW_BASE + lines * LINE_PX + len(kept) * EVENT_GAP if lines else ROW_MIN)
    return max(ROW_MIN, min(ROW_MAX, best))
