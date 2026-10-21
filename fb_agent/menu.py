"""좌측 네비게이션 메뉴 정의 (Streamlit 비의존).

구조: 레일(아이콘) → 대메뉴 → 중메뉴 → 소메뉴(Leaf, 화면 하나).
소메뉴의 view 키가 views 패키지의 렌더러와 연결되고, arg 로 같은 렌더러를 변형해서 쓴다.
"""
from dataclasses import dataclass

from config import STORES  # noqa: F401  (매장 목록은 마스터 종류에 따라 config 에서 정함)

FAV_RAIL = "fav"


@dataclass(frozen=True)
class Leaf:
    id: str            # URL 경로로도 쓰이는 영문 슬러그
    title: str
    view: str          # 렌더러 키 (views.REGISTRY)
    arg: str = ""      # 렌더러에 넘기는 변형 값


@dataclass(frozen=True)
class Mid:
    title: str
    leaves: tuple


@dataclass(frozen=True)
class Major:
    title: str
    en: str
    mids: tuple


@dataclass(frozen=True)
class Rail:
    id: str
    icon: str
    label: str
    majors: tuple = ()


def _mid(title, *leaves):
    return Mid(title, tuple(Leaf(*lf) for lf in leaves))


RAILS = (
    Rail("home", ":material/home:", "홈", (
        Major("홈", "Home", (
            _mid("대시보드", ("home-dashboard", "달력 대시보드", "home.dashboard")),
        )),
        Major("F&B AI 에이전트", "AI Assistant", (
            _mid("AI 운영 분석",
                 ("ai-report", "매출 및 재고 리포트 요약", "ai.report"),
                 ("ai-alerts", "이상징후 알림", "ai.alerts")),
            _mid("Q&A 대화창",
                 ("ai-chat-order", "발주 추천", "ai.chat", "발주 추천"),
                 ("ai-chat-leadtime", "리드타임 조회", "ai.chat", "리드타임 조회"),
                 ("ai-chat-schedule", "스케줄 조정 문의", "ai.chat", "스케줄 조정 문의")),
        )),
    )),
    Rail(FAV_RAIL, ":material/star:", "즐겨찾기"),
    Rail("sales", ":material/payments:", "매출", (
        Major("매출분석", "Sales Analysis", (
            _mid("매출요약",
                 ("sales-monthly", "월별집계", "sales.monthly"),
                 ("sales-daily", "일자별", "sales.daily"),
                 ("sales-weekday", "요일별", "sales.weekday"),
                 ("sales-hourly", "시간대별", "sales.hourly"),
                 ("sales-realtime", "실시간매출", "sales.realtime"),
                 ("sales-ticket", "객단가 및 회전율", "sales.ticket"),
                 ("sales-cumulative", "누적대비일별매출", "sales.cumulative"),
                 ("sales-compare", "매출비교", "sales.compare"),
                 ("sales-customers", "일자별객수", "sales.customers")),
            _mid("메뉴매출분석",
                 ("menu-status", "판매현황", "menu.status"),
                 ("menu-monthly", "월별집계", "menu.monthly"),
                 ("menu-daily", "일자별", "menu.daily"),
                 ("menu-hourly", "시간대별", "menu.hourly")),
            _mid("결제수단분석",
                 ("pay-card", "신용카드", "pay.method", "신용카드"),
                 ("pay-easy", "간편결제", "pay.method", "간편결제"),
                 ("pay-cash", "현금", "pay.method", "현금"),
                 ("pay-etc", "상품권·기타", "pay.method", "상품권·기타")),
            _mid("매출취소분석",
                 ("cancel-sales", "매출취소", "cancel.table", "매출취소"),
                 ("cancel-convert", "매출변환", "cancel.table", "매출변환"),
                 ("cancel-order", "주문/메뉴취소", "cancel.table", "주문취소,메뉴취소")),
            _mid("매출정산",
                 ("settle-receipts", "매출영수증", "settle.receipts"),
                 ("settle-detail", "매출영수증상세", "settle.detail"),
                 ("settle-report", "정산레포트", "settle.report"),
                 ("settle-pnc", "정산레포트(PNC)", "settle.pnc"),
                 ("settle-salmon", "연어입고", "settle.salmon")),
        )),
    )),
    Rail("purchase", ":material/inventory_2:", "구매/발주", (
        Major("발주 및 재고관리", "Ordering & Inventory", (
            _mid("발주관리",
                 ("po-request", "구매청구", "po.request"),
                 ("po-request-detail", "구매청구 상세내역", "po.request_detail"),
                 ("po-leadtime", "발주 리드타임 관리", "po.leadtime"),
                 ("po-auto", "자동 발주 추천", "po.auto"),
                 ("po-engine", "발주 추천 (이력 기반)", "po.engine")),
            _mid("입고관리",
                 ("recv-by-po", "구매발주서 기준", "recv.by_po"),
                 ("recv-general", "일반입고", "recv.general"),
                 ("recv-detail", "입고 상세내역", "recv.detail"),
                 ("recv-returns", "반품", "recv.returns")),
            _mid("기타입출고",
                 ("io-loss", "손망실 상세내역", "io.loss"),
                 ("io-transfer", "이체 상세내역", "io.transfer"),
                 ("io-transfer-request", "이체요청", "io.transfer_request")),
            _mid("수불관리",
                 ("stock-flow", "수불현황", "stock.flow"),
                 ("stock-input", "매장별 재고입력", "stock.input"),
                 ("stock-history", "매장별 재고입력 이력", "stock.history"),
                 ("stock-forecast", "안전재고/소진율 예측", "stock.forecast")),
        )),
    )),
    Rail("hr", ":material/groups:", "인력/스케줄", (
        Major("인력 및 스케줄 관리", "HR & Scheduling", (
            _mid("근태 및 스케줄",
                 ("hr-schedule", "월간 근무 스케줄표", "hr.schedule"),
                 ("hr-punch", "파트타임/정직원 출퇴근 기록", "hr.punch"),
                 ("hr-swap", "근무 교대 요청", "hr.swap")),
            _mid("인건비 분석",
                 ("hr-staffing", "시간대별 적정 인력 배치", "hr.staffing"),
                 ("hr-labor", "매출 대비 인건비율(L%)", "hr.labor_ratio")),
        )),
    )),
    Rail("settings", ":material/settings:", "설정/계정", (
        Major("설정/계정", "Settings & Account", (
            _mid("매장", ("set-store", "매장 설정 (휴무·기준일)", "set.store"),
                 ("set-items", "품목 마스터", "set.items"),
                 ("set-suppliers", "거래처", "set.suppliers")),
            _mid("화면", ("set-agent", "에이전트 패널", "set.agent")),
            _mid("계정", ("set-account", "프로필·로그인", "set.account")),
        )),
    )),
)

