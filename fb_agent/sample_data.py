"""POS·근태 연동 전까지 화면을 채우는 샘플 데이터 (Streamlit 비의존).

날짜·매장으로 시드를 고정해서 새로고침해도 같은 값이 나오고, 매장마다 다른 값이 나온다.
실제 연동 시 이 모듈의 함수들을 데이터 소스 조회로 교체하면 된다.
"""
import zlib
from functools import lru_cache
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config
import real_sales as rs

STORE_SCALE = {"강남점": 1.0, "홍대점": 0.8, "판교점": 1.2, "수원점": 1.2}
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


# ---- 실제 매출 연결 (FB_MASTER=real) ----
# 수원점의 실제 매출이 있는 날(2025-12)은 real_sales 의 값을, 그 밖의 날짜·매장은 아래 가상 규칙을 쓴다.
# 가상 값의 메뉴·결제 구성비는 실제 12월 구성비를 따라 한 화면에서 어색하지 않게 한다.
def _real_mode() -> bool:
    return config.MASTER_MODE == "real" and rs.available()


def _real(store: str, d: date | None = None) -> bool:
    return _real_mode() and store == rs.REAL_STORE and (d is None or rs.has(d))


def _real_total(store: str, d: date) -> bool:
    """영수증 단위가 아니라 일자별 합계만 실제인 날(2026-01~09). 일 매출·정산은 실제, 시간대·메뉴·결제·영수증은 그 합계에 맞춘 가상 값."""
    return _real_mode() and store == rs.REAL_STORE and rs.has_total(d)


@lru_cache(maxsize=1)
def _real_mix() -> tuple[list, list]:
    """실제 12월 매출의 (메뉴 [(이름, 평균단가, 비중)], 결제 [(이름, 비중)])."""
    s = rs.sales_rows()
    label = rs._menu_label(s)
    g = s.groupby(label).agg(수량=("수량", "sum"), 매출=("순매출", "sum"))
    order = [*rs.menu_names(), "기타"]
    g = g.reindex(order).fillna(0)
    menus = [(n, max(1, int(g.loc[n, "매출"] / max(1, g.loc[n, "수량"]))), float(g.loc[n, "매출"] / g["매출"].sum())) for n in order]
    p = s.groupby("결제")["순매출"].sum().reindex(rs.PAY_NAMES, fill_value=0)
    return menus, [(n, float(p[n] / p.sum())) for n in rs.PAY_NAMES]


# 실제 데이터가 없는 날(2025-12 밖, 다른 매장)의 가상 매출: 실제 12월의 요일별 중앙값 × 월별 계절 × 공휴일 × 매장 규모 × 날짜별 잡음.
HOLIDAYS = {date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18), date(2026, 3, 1), date(2026, 3, 2),
            date(2026, 5, 5), date(2026, 5, 24), date(2026, 5, 25), date(2026, 6, 6), date(2026, 8, 15), date(2026, 8, 17),
            date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26), date(2026, 10, 3), date(2026, 10, 5), date(2026, 10, 9),
            date(2025, 12, 25), date(2026, 12, 25)}                       # 설날·삼일절·어린이날·석가탄신일·현충일·광복절·추석·개천절·한글날·성탄(대체휴일 포함)
HOLIDAY_FACTOR = 1.15
SEASON = {1: .92, 2: .90, 3: .95, 4: .97, 5: 1.0, 6: .95, 7: .93, 8: .93, 9: .97, 10: 1.0, 11: .97, 12: 1.0}   # 12월(실제) 대비
REAL_STORE_SCALE = {"수원점": 1.0, "강남점": 1.1, "홍대점": 0.85}


