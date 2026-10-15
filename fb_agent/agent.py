"""F&B Agent 응답 생성 (Streamlit 비의존).

현재는 앱 데이터(재고 추천, 일정)를 바탕으로 한 규칙 기반 응답입니다.
LLM을 붙일 때는 answer()만 교체하면 UI는 그대로 쓸 수 있습니다.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from calendar_data import CATEGORIES, Event
from reorder import Recommendation, fmt_date

QUICK_QUESTIONS = ["지금 발주해야 할 품목은?", "이번 주 일정 알려줘", "재고 현황 요약", "인력·매출 이슈 있어?"]
TOPIC_QUESTIONS = {
    "발주 추천": ["지금 발주해야 할 품목은?", "재고 현황 요약", "발주 입고 일정 알려줘"],
    "리드타임 조회": ["거래처 리드타임 알려줘", "짜사이 리드타임은?", "다음 입고 일정 알려줘"],
    "스케줄 조정 문의": ["오늘 근무 인원은?", "인력 부족한 시간대 있어?", "근무 교대는 어떻게 해?"],
}
STATUS_LABEL = {"URGENT": "긴급", "ORDER_NOW": "지금 발주", "ORDER_SOON": "곧 발주", "OK": "양호", "NO_USAGE": "소비 없음"}

GREETING = ("안녕하세요, F&B Agent입니다. 재고·발주와 매장 일정에 대해 물어보세요.\n\n"
            "아래 추천 질문을 눌러 보셔도 좋아요.")


@dataclass
class AgentContext:
    today: date
    recs: list[Recommendation] = field(default_factory=list)
    events: dict = field(default_factory=dict)   # {날짜: [Event]} (오늘 ~ 앞으로 2주)
    store: str = ""
    sales_note: str = ""                          # 오늘 매출 한 줄 요약
    staff_today: int | None = None                # 오늘 근무 인원
    shortage_hours: list = field(default_factory=list)   # 오늘 인력 부족 시간대 ['12시', ...]


def _has(text: str, *words) -> bool:
    return any(w in text for w in words)


def _events_between(ctx: AgentContext, start: date, end: date, categories=None) -> list[Event]:
    out = [e for d, evs in sorted(ctx.events.items()) if start <= d <= end for e in evs
           if e.category != "closed" and (categories is None or e.category in categories)]
    return out


def _fmt_events(evs: list[Event]) -> str:
    return "\n".join(f"- {fmt_date(e.day)} {CATEGORIES[e.category][2]} **{e.title}**"
                     + (f" — {e.detail}" if e.detail else "") for e in evs)


def answer(prompt: str, ctx: AgentContext) -> str:
    q = prompt.strip()
    if not q:
        return "질문을 입력해 주세요."

    if _has(q, "발주", "주문", "입고"):
        todo = [r for r in ctx.recs if r.status in ("URGENT", "ORDER_NOW", "ORDER_SOON")]
        if not todo:
            return "지금 발주가 필요한 품목은 없어요. 재고가 모두 충분합니다."
        todo.sort(key=lambda r: ["URGENT", "ORDER_NOW", "ORDER_SOON"].index(r.status))
        lines = [f"- **{r.item}** [{STATUS_LABEL[r.status]}] {r.supplier} {r.order_packs}PK · "
                 f"발주 {fmt_date(r.order_date)} → 입고 {fmt_date(r.arrival_date)}" for r in todo]
        return f"발주가 필요한 품목 {len(todo)}개입니다.\n\n" + "\n".join(lines)

    if _has(q, "재고", "소진", "얼마나"):
        if not ctx.recs:
            return "아직 재고 정보가 없어요. '매출/재고 관리' 메뉴에서 실사 재고를 입력하거나 파일을 올려 주세요."
        lines = [f"- **{r.item}** [{STATUS_LABEL[r.status]}] "
                 + ("소비 없음" if r.days_left is None else f"잔여 약 {r.days_left:.1f}일 (소진 {fmt_date(r.stockout_date)})")
                 for r in ctx.recs]
        return "재고 현황입니다.\n\n" + "\n".join(lines)

    if _has(q, "리드타임", "배송", "거래처", "납기"):
        from data import ITEMS, SUPPLIERS
        for name, it in ITEMS.items():                  # 품목명이 들어 있으면 그 품목만
            if name in q:
                s_ = it.supplier
                return (f"**{name}** 는 {s_.name}에서 발주 가능 요일은 {s_.order_days_label}이고, "
                        f"리드타임은 D+{s_.lead_time_days}입니다.")
        lines = [f"- **{s.name}** · 발주 {s.order_days_label} · D+{s.lead_time_days}" for s in SUPPLIERS.values()]
        return "거래처별 리드타임입니다.\n\n" + "\n".join(lines)

    if _has(q, "스케줄", "근무", "교대", "배치"):
        if ctx.staff_today is None:
            return "근무 정보가 아직 없어요. '인력/스케줄' 메뉴에서 월간 근무 스케줄표를 확인해 주세요."
        msg = f"{ctx.store or '이 매장'} 오늘 근무 인원은 **{ctx.staff_today}명**입니다."
        if ctx.shortage_hours:
            msg += f"\n\n인력이 부족한 시간대: {', '.join(ctx.shortage_hours)}. 교대·보강이 필요할 수 있어요."
        else:
            msg += "\n\n시간대별 인력은 적정 수준이에요."
        return msg + "\n\n교대는 '인력/스케줄 > 근무 교대 요청'에서 요청할 수 있어요."

    if "매출" in q and "이슈" not in q:
        return ctx.sales_note or "매출 정보가 아직 없어요."

    if _has(q, "인력", "직원", "매출"):
        cats = tuple(c for c, kw in (("staff", ("인력", "직원")), ("sales", ("매출",))) if _has(q, *kw)) \
            or ("staff", "sales")
        evs = _events_between(ctx, ctx.today, ctx.today + timedelta(days=14), cats)
        return ("앞으로 2주간 확인된 이슈입니다.\n\n" + _fmt_events(evs)) if evs else \
            "앞으로 2주간 등록된 인력·매출 이슈는 없어요."

    if _has(q, "일정", "이벤트", "스케줄", "오늘", "이번 주", "내일"):
        if "오늘" in q:
            start = end = ctx.today
            label = "오늘"
        elif "내일" in q:
            start = end = ctx.today + timedelta(days=1)
            label = "내일"
        else:
            start, end, label = ctx.today, ctx.today + timedelta(days=6), "앞으로 7일"
        evs = _events_between(ctx, start, end)
        return (f"{label} 일정입니다.\n\n" + _fmt_events(evs)) if evs else f"{label} 등록된 일정이 없어요."

    if _has(q, "휴무", "쉬는"):
        closed = [d for d, evs in sorted(ctx.events.items()) if any(e.category == "closed" for e in evs)]
        return ("앞으로 2주간 휴무일: " + ", ".join(fmt_date(d) for d in closed)) if closed else \
            "앞으로 2주간 휴무일이 없어요."

    return ("아직 답변할 수 없는 질문이에요. 지금은 이런 질문에 답할 수 있어요.\n\n"
            "- 발주가 필요한 품목 / 재고 현황\n- 거래처 리드타임\n- 오늘 근무 인원 / 인력 부족 시간대\n"
            "- 오늘 매출\n- 오늘·이번 주 일정, 인력·매출 이슈, 휴무일\n\n"
            "(현재는 앱 데이터 기반 규칙 응답이며, LLM 연동 시 자유 질문도 지원할 수 있어요.)")
