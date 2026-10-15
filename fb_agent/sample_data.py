"""POS·근태 연동 전까지 화면을 채우는 샘플 데이터 (Streamlit 비의존).

날짜·매장으로 시드를 고정해서 새로고침해도 같은 값이 나오고, 매장마다 다른 값이 나온다.
실제 연동 시 이 모듈의 함수들을 데이터 소스 조회로 교체하면 된다.
"""
import zlib
from functools import lru_cache
from datetime import date, timedelta

import numpy as np
import pandas as pd

STORE_SCALE = {"강남점": 1.0, "홍대점": 0.8, "판교점": 1.2}
WEEKDAY_FACTOR = [0.85, 0.9, 0.95, 1.0, 1.15, 1.35, 1.25]          # 월~일
OPEN_HOURS = list(range(11, 22))                                    # 11시~21시
HOUR_PROFILE = np.array([.08, .16, .14, .06, .04, .04, .07, .14, .15, .08, .04])
BASE_DAILY_SALES = 4_200_000
AVG_TICKET = 21_000
SEATS = 60

MENUS = [("짜장면", 9000, .24), ("짬뽕", 10000, .18), ("탕수육", 22000, .15), ("볶음밥", 9500, .12),
         ("군만두", 6000, .10), ("깐풍기", 24000, .08), ("음료", 2000, .13)]
PAYMENTS = [("신용카드", .62), ("간편결제", .23), ("현금", .10), ("상품권·기타", .05)]

STAFF = [("김민준", "정직원", 13_000), ("이서연", "정직원", 12_500), ("박지호", "정직원", 12_000),
         ("최유나", "파트타임", 10_500), ("정도윤", "파트타임", 10_500), ("한소희", "파트타임", 10_030),
         ("오세훈", "파트타임", 10_030), ("윤하늘", "파트타임", 10_030),
         ("강지우", "정직원", 12_000), ("조현우", "정직원", 12_500), ("신예린", "정직원", 11_500),
         ("임태양", "파트타임", 10_030), ("배수아", "파트타임", 10_030), ("송민재", "파트타임", 10_030)]
SHIFTS = {"오": ("오전", 11, 16), "후": ("오후", 16, 22), "풀": ("종일", 11, 22), "휴": ("휴무", 0, 0)}
HOURLY_SALES_PER_STAFF = 330_000     # 직원 1명이 1시간에 감당하는 매출(적정 인력 산정 기준)


def _rng(*parts) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32("|".join(map(str, parts)).encode()))


def _scale(store: str) -> float:
    return STORE_SCALE.get(store, 1.0)


def day_sales(store: str, d: date) -> dict:
    """하루 매출·객수."""
    r = _rng(store, d.toordinal())
    trend = 1 + 0.0004 * (d.toordinal() - date(2026, 1, 1).toordinal())
    sales = BASE_DAILY_SALES * _scale(store) * WEEKDAY_FACTOR[d.weekday()] * trend * r.uniform(0.9, 1.1)
    ticket = AVG_TICKET * r.uniform(0.95, 1.05)
    return {"date": d, "sales": int(round(sales, -3)), "customers": int(sales / ticket), "ticket": int(ticket)}


def daily_sales(store: str, end: date, days: int = 90) -> pd.DataFrame:
    rows = [day_sales(store, end - timedelta(days=i)) for i in range(days - 1, -1, -1)]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["turnover"] = (df["customers"] / SEATS).round(2)      # 회전율 = 객수 / 좌석수
    return df


def monthly_sales(store: str, end: date, months: int = 12) -> pd.DataFrame:
    df = daily_sales(store, end, days=months * 31 + 31)
    df["month"] = df["date"].dt.to_period("M")
    m = df.groupby("month").agg(sales=("sales", "sum"), customers=("customers", "sum"),
                                days=("date", "count")).reset_index().tail(months)
    m["month"] = m["month"].astype(str)
    return m


def hourly_sales(store: str, d: date) -> pd.DataFrame:
    """시간대별 매출·객수."""
    day = day_sales(store, d)
    r = _rng(store, d.toordinal(), "hour")
    w = HOUR_PROFILE * r.uniform(0.85, 1.15, len(OPEN_HOURS))
    w = w / w.sum()
    sales = (day["sales"] * w).round(-2)
    return pd.DataFrame({"hour": OPEN_HOURS, "sales": sales.astype(int),
                         "customers": (sales / day["ticket"]).astype(int)})


def menu_table(store: str, start: date, end: date) -> pd.DataFrame:
    """기간 내 메뉴별 판매수량·매출·비중."""
    total = int(daily_sales(store, end, (end - start).days + 1)["sales"].sum())
    rows = []
    for name, price, share in MENUS:
        r = _rng(store, name, start.toordinal(), end.toordinal())
        qty = max(1, int(total * share * r.uniform(0.95, 1.05) / price))
        rows.append({"메뉴": name, "단가": price, "판매수량": qty, "매출": qty * price})
    df = pd.DataFrame(rows)
    df["비중(%)"] = (df["매출"] / df["매출"].sum() * 100).round(1)
    return df.sort_values("매출", ascending=False).reset_index(drop=True)