DEFAULT_LEAF = "home-dashboard"


# ---- 조회용 색인 ----
def _index():
    out = {}
    for rail in RAILS:
        for major in rail.majors:
            for mid in major.mids:
                for leaf in mid.leaves:
                    assert leaf.id not in out, f"중복 id: {leaf.id}"
                    out[leaf.id] = (rail, major, mid, leaf)
    return out


_INDEX = _index()


def all_leaves() -> list[Leaf]:
    return [v[3] for v in _INDEX.values()]


def get_leaf(leaf_id: str) -> Leaf:
    return _INDEX[leaf_id][3]


def has_leaf(leaf_id: str) -> bool:
    return leaf_id in _INDEX


def rail_of(leaf_id: str) -> Rail:
    return _INDEX[leaf_id][0]


def rail_by_id(rail_id: str) -> Rail:
    return next(r for r in RAILS if r.id == rail_id)


def breadcrumb(leaf_id: str) -> list[str]:
    _, major, mid, leaf = _INDEX[leaf_id]
    return [major.title, mid.title, leaf.title]


def icon_of(leaf_id: str) -> str:
    rail, major, _mid, _leaf = _INDEX[leaf_id]
    return ":material/smart_toy:" if major.en == "AI Assistant" else rail.icon   # AI 메뉴는 홈 레일에 있지만 로봇 아이콘


# ---- 검색 ----
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"


def _norm(s: str) -> str:
    return "".join(s.lower().split())


def _choseong(s: str) -> str:
    return "".join(_CHO[(ord(c) - 0xAC00) // 588] if "가" <= c <= "힣" else c for c in _norm(s))


def search(query: str, limit: int = 30) -> list[Leaf]:
    """공백으로 나눈 모든 검색어가 (대·중·소 메뉴명, 영문명) 중에 들어 있는 소메뉴.
    검색어가 초성(ㅁㅊ 등)뿐이면 초성으로도 비교."""
    tokens = query.split()
    if not tokens:
        return []
    out = []
    for rail, major, mid, leaf in _INDEX.values():
        hay = _norm(" ".join([major.title, major.en, mid.title, leaf.title]))
        hay_cho = _choseong(" ".join([major.title, mid.title, leaf.title]))
        ok = all(_norm(t) in hay or (all(c in _CHO for c in _norm(t)) and _norm(t) in hay_cho) for t in tokens)
        if ok:
            out.append(leaf)
    return out[:limit]
