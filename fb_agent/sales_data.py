"""실제 매출 조회 (Streamlit 비의존). 값은 모두 실제 POS 데이터이고, 데이터가 없는 날짜·항목은 빈 표로 돌려준다 (가상 값을 만들지 않는다).

원본
  · 일자별 매출(총매출·실매출·순매출·영수증수): POS `매출분석_일자별` 정제본 data/cleaned/<연도>/매출일자별_정제.csv (2024-01 ~ 2026-09)
  · 객수·시간대·메뉴·결제·취소: 수불부 `매출입력` 영수증 행을 `python -m prep.sales_aggregates` 로 집계한 data/cleaned/매출/*.csv
  · 영수증 단위 조회: 해당 월 수불부 원본(data/source/수불부/<연도>/<월>.md)을 처음 볼 때 읽어서 캐시한다
  · 월별 결제수단 금액: 정산레포트 data/cleaned/<연도>/정산_월별_정제.csv
일 매출·영수증수는 POS 값이고, 시간대·메뉴·결제는 영수증에서 집계한 값이라 일 순매출이 POS와 아주 조금 다른 날이 있다 (965일 중 12일, 합계 0.01%).
좌석 수·수용 인원·수수료율 같은 원본에 없는 값은 쓰지 않는다 (회전율·수수료 화면은 제공하지 않는다).
"""
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
CLEANED = DATA / "cleaned"
AGG = CLEANED / "매출"
SOURCE = DATA / "source" / "수불부"
STORE = "수원점"
PAY_NAMES = ["신용카드", "현금", "상품권·기타"]          # 영수증의 결제수단 글자에서 구분되는 것 (간편결제는 원본에 구분이 없다)
MENU_KEEP = 14                                         # 상위 메뉴 수 (나머지는 '기타')
EMPTY_DAILY = ["date", "sales", "gross", "discount", "vat", "customers", "receipts", "ticket"]


def available() -> bool:
    return (AGG / "일자별.csv").exists() and any(CLEANED.glob("20*/매출일자별_정제.csv"))


def _agg(name: str) -> pd.DataFrame:
    return _agg_cached(name).copy()


@lru_cache(maxsize=8)
def _agg_cached(name: str) -> pd.DataFrame:
    return pd.read_csv(AGG / f"{name}.csv")


@lru_cache(maxsize=1)
def _pos_daily() -> pd.DataFrame:
    """POS 일자별 매출 (영업일만, index=날짜)."""
    parts = [pd.read_csv(f) for f in sorted(CLEANED.glob("20*/매출일자별_정제.csv"))]
    d = pd.concat(parts, ignore_index=True)
    d = d[d["영업여부"] == "영업"].copy()
    d["날짜"] = pd.to_datetime(d["매출일자"]).dt.date
    return d.set_index("날짜")[["총매출", "실매출", "순매출", "영수증수"]]


@lru_cache(maxsize=1)
def _daily_all() -> pd.DataFrame:
    p = _pos_daily()
    c = _agg("일자별").assign(날짜=lambda t: pd.to_datetime(t["날짜"]).dt.date).set_index("날짜")["객수"]
    out = pd.DataFrame({"date": pd.to_datetime(pd.Index(p.index)), "sales": p["순매출"].astype(int).values, "gross": p["총매출"].astype(int).values,
                        "discount": (p["총매출"] - p["실매출"]).astype(int).values, "vat": (p["실매출"] - p["순매출"]).astype(int).values,
                        "customers": c.reindex(p.index).fillna(0).astype(int).values, "receipts": p["영수증수"].astype(int).values}, index=p.index)
    out["ticket"] = (out["sales"] / out["customers"].where(out["customers"] > 0, 1)).where(out["customers"] > 0, 0).astype(int)
    return out.sort_index()


def first_date() -> date:
    return _daily_all().index.min()


def last_date() -> date:
    return _daily_all().index.max()


def anchor(today: date) -> date:
    """화면의 기준일: 오늘이 데이터 끝(마지막 영업일)보다 뒤이면 데이터 끝."""
    return min(today, last_date())


def latest_day(d: date) -> date | None:
    """d 이전(당일 포함)의 마지막 영업일. 없으면 None."""
    idx = _daily_all().index
    idx = idx[idx <= d]
    return idx.max() if len(idx) else None


def day_sales(d: date) -> dict | None:
    """하루 매출·객수. 영업하지 않았거나 데이터가 없는 날은 None."""
    a = _daily_all()
    if d not in a.index:
        return None
    r = a.loc[d]
    return {"date": d, "sales": int(r["sales"]), "customers": int(r["customers"]), "ticket": int(r["ticket"])}