def menu_series(store: str, end: date, by: str, n: int) -> pd.DataFrame:
    """메뉴별 시계열(wide). by: 'day' | 'month' | 'hour'."""
    cols = [m[0] for m in MENUS]
    if by == "hour":
        h = hourly_sales(store, end)
        data = {m: (h["sales"] * s).round(-2) for m, _, s in MENUS}
        return pd.DataFrame(data).set_index(h["hour"].astype(str) + "시")
    if by == "day":
        d = daily_sales(store, end, n)
        data = {m: (d["sales"] * s * _rng(store, m, "d").uniform(0.9, 1.1, len(d))).round(-2) for m, _, s in MENUS}
        return pd.DataFrame(data).set_index(d["date"].dt.strftime("%m-%d"))
    mth = monthly_sales(store, end, n)
    data = {m: (mth["sales"] * s * _rng(store, m, "m").uniform(0.9, 1.1, len(mth))).round(-3) for m, _, s in MENUS}
    return pd.DataFrame(data).set_index(mth["month"])


def payment_share(store: str, start: date, end: date) -> pd.DataFrame:
    total = int(daily_sales(store, end, (end - start).days + 1)["sales"].sum())
    rows = []
    for name, share in PAYMENTS:
        r = _rng(store, name, end.toordinal())
        amt = int(total * share * r.uniform(0.95, 1.05))
        rows.append({"결제수단": name, "금액": amt})
    df = pd.DataFrame(rows)
    df["비중(%)"] = (df["금액"] / df["금액"].sum() * 100).round(1)
    return df


def payment_daily(store: str, end: date, method: str, days: int = 30) -> pd.DataFrame:
    share = dict(PAYMENTS)[method]
    d = daily_sales(store, end, days)
    r = _rng(store, method, "daily").uniform(0.9, 1.1, len(d))
    return pd.DataFrame({"일자": d["date"], "금액": (d["sales"] * share * r).round(-2).astype(int)}).set_index("일자")


CANCEL_TYPES = ["매출취소", "매출변환", "주문취소", "메뉴취소"]
CANCEL_REASONS = ["고객 변심", "주문 오류", "조리 지연", "결제수단 변경", "메뉴 품절", "직원 실수"]


def cancellations(store: str, end: date, n: int = 40) -> pd.DataFrame:
    r = _rng(store, end.toordinal(), "cancel")
    rows = []
    for i in range(n):
        d = end - timedelta(days=int(r.integers(0, 30)))
        t = f"{int(r.choice(OPEN_HOURS)):02d}:{int(r.integers(0, 60)):02d}"
        rows.append({"일시": f"{d:%Y-%m-%d} {t}", "영수증번호": f"R{d:%m%d}{int(r.integers(1000, 9999))}",
                     "유형": str(r.choice(CANCEL_TYPES, p=[.3, .15, .3, .25])),
                     "금액": int(r.integers(2, 60)) * 1000, "사유": str(r.choice(CANCEL_REASONS)),
                     "처리자": STAFF[int(r.integers(0, len(STAFF)))][0]})
    return pd.DataFrame(rows).sort_values("일시", ascending=False).reset_index(drop=True)


def receipts(store: str, d: date, n: int = 30) -> pd.DataFrame:
    r = _rng(store, d.toordinal(), "receipt")
    rows = []
    for i in range(n):
        items = r.integers(1, 5)
        amount = int(sum(MENUS[int(r.integers(0, len(MENUS)))][1] * int(r.integers(1, 3)) for _ in range(items)))
        rows.append({"영수증번호": f"R{d:%m%d}{1000 + i}", "시각": f"{int(r.choice(OPEN_HOURS)):02d}:{int(r.integers(0, 60)):02d}",
                     "테이블": f"T{int(r.integers(1, 21))}", "금액": amount,
                     "결제수단": str(r.choice([p[0] for p in PAYMENTS], p=[p[1] for p in PAYMENTS]))})
    return pd.DataFrame(rows).sort_values("시각").reset_index(drop=True)


def receipt_lines(store: str, d: date, receipt_no: str) -> pd.DataFrame:
    r = _rng(store, d.toordinal(), receipt_no)
    rows = []
    for _ in range(int(r.integers(1, 5))):
        name, price, _s = MENUS[int(r.integers(0, len(MENUS)))]
        qty = int(r.integers(1, 3))
        rows.append({"메뉴": name, "단가": price, "수량": qty, "금액": price * qty})
    return pd.DataFrame(rows)


def settlement(store: str, end: date, days: int = 7) -> pd.DataFrame:
    """일자별 정산: 총매출·할인·순매출·부가세."""
    d = daily_sales(store, end, days)
    r = _rng(store, end.toordinal(), "settle")
    disc = (d["sales"] * r.uniform(0.01, 0.03, len(d))).round(-2).astype(int)
    net = d["sales"] - disc
    return pd.DataFrame({"일자": d["date"].dt.strftime("%Y-%m-%d"), "총매출": d["sales"], "할인": disc,
                         "순매출": net, "부가세": (net / 11).round(-1).astype(int)})


