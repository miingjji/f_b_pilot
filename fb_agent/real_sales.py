"""실제 매출 조회 (Streamlit 비의존). FB_MASTER=real 일 때 sample_data 가 이 모듈을 먼저 본다.

원본은 `python -m prep`이 만든 data/cleaned/매출입력_정제.csv (딘타이펑 수원점 2025-12-01~31 영수증 행 단위).
매출 기준은 정리 파일과 같다: 취소구분이 `정상`+`매출취소`인 행의 순매출 (판매및할인 시트와 일치하는 기준).
`주문취소`·`메뉴정정`은 매출로 잡지 않고 취소 내역 화면에만 쓴다.

데이터가 없는 날짜·매장은 이 모듈이 아니라 sample_data 의 가상 값이 채운다.
"""
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

CLEANED = Path(__file__).resolve().parent / "data" / "cleaned" / "매출입력_정제.csv"
REAL_STORE = "수원점"
SALES_KINDS = ("정상", "매출취소")
CANCEL_KINDS = {"매출취소": "매출취소", "주문취소": "주문취소", "메뉴정정": "메뉴취소"}   # 원본 구분 -> 화면 유형
PAY_NAMES = ["신용카드", "간편결제", "현금", "상품권·기타"]       # sample_data.PAYMENTS 와 같은 순서
MENU_KEEP = 14                                                 # 상위 메뉴 수 (나머지는 '기타')


def available() -> bool:
    return CLEANED.exists()


def pay_group(text: str) -> str:
    """'신용카드, 상품권-롯데상품권' 같은 복합 결제는 첫 결제수단으로 분류 (금액이 나뉘어 있지 않음)."""
    first = str(text).split(",")[0].strip()
    if first.startswith("신용카드"):
        return "신용카드"
    if first.startswith("현금"):
        return "현금"
    return "상품권·기타"      # 상품권·외상·결제없음


@lru_cache(maxsize=1)
def rows() -> pd.DataFrame:
    d = pd.read_csv(CLEANED, low_memory=False, dtype={"메뉴코드": str})
    d["날짜"] = pd.to_datetime(d["매출일자"]).dt.date
    d["시"] = d["매출시간"].str[:2].astype(int)
    d["결제"] = d["결제수단"].map(pay_group)
    d["영수증"] = d["날짜"].astype(str).str[5:].str.replace("-", "") + d["포스번호"].astype(str) + "-" + d["영수증번호"].astype(str).str.zfill(4)
    return d


@lru_cache(maxsize=1)
def sales_rows() -> pd.DataFrame:
    d = rows()
    return d[d["취소구분"].isin(SALES_KINDS)]


@lru_cache(maxsize=1)
def days() -> frozenset:
    return frozenset(rows()["날짜"].unique())


def has(d: date) -> bool:
    return available() and d in days()


def span() -> tuple[date, date]:
    ds = days()
    return min(ds), max(ds)


@lru_cache(maxsize=1)
def daily() -> pd.DataFrame:
    """일자별 총매출·할인·순매출·부가세·객수·영수증수 (index=date)."""
    s = sales_rows()
    g = s.groupby("날짜").agg(총매출=("총매출", "sum"), 할인=("할인", "sum"), 순매출=("순매출", "sum"), 부가세=("부가세", "sum"))
    first = s.drop_duplicates(["날짜", "포스번호", "영수증번호"])      # 객수는 영수증 첫 행에 한 번만 센다
    g["객수"] = first.groupby("날짜")["객수"].sum()
    g["영수증수"] = first.groupby("날짜").size()
    return g.fillna(0).astype(int)