def daily(start: date, end: date) -> pd.DataFrame:
    """[start, end] 의 영업일별 순매출(sales)·총매출·할인·부가세·객수·영수증수·객단가. 영업하지 않은 날은 행이 없다."""
    a = _daily_all()
    out = a[(a.index >= start) & (a.index <= end)].reset_index(drop=True)
    return out if len(out) else pd.DataFrame(columns=EMPTY_DAILY)


def monthly(end: date, months: int = 12) -> pd.DataFrame:
    """end 가 속한 달까지 최근 months 개월: month, sales, customers, days(영업일)."""
    a = _daily_all()
    a = a[a.index <= end]
    g = a.groupby(a["date"].dt.to_period("M")).agg(sales=("sales", "sum"), customers=("customers", "sum"), days=("date", "count")).reset_index().tail(months)
    g["month"] = g["date"].astype(str)
    return g[["month", "sales", "customers", "days"]].reset_index(drop=True)


def hourly(d: date) -> pd.DataFrame:
    """그날 시간대별 순매출·객수 (영수증 시각의 시 기준, 매출이 있는 시간대만)."""
    h = _agg("시간대별")
    h = h[h["날짜"] == f"{d:%Y-%m-%d}"]
    return pd.DataFrame({"hour": h["시"].astype(int).values, "sales": h["순매출"].astype(int).values, "customers": h["객수"].astype(int).values})


def menu_names() -> list[str]:
    """전 기간 순매출 상위 MENU_KEEP개 메뉴 (순매출 순)."""
    g = _agg("메뉴별").groupby("메뉴명")["순매출"].sum()
    return list(g.sort_values(ascending=False).index[:MENU_KEEP])


def _label(s: pd.Series) -> pd.Series:
    keep = set(menu_names())
    return s.where(s.isin(keep), "기타")


def menu_table(start: date, end: date) -> pd.DataFrame:
    """기간 내 메뉴별 판매수량·매출·비중 (상위 메뉴 + 기타). 단가는 매출÷수량의 평균."""
    m = _agg("메뉴별")
    m = m[(m["날짜"] >= f"{start:%Y-%m-%d}") & (m["날짜"] <= f"{end:%Y-%m-%d}")]
    if m.empty:
        return pd.DataFrame(columns=["메뉴", "단가", "판매수량", "매출", "비중(%)"])
    g = m.groupby(_label(m["메뉴명"])).agg(판매수량=("수량", "sum"), 매출=("순매출", "sum")).reset_index().rename(columns={"메뉴명": "메뉴"})
    g["단가"] = (g["매출"] / g["판매수량"].where(g["판매수량"] > 0, 1)).round().astype(int)
    g["비중(%)"] = (g["매출"] / max(1, g["매출"].sum()) * 100).round(1)
    top = g[g["메뉴"] != "기타"].sort_values("매출", ascending=False)
    out = pd.concat([top, g[g["메뉴"] == "기타"]], ignore_index=True)
    return out[["메뉴", "단가", "판매수량", "매출", "비중(%)"]].astype({"판매수량": int, "매출": int})


def menu_series(end: date, by: str, n: int) -> pd.DataFrame:
    """메뉴별 매출 시계열(wide, 열=메뉴). by: 'day'(최근 n일, 영업일만) | 'month'(최근 n개월) | 'hour'(end 하루의 시간대)."""
    names = menu_names()
    if by == "hour":
        h = _agg("메뉴시간별")
        h = h[h["날짜"] == f"{end:%Y-%m-%d}"]
        p = h.pivot_table(index="시", columns="메뉴명", values="순매출", aggfunc="sum", fill_value=0)
        p.index = p.index.astype(str) + "시"
        return p
    m = _agg("메뉴별")
    m["메뉴"] = _label(m["메뉴명"])
    m = m[m["날짜"] <= f"{end:%Y-%m-%d}"]
    if by == "day":
        days = sorted(m["날짜"].unique())[-n:]
        p = m[m["날짜"].isin(days)].pivot_table(index="날짜", columns="메뉴", values="순매출", aggfunc="sum", fill_value=0)
        p.index = [x[5:] for x in p.index]
    else:
        m["월"] = m["날짜"].str[:7]
        months = sorted(m["월"].unique())[-n:]
        p = m[m["월"].isin(months)].pivot_table(index="월", columns="메뉴", values="순매출", aggfunc="sum", fill_value=0)
    cols = [c for c in [*names, "기타"] if c in p.columns]
    return p[cols]


def payment_share(start: date, end: date) -> pd.DataFrame:
    """기간 내 결제수단별 금액·비중 (복합 결제는 첫 결제수단으로 분류)."""
    p = _agg("결제별")
    p = p[(p["날짜"] >= f"{start:%Y-%m-%d}") & (p["날짜"] <= f"{end:%Y-%m-%d}")]
    g = p.groupby("결제")["순매출"].sum().reindex(PAY_NAMES, fill_value=0)
    df = pd.DataFrame({"결제수단": g.index, "금액": g.astype(int).values})
    df["비중(%)"] = (df["금액"] / max(1, df["금액"].sum()) * 100).round(1)
    return df