@lru_cache(maxsize=1)
def _real_profile() -> dict:
    """실제 12월에서 뽑은 요일별 (순매출, 객수) 중앙값과 평일/주말 시간대 비중. 성탄절은 특수일이라 제외."""
    d = rs.daily()
    d = d[[x != date(2025, 12, 25) for x in d.index]]
    wd = pd.Series([x.weekday() for x in d.index], index=d.index)
    sales = d["순매출"].groupby(wd).median()
    cust = d["객수"].groupby(wd).median()
    hours = {}
    for kind, days in (("wk", [x for x in d.index if x.weekday() < 5]), ("we", [x for x in d.index if x.weekday() >= 5])):
        tot = sum(rs.hourly(x, OPEN_HOURS)["sales"].to_numpy() for x in days).astype(float)
        hours[kind] = tot / tot.sum()
    return {"sales": sales.to_dict(), "customers": cust.to_dict(), "hours": hours}


def _virtual_real_day(store: str, d: date) -> dict:
    prof = _real_profile()
    r = _rng(store, d.toordinal(), "real-virtual")
    base = prof["sales"][d.weekday()] * REAL_STORE_SCALE.get(store, 1.0) * SEASON[d.month]
    if d in HOLIDAYS:
        base *= HOLIDAY_FACTOR
    sales = base * r.uniform(0.9, 1.1)
    ticket = prof["sales"][d.weekday()] / max(1, prof["customers"][d.weekday()]) * r.uniform(0.95, 1.05)
    return {"date": d, "sales": int(round(sales, -3)), "customers": int(sales / ticket), "ticket": int(ticket)}


def menus() -> list:
    return _real_mix()[0] if _real_mode() else MENUS


def payments() -> list:
    return _real_mix()[1] if _real_mode() else PAYMENTS


def day_sales(store: str, d: date) -> dict:
    """하루 매출·객수."""
    if _real(store, d):
        row = rs.daily().loc[d]
        return {"date": d, "sales": int(row["순매출"]), "customers": int(row["객수"]),
                "ticket": int(row["순매출"] / max(1, row["객수"]))}
    if _real_total(store, d):
        row = rs.totals_2026().loc[d]
        return {"date": d, "sales": int(row["순매출"]), "customers": int(row["객수"]),
                "ticket": int(row["순매출"] / row["객수"]) if row["객수"] else 0}
    if _real_mode():
        return _virtual_real_day(store, d)
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


def _band_weights(d: date, base) -> "np.ndarray":
    """OPEN_HOURS 별 비중: 월별 정산의 구간(10~13시·14~17시·18~21시) 실매출 비중 × 구간 안 base 모양. 영업시간(11~21시)은 세 구간에 모두 들어간다."""
    share = rs.settle_band_share(d)
    w = np.zeros(len(OPEN_HOURS))
    for (lo, hi), v in share.items():
        idx = [i for i, h in enumerate(OPEN_HOURS) if lo <= h <= hi]
        if idx:
            w[idx] = v * base[idx] / base[idx].sum()
    return w


def hourly_sales(store: str, d: date) -> pd.DataFrame:
    """시간대별 매출·객수."""
    if _real(store, d):
        return rs.hourly(d, OPEN_HOURS)
    day = day_sales(store, d)
    r = _rng(store, d.toordinal(), "hour")
    base = _real_profile()["hours"]["we" if d.weekday() >= 5 else "wk"] if _real_mode() else HOUR_PROFILE
    if _real_total(store, d) and rs.has_settle(d):
        base = _band_weights(d, base)      # 그 달 실제 시간대 구간 비중에 맞추고, 구간 안은 12월 시간대 모양을 쓴다
    w = base * r.uniform(0.85, 1.15, len(OPEN_HOURS))
    w = w / w.sum()
    sales = (day["sales"] * w).round(-2)
    return pd.DataFrame({"hour": OPEN_HOURS, "sales": sales.astype(int),
                         "customers": (sales / max(1, day["ticket"])).astype(int)})


