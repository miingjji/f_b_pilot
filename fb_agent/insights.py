"""재고 현황 요약 (Streamlit 비의존) - 달력과 에이전트가 같은 계산을 공유."""
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

import sales_data as sd
import stock_sim
from config import TEST_MASTER
from converter import to_boxes, to_grams
from data import ITEMS, ITEMS_BY_CODE
from errors import InvalidInputError
from menu import STORES
from models import StoreCalendar
from reorder import Recommendation, recommend


def master_stock_g(day: date | None = None) -> dict:
    """마스터의 현재재고량(품목명 -> 기본단위 수량). 실사 값이 없는 품목은 0 으로 두고, 추천은 입력 전까지 '데이터 없음'으로 본다.
    day 를 주면 마지막 월말 실사 이후의 재고를 시뮬레이션 값(동결한 재고 예측)으로 바꾼다 — 실사를 더 올리지 않으므로 day 아침의 추정 재고."""
    stock = {name: float(it.current_stock or 0) for name, it in ITEMS.items()}
    if day is not None:
        stock |= sim_stock(day)[0]
    return stock


def sim_stock(day: date) -> tuple[dict, dict | None]:
    """({품목명: day 아침 예상 재고}, 정보). 테스트 마스터이거나 쓸 예측이 없으면 ({}, None)."""
    return ({}, None) if TEST_MASTER else stock_sim.sim_stock(day, ITEMS_BY_CODE)


def sim_on_order(day: date) -> dict:
    """{품목명: day 아침 이미 오는 중으로 볼 시뮬레이션 예상 입고(기본단위)}. 테스트 마스터이거나 쓸 예측이 없으면 {}."""
    return {} if TEST_MASTER else stock_sim.sim_inbound(day, ITEMS_BY_CODE)


def sim_stock_note(day: date) -> str:
    """시뮬레이션 재고임을 알리는 한 줄. 쓸 예측이 없으면 빈 문자열."""
    info = sim_stock(day)[1]
    if info is None:
        return ""
    f = lambda d: f"{d.month}월 {d.day}일"
    s = (f"재고는 {f(info['origin'])} 월말 실사에서 {f(info['asof'])} 마감까지 소비·입고를 시뮬레이션한 추정값입니다"
         f"(품목별 오차 약 31%, 시뮬레이션 {info['items']}개 품목).")
    return s + (f" 예측이 {f(info['asof'])}에서 끝나 그 뒤 날짜는 같은 값을 씁니다." if info["clamped"] else "") + " 실사 값을 입력하면 그 값을 씁니다."


TABLE_COLUMNS = ["품목코드", "품목", "분류", "단위", "BOX", "PK", "낱개"]


def build_table(stock_g: dict) -> pd.DataFrame:
    """재고(기본단위) -> 실사 입력 표(BOX/PK/낱개)."""
    rows = []
    for name, it in ITEMS.items():
        box, pk, loose = to_boxes(it, stock_g.get(name, 0.0))
        rows.append({"품목코드": it.code, "품목": name, "분류": it.mid, "단위": it.base_unit,
                     "BOX": float(box), "PK": float(pk), "낱개": float(round(loose, 2))})
    return pd.DataFrame(rows, columns=TABLE_COLUMNS)


def stock_from_table(df: pd.DataFrame) -> tuple[dict, list]:
    """실사 입력 표 -> ({품목명: 기본단위 수량}, [(품목명, 오류 메시지)])."""
    stock, errors = {}, []
    for _, row in df.iterrows():
        it = ITEMS[row["품목"]]
        try:
            stock[it.name] = to_grams(it, row["PK"], row["낱개"], boxes=row["BOX"])
        except InvalidInputError as e:
            errors.append((it.name, str(e)))
    return stock, errors


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
CANCEL_RATIO = 1.5


def build_alerts(store: str, today: date, recs: list[Recommendation]) -> list[Alert]:
    out = []
    for r in recs:
        if r.status == "URGENT":
            out.append(Alert("high", f"{r.item} 재고 긴급", r.message, "po-auto"))

    # 매출: 같은 요일 평균 대비 편차가 큰 영업일 (최근 14일, 최근 90일 평균·표준편차 기준)
    df = sd.daily(today - timedelta(days=89), today)
    if len(df):
        df["wd"] = df["date"].dt.weekday
        stats = df.groupby("wd")["sales"].agg(["mean", "std"])
        for _, row in df[df["date"] > pd.Timestamp(today - timedelta(days=14))].iterrows():
            mean, std = stats.loc[row["wd"], "mean"], stats.loc[row["wd"], "std"]
            if std and abs((row["sales"] - mean) / std) >= Z_LIMIT:
                diff = (row["sales"] - mean) / mean * 100
                out.append(Alert("medium", f"{row['date']:%m/%d} 매출 {'급증' if diff > 0 else '급감'}",
                                 f"같은 요일 평균 대비 {diff:+.0f}% ({int(row['sales']):,}원)", "sales-daily"))

    canc = sd.cancellations(today, 90)
    if len(canc):
        canc["d"] = canc["일시"].str[:10]
        recent = (canc["d"] >= (today - timedelta(days=6)).isoformat()).sum()
        base = (canc["d"] < (today - timedelta(days=6)).isoformat()).sum() / max(1, 83 / 7)
        if base and recent / base >= CANCEL_RATIO:
            out.append(Alert("medium", "매출취소 증가", f"최근 7일 {recent}건 (평소 주당 {base:.0f}건)", "cancel-sales"))
    if not out:
        out.append(Alert("info", "이상징후 없음", "감지된 이상징후가 없어요.", "home-dashboard"))
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(out, key=lambda a: order[a.level])