def payment_daily(end: date, method: str, days: int = 30) -> pd.DataFrame:
    """결제수단 하나의 일자별 금액 (index=일자, 열=금액). 기간 안 영업일만."""
    p = _agg("결제별")
    lo = end - timedelta(days=days - 1)
    p = p[(p["결제"] == method) & (p["날짜"] >= f"{lo:%Y-%m-%d}") & (p["날짜"] <= f"{end:%Y-%m-%d}")]
    out = pd.DataFrame({"금액": p["순매출"].astype(int).values}, index=pd.to_datetime(p["날짜"]).rename("일자"))
    return out.sort_index()


def cancellations(end: date, days: int = 90) -> pd.DataFrame:
    """end 까지 최근 days 일의 취소·정정 내역: 일시, 영수증번호, 유형, 금액 (사유·처리자는 원본에 없다)."""
    c = _agg("취소")
    lo = end - timedelta(days=days - 1)
    c = c[(c["날짜"] >= f"{lo:%Y-%m-%d}") & (c["날짜"] <= f"{end:%Y-%m-%d}")]
    out = pd.DataFrame({"일시": c["날짜"] + " " + c["시각"], "영수증번호": c["영수증번호"], "유형": c["유형"], "금액": c["금액"].astype(int)})
    return out.sort_values("일시", ascending=False).reset_index(drop=True)


def settlement(end: date, days: int = 7) -> pd.DataFrame:
    """일자별 정산: 총매출·할인·순매출·부가세 (최근 days 일 중 영업일)."""
    d = daily(end - timedelta(days=days - 1), end)
    return pd.DataFrame({"일자": d["date"].dt.strftime("%Y-%m-%d"), "총매출": d["gross"], "할인": d["discount"], "순매출": d["sales"], "부가세": d["vat"]})


def settlement_by_payment(month: str) -> pd.DataFrame:
    """정산레포트의 월별 결제수단 금액 (month='2026-09'). 해당 월 정산이 없으면 빈 표."""
    parts = [pd.read_csv(f) for f in sorted(CLEANED.glob("20*/정산_월별_정제.csv"))]
    s = pd.concat(parts, ignore_index=True)
    s = s[s["월"] == month]
    if s.empty:
        return pd.DataFrame(columns=["결제수단", "금액", "비중(%)"])
    r = s.iloc[0]
    names = ["신용카드", "현금", "상품권", "외상", "포인트", "기타결제"]
    df = pd.DataFrame({"결제수단": names, "금액": [int(r[n]) for n in names]})
    df["비중(%)"] = (df["금액"] / max(1, df["금액"].sum()) * 100).round(1)
    return df


# ---------------------------------------------------------------- 영수증 단위 (월 원본을 처음 볼 때 읽는다)
def receipts_available(d: date) -> bool:
    return (SOURCE / f"{d:%Y}" / f"{d:%Y-%m}.md").exists()


@lru_cache(maxsize=3)
def _month_rows(ym: str) -> pd.DataFrame:
    from prep import sales_aggregates as sa
    r = sa.month_rows(SOURCE / ym[:4] / f"{ym}.md")
    return r[r["취소구분"].isin(sa.SALES_KINDS)]


def _day_rows(d: date) -> pd.DataFrame:
    if not receipts_available(d):
        return pd.DataFrame()
    r = _month_rows(f"{d:%Y-%m}")
    return r[r["날짜"] == f"{d:%Y-%m-%d}"]


def receipts(d: date) -> pd.DataFrame:
    """그날 영수증 목록: 영수증번호, 시각, 테이블, 금액, 결제수단."""
    s = _day_rows(d)
    if s.empty:
        return pd.DataFrame(columns=["영수증번호", "시각", "테이블", "금액", "결제수단"])
    g = s.groupby("영수증").agg(시각=("매출시간", "min"), 테이블=("테이블", "first"), 금액=("순매출", "sum"), 결제수단=("결제", "first"))
    g["시각"] = g["시각"].str[:5]
    return g.reset_index().rename(columns={"영수증": "영수증번호"}).sort_values(["시각", "영수증번호"]).reset_index(drop=True)


def receipt_lines(d: date, receipt_no: str) -> pd.DataFrame:
    s = _day_rows(d)
    s = s[s["영수증"] == receipt_no]
    return s[["메뉴명", "단가", "수량", "순매출"]].rename(columns={"메뉴명": "메뉴", "순매출": "금액"}).reset_index(drop=True)