def menu_table(store: str, start: date, end: date) -> pd.DataFrame:
    """기간 내 메뉴별 판매수량·매출·비중."""
    if _real_mode():
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        t = sum((_menu_day(store, d) for d in days), _menu_day(store, days[0]) * 0)
        df = pd.DataFrame({"메뉴": t.index, "단가": [p for _n, p, _s in menus()],
                           "판매수량": t["수량"].astype(int).values, "매출": t["매출"].astype(int).values})
        df["비중(%)"] = (df["매출"] / max(1, df["매출"].sum()) * 100).round(1)
        df = pd.concat([df[df["메뉴"] != "기타"].sort_values("매출", ascending=False), df[df["메뉴"] == "기타"]])   # '기타'는 마지막
        return df.reset_index(drop=True)
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
    if _real_mode():
        return _real_menu_series(store, end, by, n)
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


@lru_cache(maxsize=4096)
def _menu_day(store: str, d: date) -> pd.DataFrame:
    """그날 메뉴별 수량·매출 (실제 날은 실제 값, 아니면 실제 구성비로 나눈 가상 값)."""
    names = [m[0] for m in menus()]
    if _real(store, d):
        return rs.menu_day(d).reindex(names, fill_value=0)
    sales = day_sales(store, d)["sales"]
    r = _rng(store, d.toordinal(), "menu").uniform(0.9, 1.1, len(names))
    amt = np.array([sales * share for _n, _p, share in menus()]) * r
    qty = amt / np.array([p for _n, p, _s in menus()])
    return pd.DataFrame({"수량": qty.round(), "매출": amt.round(-2)}, index=names)


def _real_menu_series(store: str, end: date, by: str, n: int) -> pd.DataFrame:
    names = [m[0] for m in menus()]
    if by == "hour":
        if _real(store, end):
            p = rs.menu_hour(end, OPEN_HOURS).reindex(columns=names, fill_value=0)
            return p.set_index(p.index.astype(str) + "시")
        h = hourly_sales(store, end)
        return pd.DataFrame({m: (h["sales"] * s).round(-2) for m, _p, s in menus()}).set_index(h["hour"].astype(str) + "시")
    if by == "day":
        days = [end - timedelta(days=i) for i in range(n - 1, -1, -1)]
        out = pd.DataFrame({d.strftime("%m-%d"): _menu_day(store, d)["매출"] for d in days}).T
        return out[names]
    mth = monthly_sales(store, end, n)
    rows = {}
    for m in mth["month"]:
        y, mo = int(m[:4]), int(m[5:])
        last = min(end, (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)))
        total = sum((_menu_day(store, date(y, mo, k))["매출"] for k in range(1, last.day + 1)), _menu_day(store, date(y, mo, 1))["매출"] * 0)
        rows[m] = total
    return pd.DataFrame(rows).T[names]


@lru_cache(maxsize=4096)
def _pay_day(store: str, d: date) -> dict:
    """그날 결제수단별 금액 (실제 날은 실제 값, 아니면 실제 구성비로 나눈 가상 값)."""
    if _real(store, d):
        return rs.pay_amounts(d)
    sales = day_sales(store, d)["sales"]
    if _real_total(store, d) and rs.has_settle(d):
        return {n: int(sales * share) for n, share in rs.settle_pay_mix(d).items()}      # 그 달 실제 결제수단 구성비
    r = _rng(store, d.toordinal(), "pay").uniform(0.95, 1.05, len(payments()))
    return {n: int(sales * share * x) for (n, share), x in zip(payments(), r)}


def _pay_totals(store: str, start: date, end: date) -> dict:
    out = {n: 0 for n, _s in payments()}
    for i in range((end - start).days + 1):
        for n, v in _pay_day(store, start + timedelta(days=i)).items():
            out[n] += v
    return out