def settlement_by_channel(store: str, end: date) -> pd.DataFrame:
    s = settlement(store, end, 7)
    rows = []
    for name, share in PAYMENTS:
        net = int(s["순매출"].sum() * share)
        fee = {"신용카드": .015, "간편결제": .02, "현금": 0.0, "상품권·기타": .03}[name]
        rows.append({"결제채널": name, "순매출": net, "수수료율(%)": fee * 100, "수수료": int(net * fee),
                     "입금예정액": net - int(net * fee)})
    return pd.DataFrame(rows)


def salmon_receiving(store: str, end: date, n: int = 10) -> pd.DataFrame:
    r = _rng(store, end.toordinal(), "salmon")
    rows = []
    for i in range(n):
        d = end - timedelta(days=int(r.integers(0, 28)))
        kg = round(float(r.uniform(4, 15)), 1)
        price = int(r.integers(26, 34)) * 1000
        rows.append({"입고일": f"{d:%Y-%m-%d}", "거래처": str(r.choice(["A식자재", "B유통"])), "품목": "생연어(필렛)",
                     "수량(kg)": kg, "단가(원/kg)": price, "금액": int(kg * price),
                     "검수": str(r.choice(["합격", "합격", "합격", "재검"]))})
    return pd.DataFrame(rows).sort_values("입고일", ascending=False).reset_index(drop=True)


# ---- 인력 ----
@lru_cache(maxsize=64)
def month_schedule(store: str, year: int, month: int) -> pd.DataFrame:
    """직원 × 일자 근무 코드(오/후/풀/휴). 같은 인자는 캐시하므로 반환값을 수정하지 말 것."""
    import calendar
    days = calendar.monthrange(year, month)[1]
    rows = {}
    for si, (name, kind, _w) in enumerate(STAFF):
        r = _rng(store, name, year, month)
        codes = []
        for d in range(1, days + 1):
            wd = date(year, month, d).weekday()
            if kind == "정직원":
                code = "휴" if (d + si) % 7 in (0, 1) else "풀"
            else:
                code = "휴" if r.random() < 0.45 else str(r.choice(["오", "후"]))
            if wd >= 5 and kind == "파트타임" and code == "휴" and r.random() < .6:
                code = "후"                        # 주말은 파트 보강
            codes.append(code)
        rows[name] = codes
    df = pd.DataFrame(rows, index=range(1, days + 1)).T
    df.columns = [f"{d}" for d in range(1, days + 1)]
    return df


def staffing_by_hour(store: str, d: date) -> pd.DataFrame:
    """시간대별 적정 인력(매출 기준) vs 배치 인력(스케줄 기준)."""
    sched = month_schedule(store, d.year, d.month)[str(d.day)]
    placed = []
    for h in OPEN_HOURS:
        n = 0
        for code in sched:
            _, s, e = SHIFTS[code]
            n += 1 if s <= h < e else 0
        placed.append(n)
    h = hourly_sales(store, d)
    need = np.ceil(h["sales"] / HOURLY_SALES_PER_STAFF).astype(int).clip(lower=2)
    return pd.DataFrame({"시간": [f"{x}시" for x in OPEN_HOURS], "적정 인력": need.values, "배치 인력": placed})


def punch_records(store: str, end: date, days: int = 7) -> pd.DataFrame:
    rows = []
    for i in range(days):
        d = end - timedelta(days=i)
        sched = month_schedule(store, d.year, d.month)[str(d.day)]
        for name, kind, _w in STAFF:
            code = sched[name]
            if code == "휴":
                continue
            _, s, e = SHIFTS[code]
            r = _rng(store, name, d.toordinal(), "punch")
            cin = s * 60 + int(r.integers(-8, 12))
            cout = e * 60 + int(r.integers(-5, 25))
            rows.append({"일자": f"{d:%Y-%m-%d}", "직원": name, "구분": kind, "근무": SHIFTS[code][0],
                         "출근": f"{cin // 60:02d}:{cin % 60:02d}", "퇴근": f"{cout // 60:02d}:{cout % 60:02d}",
                         "근무시간": round((cout - cin) / 60, 1)})
    return pd.DataFrame(rows)


def labor_cost(store: str, end: date, days: int = 30) -> pd.DataFrame:
    """일자별 인건비와 매출 대비 인건비율(L%)."""
    sales = daily_sales(store, end, days)
    wage = {n: w for n, _k, w in STAFF}
    rows = []
    for _, row in sales.iterrows():
        d = row["date"].date()
        sched = month_schedule(store, d.year, d.month)[str(d.day)]
        cost = 0
        for name, code in sched.items():
            _, s, e = SHIFTS[code]
            cost += (e - s) * wage[name]
        rows.append({"date": row["date"], "sales": row["sales"], "labor": int(cost)})
    df = pd.DataFrame(rows)
    df["L%"] = (df["labor"] / df["sales"] * 100).round(1)
    return df


def today_staff_count(store: str, d: date) -> int:
    sched = month_schedule(store, d.year, d.month)[str(d.day)]
    return int((sched != "휴").sum())
