"""재고 현황 요약 (Streamlit 비의존) - 달력과 에이전트가 같은 계산을 공유."""
from dataclasses import dataclass
from datetime import date, timedelta

import sample_data as sd
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


# ---- 이상징후 ----
@dataclass(frozen=True)
class Alert:
    level: str        # high | medium | info
    title: str
    detail: str
    leaf: str         # 이동할 소메뉴 id


Z_LIMIT = 1.6
LABOR_LIMIT = 30.0
CANCEL_RATIO = 1.5


def build_alerts(store: str, today: date, recs: list[Recommendation]) -> list[Alert]:
    out = []
    for r in recs:
        if r.status == "URGENT":
            out.append(Alert("high", f"{r.item} 재고 긴급", r.message, "po-auto"))

    # 매출: 같은 요일 평균 대비 편차가 큰 날 (최근 14일)
    df = sd.daily_sales(store, today, 90)
    df["wd"] = df["date"].dt.weekday
    stats = df.groupby("wd")["sales"].agg(["mean", "std"])
    for _, row in df.tail(14).iterrows():
        mean, std = stats.loc[row["wd"], "mean"], stats.loc[row["wd"], "std"]
        if std and abs((row["sales"] - mean) / std) >= Z_LIMIT:
            diff = (row["sales"] - mean) / mean * 100
            out.append(Alert("medium", f"{row['date']:%m/%d} 매출 {'급증' if diff > 0 else '급감'}",
                             f"같은 요일 평균 대비 {diff:+.0f}% ({int(row['sales']):,}원)", "sales-daily"))

    labor = sd.labor_cost(store, today, 7)
    hi = labor[labor["L%"] > LABOR_LIMIT]
    if len(hi):
        out.append(Alert("medium", "인건비율 초과", f"최근 7일 중 {len(hi)}일이 {LABOR_LIMIT:.0f}%를 넘었어요.", "hr-labor"))

    canc = sd.cancellations(store, today)
    canc["d"] = canc["일시"].str[:10]
    recent = (canc["d"] >= (today - timedelta(days=6)).isoformat()).sum()
    base = (canc["d"] < (today - timedelta(days=6)).isoformat()).sum() / max(1, 24 / 7)
    if base and recent / base >= CANCEL_RATIO:
        out.append(Alert("medium", "매출취소 증가", f"최근 7일 {recent}건 (평소 주당 {base:.0f}건)", "cancel-sales"))

    short = sd.staffing_by_hour(store, today)
    gap = short[short["배치 인력"] < short["적정 인력"]]
    if len(gap) >= 2:
        out.append(Alert("medium", "오늘 인력 부족", f"{', '.join(gap['시간'])} 시간대 배치가 부족해요.", "hr-staffing"))
    if not out:
        out.append(Alert("info", "이상징후 없음", "감지된 이상징후가 없어요.", "home-dashboard"))
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(out, key=lambda a: order[a.level])
