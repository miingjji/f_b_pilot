"""매출분석: 매출요약 · 메뉴매출 · 결제수단 · 매출취소 · 매출정산 (실제 POS 데이터, 없는 항목은 '데이터 없음')."""
from datetime import timedelta

import pandas as pd
import streamlit as st

import sales_data as sd
from menu import Leaf
from views import register
from views.common import axis_chart, date_range, kpis, no_data, num_cols, pct_delta, sales_anchor, sales_notice, won

DOW_KR = "월화수목금토일"
UNITS = {"매출": "원", "객단가": "원", "객수": "명", "영업일": "일"}


def unit_table(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """표의 숫자 열 이름에 단위를 붙이고(매출(원)·객수(명)…) 천 단위 쉼표를 적용하는 (표, column_config)."""
    out = df.rename(columns={c: f"{c}({u})" for c, u in UNITS.items() if c in df.columns})
    return out, num_cols(*[f"{c}({u})" for c, u in UNITS.items() if c in df.columns])


# ---------------- 매출요약 ----------------
@register("sales.monthly")
def monthly(leaf: Leaf):
    sales_notice()
    m = sd.monthly(sales_anchor(), 12)
    if len(m) < 2:
        return no_data()
    cur, prev = m.iloc[-1], m.iloc[-2]
    kpis([(f"{cur['month']} 매출", won(cur["sales"]), pct_delta(cur["sales"], prev["sales"]) + " 전월 대비"),
          (f"{len(m)}개월 합계", won(m["sales"].sum()), None),
          ("월평균 객수", f"{int(m['customers'].mean()):,}명", None)])
    axis_chart("bar", m, x="month", y="sales", x_label="월", y_label="매출(원)", alt_text="월별 매출")
    out, cfg = unit_table(m.assign(객단가=(m["sales"] / m["customers"]).astype(int)).rename(
        columns={"month": "월", "sales": "매출", "customers": "객수", "days": "영업일"}))
    st.dataframe(out, hide_index=True, width="stretch", alt="월별 매출 집계표", column_config=cfg)


@register("sales.daily")
def daily(leaf: Leaf):
    sales_notice()
    start, end = date_range("기간", 30, "sales_daily_range")
    df = sd.daily(start, end)
    if df.empty:
        return no_data("선택한 기간에 영업일 데이터가 없어요.")
    best = df.loc[df["sales"].idxmax()]
    kpis([("기간 매출", won(df["sales"].sum()), None), ("영업일 평균", won(df["sales"].mean()), f"영업일 {len(df)}일"),
          ("최고 매출일", f"{best['date']:%m-%d}", won(best["sales"]))])
    chart_tab, table_tab = st.tabs([":material/show_chart: 추이", ":material/table: 표"])
    with chart_tab:
        axis_chart("line", df, x="date", y="sales", x_label="일자", y_label="매출(원)", alt_text="일자별 매출 추이", year=True)
    with table_tab:
        tbl, cfg = unit_table(df.assign(일자=df["date"].dt.strftime("%Y-%m-%d"))[["일자", "sales", "customers", "ticket"]]
                              .rename(columns={"sales": "매출", "customers": "객수", "ticket": "객단가"}).sort_values("일자", ascending=False))
        st.dataframe(tbl, hide_index=True, width="stretch", alt="일자별 매출표", column_config=cfg)


@register("sales.weekday")
def weekday(leaf: Leaf):
    sales_notice()
    end = sales_anchor()
    df = sd.daily(end - timedelta(days=89), end)
    if df.empty:
        return no_data()
    g = df.groupby(df["date"].dt.weekday).agg(매출=("sales", "mean"), 객수=("customers", "mean")).round(0)
    g.index = [f"{DOW_KR[i]}요일" for i in g.index]
    kpis([("가장 높은 요일", g["매출"].idxmax(), won(g["매출"].max())),
          ("가장 낮은 요일", g["매출"].idxmin(), won(g["매출"].min()))])
    st.caption("최근 90일 영업일 기준 요일별 평균 (쉬는 날은 평균에서 제외)")
    axis_chart("bar", g["매출"], y_label="평균 매출(원)", alt_text="요일별 평균 매출")
    tbl, cfg = unit_table(g.astype(int).reset_index(names="요일"))
    st.dataframe(tbl, hide_index=True, width="stretch", alt="요일별 평균표", column_config=cfg)


@register("sales.hourly")
def hourly(leaf: Leaf):
    sales_notice()
    d = st.date_input("일자", value=sales_anchor(), min_value=sd.first_date(), max_value=sd.last_date(), key="sales_hourly_day")
    h = sd.hourly(d)
    if h.empty:
        return no_data("이 날은 영업 기록이 없어요.")
    peak = h.loc[h["sales"].idxmax()]
    kpis([("일 매출", won(h["sales"].sum()), None), ("피크 시간", f"{int(peak['hour'])}시", won(peak["sales"]))])
    chart_tab, table_tab = st.tabs([":material/bar_chart: 시간대 차트", ":material/table: 표"])
    with chart_tab:
        axis_chart("bar", h.assign(시간=h["hour"].astype(str) + "시"), x="시간", y="sales", y_label="매출(원)", alt_text="시간대별 매출")
    with table_tab:
        tbl, cfg = unit_table(h.rename(columns={"hour": "시", "sales": "매출", "customers": "객수"}))
        st.dataframe(tbl, hide_index=True, width="stretch", alt="시간대별 매출표", column_config=cfg)


@register("sales.realtime")
def realtime(leaf: Leaf):
    sales_notice()
    st.info("실시간 매출은 POS 실시간 연동 후 제공됩니다. 아래는 마지막 영업일의 시간대별 누적 매출입니다.", icon=":material/info:")
    last = sd.last_date()
    prev = last - timedelta(days=7)
    t, w = sd.hourly(last), sd.hourly(prev)
    if t.empty:
        return no_data()
    hours = list(range(int(t["hour"].min()), int(t["hour"].max()) + 1))
    t_cum = t.set_index("hour")["sales"].reindex(hours, fill_value=0).cumsum()
    w_cum = w.set_index("hour")["sales"].reindex(hours, fill_value=0).cumsum() if not w.empty else None
    kpis([(f"{last:%m-%d} 마감 매출", won(t_cum.iloc[-1]), (pct_delta(t_cum.iloc[-1], w_cum.iloc[-1]) + f" {prev:%m-%d} 대비") if w_cum is not None else None),
          ("객수", f"{int(t['customers'].sum()):,}명", None)])
    chart = pd.DataFrame({f"{last:%m-%d}": t_cum.values, **({f"{prev:%m-%d}": w_cum.values} if w_cum is not None else {})}, index=[f"{x}시" for x in hours])
    axis_chart("line", chart, y_label="누적 매출(원)", alt_text="마지막 영업일 누적 매출")


@register("sales.ticket")
def ticket(leaf: Leaf):
    sales_notice()
    end = sales_anchor()
    df = sd.daily(end - timedelta(days=29), end)
    if df.empty:
        return no_data()
    kpis([("평균 객단가", won(df.loc[df["customers"] > 0, "ticket"].mean()), None)])
    st.caption("회전율은 좌석 수 데이터가 없어 제공하지 않습니다.")
    axis_chart("line", df, x="date", y="ticket", x_label="일자", y_label="객단가(원)", alt_text="일자별 객단가", year=True)


@register("sales.cumulative")
def cumulative(leaf: Leaf):
    sales_notice()
    today = sales_anchor()
    first = today.replace(day=1)
    df = sd.daily(first, today)
    prev_end = first - timedelta(days=1)
    prev = sd.daily(prev_end.replace(day=1), prev_end)
    if df.empty or prev.empty:
        return no_data("이번 달과 지난달 데이터가 모두 있어야 비교할 수 있어요.")
    target = st.slider("이번 달 목표 (전월 대비)", 90, 130, 105, format="%d%%", key="cum_target") / 100 * prev["sales"].sum()
    cum = df["sales"].cumsum()
    kpis([("누적 매출", won(cum.iloc[-1]), None), ("월 목표", won(target), None),
          ("달성률", f"{cum.iloc[-1] / target * 100:.1f}%", f"{today.day}일차")])
    chart = pd.DataFrame({"누적": cum.values, "일별": df["sales"].values}, index=df["date"].dt.strftime("%m-%d"))
    axis_chart("area", chart["누적"], y_label="누적(원)", alt_text="이번 달 누적 매출", year=f"{today.year}년")
    axis_chart("bar", chart["일별"], y_label="일별(원)", alt_text="이번 달 일별 매출", year=f"{today.year}년")


@register("sales.compare")
def compare(leaf: Leaf):
    sales_notice()
    today = sales_anchor()
    preset = st.segmented_control("비교", ["이번 주 vs 지난 주", "이번 달 vs 지난 달"], default="이번 주 vs 지난 주",
                                  key="cmp_preset") or "이번 주 vs 지난 주"
    if preset.startswith("이번 주"):
        a_start = today - timedelta(days=today.weekday())
        b_start, n = a_start - timedelta(days=7), today.weekday() + 1
    else:
        a_start = today.replace(day=1)
        b_end = a_start - timedelta(days=1)
        b_start, n = b_end.replace(day=1), today.day
    a, b = sd.daily(a_start, a_start + timedelta(days=n - 1)), sd.daily(b_start, b_start + timedelta(days=n - 1))
    if a.empty or b.empty:
        return no_data("비교할 두 기간의 데이터가 모두 있어야 해요.")
    kpis([("현재 기간", won(a["sales"].sum()), pct_delta(a["sales"].sum(), b["sales"].sum()) + " 비교 기간 대비"),
          ("비교 기간", won(b["sales"].sum()), None),
          ("객수 증감", f"{int(a['customers'].sum() - b['customers'].sum()):+,}명", None)])
    cur = pd.Series(a["sales"].values, index=a["date"].dt.date.map(lambda x: (x - a_start).days + 1))
    old = pd.Series(b["sales"].values, index=b["date"].dt.date.map(lambda x: (x - b_start).days + 1))
    chart = pd.DataFrame({"현재": cur, "비교": old}).reindex(range(1, n + 1)).fillna(0)
    chart.index = [f"{i}일차" for i in chart.index]
    axis_chart("bar", chart, stack=False, y_label="매출(원)", alt_text="기간별 매출 비교 (쉬는 날은 0)")


@register("sales.customers")
def customers(leaf: Leaf):
    sales_notice()
    start, end = date_range("기간", 30, "sales_cust_range")
    df = sd.daily(start, end)
    if df.empty:
        return no_data("선택한 기간에 영업일 데이터가 없어요.")
    kpis([("총 객수", f"{int(df['customers'].sum()):,}명", None), ("영업일 평균", f"{df['customers'].mean():,.0f}명", None)])
    axis_chart("line", df, x="date", y="customers", x_label="일자", y_label="객수(명)", alt_text="일자별 객수", year=True)


# ---------------- 메뉴매출분석 ----------------
@register("menu.status")
def menu_status(leaf: Leaf):
    sales_notice()
    start, end = date_range("기간", 30, "menu_range")
    t = sd.menu_table(start, end)
    if t.empty:
        return no_data("선택한 기간에 메뉴 판매 데이터가 없어요.")
    kpis([("메뉴 매출 합계", won(t["매출"].sum()), None), ("1위 메뉴", t.iloc[0]["메뉴"], f"{t.iloc[0]['비중(%)']}%")])
    chart_tab, table_tab = st.tabs([":material/bar_chart: 메뉴별 매출", ":material/table: 판매현황표"])
    with chart_tab:
        st.bar_chart(t[t["메뉴"] != "기타"], x="메뉴", y="매출", horizontal=True, sort="-매출",
                     alt="메뉴별 매출 (기타 제외)")        # '기타'(나머지 메뉴 묶음)는 막대가 너무 길어 표에서만 보여 준다
    with table_tab:
        st.dataframe(t, hide_index=True, width="stretch", alt="메뉴별 판매현황",
                     column_config={**num_cols("단가", "판매수량", "매출"),
                                    "비중(%)": st.column_config.ProgressColumn("비중(%)", min_value=0, max_value=40, format="%.1f")})


def _menu_series(by: str, n: int, label: str, key: str):
    sales_notice()
    df = sd.menu_series(sales_anchor(), by, n)
    if df.empty:
        return no_data()
    picked = st.pills("메뉴", list(df.columns), selection_mode="multi", default=list(df.columns), key=key) or list(df.columns)
    axis_chart("bar", df[picked], y_label="매출(원)", alt_text=f"메뉴별 {label} 매출")
    st.dataframe(df[picked].astype(int).reset_index(names=label), hide_index=True, width="stretch",
                 alt=f"메뉴별 {label} 매출표", column_config=num_cols(*picked))


@register("menu.monthly")
def menu_monthly(leaf: Leaf):
    _menu_series("month", 12, "월", "menu_m_pick")


@register("menu.daily")
def menu_daily(leaf: Leaf):
    _menu_series("day", 14, "일자", "menu_d_pick")


@register("menu.hourly")
def menu_hourly(leaf: Leaf):
    _menu_series("hour", 0, "시간", "menu_h_pick")


# ---------------- 결제수단분석 ----------------
@register("pay.method")
def pay_method(leaf: Leaf):
    sales_notice("결제")
    method = leaf.arg
    if method not in sd.PAY_NAMES:
        return no_data(f"'{method}'는 원본 영수증에 결제수단 구분이 없어 제공하지 않습니다.")
    start, end = date_range("기간", 30, "pay_range")
    share = sd.payment_share(start, end)
    if share["금액"].sum() == 0:
        return no_data("선택한 기간에 결제 데이터가 없어요.")
    me = share[share["결제수단"] == method].iloc[0]
    kpis([(f"{method} 결제액", won(me["금액"]), f"비중 {me['비중(%)']}%"), ("전체 결제액", won(share["금액"].sum()), None)])
    st.caption("복합 결제(예: 신용카드+상품권)는 영수증의 첫 결제수단으로 분류했어요 (결제수단별 금액이 원본에 나뉘어 있지 않아요).")
    c1, c2 = st.columns(2)
    c1.markdown("**결제수단별 비중**")
    with c1:
        axis_chart("bar", share, x="결제수단", y="금액", alt_text="결제수단별 결제액")
    c2.markdown(f"**{method} 일자별 추이**")
    pd_ = sd.payment_daily(end, method, (end - start).days + 1)
    with c2:
        axis_chart("line", pd_, alt_text=f"{method} 일자별 결제액", year=True)
    st.dataframe(share, hide_index=True, width="stretch", alt="결제수단별 비중표", column_config=num_cols("금액"))


# ---------------- 매출취소분석 ----------------
@register("cancel.table")
def cancel_table(leaf: Leaf):
    sales_notice("취소내역")
    st.caption("최근 90일 내역입니다. 취소 사유·처리자는 원본에 없어 제공하지 않아요.")
    types = leaf.arg.split(",")
    df = sd.cancellations(sales_anchor(), 90)
    df = df[df["유형"].isin(types)]
    kpis([("건수", f"{len(df)}건", None), ("취소 금액", won(df["금액"].sum()), None)])
    if df.empty:
        return no_data("해당 유형의 내역이 없어요.")
    st.dataframe(df, hide_index=True, width="stretch", alt=f"{leaf.title} 내역", column_config=num_cols("금액"))


# ---------------- 매출정산 ----------------
@register("settle.receipts")
def settle_receipts(leaf: Leaf):
    sales_notice("영수증")
    d = st.date_input("일자", value=sales_anchor(), min_value=sd.first_date(), max_value=sd.last_date(), key="rcpt_day")
    df = sd.receipts(d)
    if df.empty:
        return no_data("이 날은 영수증이 없어요.")
    pays = st.pills("결제수단", sd.PAY_NAMES, selection_mode="multi", key="rcpt_pay") or []
    view = df[df["결제수단"].isin(pays)] if pays else df
    kpis([("영수증", f"{len(view)}건", None), ("합계", won(view["금액"].sum()), None)])
    st.dataframe(view, hide_index=True, width="stretch", alt="매출 영수증 목록", column_config=num_cols("금액"))


@register("settle.detail")
def settle_detail(leaf: Leaf):
    sales_notice("영수증")
    d = st.date_input("일자", value=sales_anchor(), min_value=sd.first_date(), max_value=sd.last_date(), key="rcpt_d_day")
    df = sd.receipts(d)
    if df.empty:
        return no_data("이 날은 영수증이 없어요.")
    no = st.selectbox("영수증", df["영수증번호"], format_func=lambda n: f"{n} · {df[df['영수증번호'] == n].iloc[0]['시각']}")
    lines = sd.receipt_lines(d, no)
    head = df[df["영수증번호"] == no].iloc[0]
    kpis([("테이블", head["테이블"], None), ("결제수단", head["결제수단"], None), ("품목 합계", won(lines["금액"].sum()), None)])
    st.dataframe(lines, hide_index=True, width="stretch", alt="영수증 상세 품목", column_config=num_cols("단가", "수량", "금액"))


@register("settle.report")
def settle_report(leaf: Leaf):
    sales_notice("정산")
    df = sd.settlement(sales_anchor(), 7)
    if df.empty:
        return no_data()
    kpis([("영업일 순매출", won(df["순매출"].sum()), f"최근 7일 중 영업일 {len(df)}일"), ("할인 합계", won(df["할인"].sum()), None),
          ("부가세 합계", won(df["부가세"].sum()), None)])
    st.dataframe(df, hide_index=True, width="stretch", alt="일자별 정산 레포트",
                 column_config=num_cols("총매출", "할인", "순매출", "부가세"))
    st.download_button("CSV 내려받기", df.to_csv(index=False).encode("utf-8-sig"), "정산레포트.csv", "text/csv",
                       icon=":material/download:")


@register("settle.pnc")
def settle_pnc(leaf: Leaf):
    sales_notice("정산")
    month = f"{sales_anchor():%Y-%m}"
    st.caption(f"{month} 월별 정산레포트의 결제수단별 금액입니다. 결제채널별 수수료·입금예정액은 원본에 없어 제공하지 않아요.")
    df = sd.settlement_by_payment(month)
    if df.empty:
        return no_data("이 달의 정산레포트가 없어요.")
    kpis([("결제 합계", won(df["금액"].sum()), None)])
    st.dataframe(df, hide_index=True, width="stretch", alt="결제수단별 월 정산표", column_config=num_cols("금액"))


@register("settle.salmon")
def settle_salmon(leaf: Leaf):
    sales_notice("입고")
    no_data("연어 입고 내역은 원본 입고 데이터에 별도 구분이 없어 제공하지 않아요. 입고 내역은 구매/발주 메뉴에서 볼 수 있어요.")