def hourly(d: date, open_hours: list[int]) -> pd.DataFrame:
    """영업시간 열(open_hours) 기준 시간대별 매출·객수. 범위 밖 시간(10시 등)은 가까운 영업시간에 합친다."""
    s = sales_rows()
    s = s[s["날짜"] == d]
    lo, hi = open_hours[0], open_hours[-1]
    hour = s["시"].clip(lo, hi)
    sales = s.groupby(hour)["순매출"].sum().reindex(open_hours, fill_value=0)
    first = s.drop_duplicates(["포스번호", "영수증번호"])
    cust = first.groupby(first["시"].clip(lo, hi))["객수"].sum().reindex(open_hours, fill_value=0)
    return pd.DataFrame({"hour": open_hours, "sales": sales.astype(int).values, "customers": cust.astype(int).values})


def pay_amounts(d: date) -> dict:
    s = sales_rows()
    g = s[s["날짜"] == d].groupby("결제")["순매출"].sum()
    return {k: int(g.get(k, 0)) for k in PAY_NAMES}


@lru_cache(maxsize=1)
def menu_names() -> list[str]:
    """통합메뉴명 기준 상위 MENU_KEEP개 (순매출 순). 나머지는 '기타'로 묶는다."""
    g = sales_rows().groupby("메뉴명")["순매출"].sum()      # 통합메뉴명은 정리 파일에만 있어, 여기서는 메뉴명을 쓴다
    return list(g.sort_values(ascending=False).index[:MENU_KEEP])


def _menu_label(s: pd.DataFrame) -> pd.Series:
    keep = set(menu_names())
    return s["메뉴명"].where(s["메뉴명"].isin(keep), "기타")


def menu_day(d: date) -> pd.DataFrame:
    """그날 메뉴별 수량·순매출 (index=메뉴명, 열: 수량, 매출)."""
    s = sales_rows()
    s = s[s["날짜"] == d]
    g = s.groupby(_menu_label(s)).agg(수량=("수량", "sum"), 매출=("순매출", "sum"))
    return g


def menu_hour(d: date, open_hours: list[int]) -> pd.DataFrame:
    """그날 시간대(행) × 메뉴(열) 순매출."""
    s = sales_rows()
    s = s[s["날짜"] == d]
    p = s.pivot_table(index=s["시"].clip(open_hours[0], open_hours[-1]), columns=_menu_label(s), values="순매출", aggfunc="sum", fill_value=0)
    return p.reindex(open_hours, fill_value=0)


def receipts(d: date) -> pd.DataFrame:
    s = sales_rows()
    s = s[s["날짜"] == d]
    g = s.groupby("영수증").agg(시각=("매출시간", "min"), 테이블=("테이블", "first"), 금액=("순매출", "sum"), 결제수단=("결제", "first"))
    g["시각"] = g["시각"].str[:5]
    return g.reset_index().rename(columns={"영수증": "영수증번호"}).sort_values(["시각", "영수증번호"]).reset_index(drop=True)


def receipt_lines(d: date, receipt_no: str) -> pd.DataFrame:
    s = sales_rows()
    s = s[(s["날짜"] == d) & (s["영수증"] == receipt_no)]
    return s[["메뉴명", "단가", "수량", "순매출"]].rename(columns={"메뉴명": "메뉴", "순매출": "금액"}).reset_index(drop=True)


def cancellations(start: date, end: date) -> pd.DataFrame:
    """취소·정정 행을 영수증·유형 단위로 묶은 내역 (사유·처리자는 원본에 없음)."""
    r = rows()
    r = r[r["취소구분"].isin(CANCEL_KINDS) & (r["날짜"] >= start) & (r["날짜"] <= end)]
    if r.empty:
        return pd.DataFrame(columns=["일시", "영수증번호", "유형", "금액"])
    r = r.assign(유형=r["취소구분"].map(CANCEL_KINDS))
    g = r.groupby(["영수증", "유형"]).agg(날짜=("날짜", "first"), 시각=("매출시간", "min"), 금액=("순매출", lambda x: int(abs(x.sum())))).reset_index()
    g["일시"] = g["날짜"].astype(str) + " " + g["시각"].str[:5]
    return g.rename(columns={"영수증": "영수증번호"})[["일시", "영수증번호", "유형", "금액"]]