def payment_share(store: str, start: date, end: date) -> pd.DataFrame:
    if _real_mode():
        df = pd.DataFrame({"결제수단": [n for n, _s in payments()], "금액": list(_pay_totals(store, start, end).values())})
        df["비중(%)"] = (df["금액"] / max(1, df["금액"].sum()) * 100).round(1)
        return df
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
    if _real_mode():
        idx = pd.to_datetime([end - timedelta(days=i) for i in range(days - 1, -1, -1)])
        vals = [_pay_day(store, x.date()).get(method, 0) for x in idx]
        return pd.DataFrame({"일자": idx, "금액": vals}).set_index("일자")
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
    df = pd.DataFrame(rows)
    if _real(store):
        lo = end - timedelta(days=29)
        df = df[~df["일시"].str[:10].map(lambda x: rs.has(date.fromisoformat(x)))]       # 실제 날짜는 아래 실제 행으로 대체
        real = rs.cancellations(lo, end)
        if len(real):
            rr = _rng(store, end.toordinal(), "cancel-meta")                           # 원본에 없는 사유·처리자는 가상
            real = real.assign(사유=[str(rr.choice(CANCEL_REASONS)) for _ in range(len(real))],
                               처리자=[STAFF[int(rr.integers(0, len(STAFF)))][0] for _ in range(len(real))])
            df = pd.concat([df, real[df.columns]], ignore_index=True)
    return df.sort_values("일시", ascending=False).reset_index(drop=True)


def receipts(store: str, d: date, n: int = 30) -> pd.DataFrame:
    if _real(store, d):
        return rs.receipts(d)
    if _real_total(store, d) and rs.totals_2026().loc[d, "영수증수"] == 0:
        return pd.DataFrame(columns=["영수증번호", "시각", "테이블", "금액", "결제수단"])
    r = _rng(store, d.toordinal(), "receipt")
    rows = []
    for i in range(n):
        items = r.integers(1, 5)
        amount = int(sum(menus()[int(r.integers(0, len(menus())))][1] * int(r.integers(1, 3)) for _ in range(items)))
        rows.append({"영수증번호": f"R{d:%m%d}{1000 + i}", "시각": f"{int(r.choice(OPEN_HOURS)):02d}:{int(r.integers(0, 60)):02d}",
                     "테이블": f"T{int(r.integers(1, 21))}", "금액": amount,
                     "결제수단": str(r.choice([p[0] for p in payments()], p=[p[1] for p in payments()]))})
    return pd.DataFrame(rows).sort_values("시각").reset_index(drop=True)


def receipt_lines(store: str, d: date, receipt_no: str) -> pd.DataFrame:
    if _real(store, d):
        return rs.receipt_lines(d, receipt_no)
    r = _rng(store, d.toordinal(), receipt_no)
    rows = []
    for _ in range(int(r.integers(1, 5))):
        name, price, _s = menus()[int(r.integers(0, len(menus())))]
        qty = int(r.integers(1, 3))
        rows.append({"메뉴": name, "단가": price, "수량": qty, "금액": price * qty})
    return pd.DataFrame(rows)


def settlement(store: str, end: date, days: int = 7) -> pd.DataFrame:
    """일자별 정산: 총매출·할인·순매출·부가세."""
    d = daily_sales(store, end, days)
    r = _rng(store, end.toordinal(), "settle")
    disc = (d["sales"] * r.uniform(0.01, 0.03, len(d))).round(-2).astype(int)
    net = d["sales"] - disc
    out = pd.DataFrame({"일자": d["date"].dt.strftime("%Y-%m-%d"), "총매출": d["sales"], "할인": disc,
                        "순매출": net, "부가세": (net / 11).round(-1).astype(int)})
    if _real(store):
        real = rs.daily()
        for i, day in enumerate(d["date"].dt.date):
            if day in real.index:
                out.loc[out.index[i], ["총매출", "할인", "순매출", "부가세"]] = [int(real.loc[day, c]) for c in ("총매출", "할인", "순매출", "부가세")]
            elif _real_total(store, day):
                t = rs.totals_2026()
                out.loc[out.index[i], ["총매출", "할인", "순매출", "부가세"]] = [int(t.loc[day, c]) for c in ("총매출", "할인", "순매출", "부가세")]
    return out


def settlement_by_channel(store: str, end: date) -> pd.DataFrame:
    s = settlement(store, end, 7)
    pay = _pay_totals(store, end - timedelta(days=6), end) if _real_mode() else None
    rows = []
    for name, share in payments():
        net = int(pay[name] if pay else s["순매출"].sum() * share)
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
