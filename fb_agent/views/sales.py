"""매출분석: 매출요약 · 메뉴매출 · 결제수단 · 매출취소 · 매출정산 (샘플 데이터)."""
from datetime import timedelta

import pandas as pd
import streamlit as st

import sample_data as sd
from menu import Leaf
from state import get_store, get_today
from views import register
from views.common import date_range, iso, kpis, num_cols, pct_delta, sales_notice, won

DOW_KR = "월화수목금토일"


# ---------------- 매출요약 ----------------
@register("sales.monthly")
def monthly(leaf: Leaf):
    sales_notice()
    m = sd.monthly_sales(get_store(), get_today(), 12)
    cur, prev = m.iloc[-1], m.iloc[-2]
    kpis([(f"{cur['month']} 매출", won(cur["sales"]), pct_delta(cur["sales"], prev["sales"]) + " 전월 대비"),
          ("12개월 합계", won(m["sales"].sum()), None),
          ("월평균 객수", f"{int(m['customers'].mean()):,}명", None)])
    st.bar_chart(m, x="month", y="sales", x_label="월", y_label="매출(원)", alt="최근 12개월 월별 매출")
    out = m.assign(객단가=(m["sales"] / m["customers"]).astype(int)).rename(
        columns={"month": "월", "sales": "매출", "customers": "객수", "days": "영업일"})
    st.dataframe(out, hide_index=True, width="stretch", alt="월별 매출 집계표",
                 column_config={"매출": st.column_config.NumberColumn(format="%d원"),
                                "객단가": st.column_config.NumberColumn(format="%d원")})


@register("sales.daily")
def daily(leaf: Leaf):
    sales_notice()
    start, end = date_range("기간", 30, "sales_daily_range")
    df = sd.daily_sales(get_store(), end, (end - start).days + 1)
    best = df.loc[df["sales"].idxmax()]
    kpis([("기간 매출", won(df["sales"].sum()), None), ("일평균", won(df["sales"].mean()), None),
          ("최고 매출일", f"{best['date']:%m-%d}", won(best["sales"]))])
    chart_tab, table_tab = st.tabs([":material/show_chart: 추이", ":material/table: 표"])
    with chart_tab:
        st.line_chart(iso(df), x="date", y="sales", x_label="일자", y_label="매출(원)", alt="일자별 매출 추이")
    with table_tab:
        st.dataframe(df.assign(일자=df["date"].dt.strftime("%Y-%m-%d"))[["일자", "sales", "customers", "ticket"]]
                     .rename(columns={"sales": "매출", "customers": "객수", "ticket": "객단가"})
                     .sort_values("일자", ascending=False), hide_index=True, width="stretch", alt="일자별 매출표",
                     column_config=num_cols("매출", "객수", "객단가"))


@register("sales.weekday")
def weekday(leaf: Leaf):
    sales_notice()
    df = sd.daily_sales(get_store(), get_today(), 90)
    g = df.groupby(df["date"].dt.weekday).agg(매출=("sales", "mean"), 객수=("customers", "mean")).round(0)
    g.index = [f"{DOW_KR[i]}요일" for i in g.index]
    kpis([("가장 높은 요일", g["매출"].idxmax(), won(g["매출"].max())),
          ("가장 낮은 요일", g["매출"].idxmin(), won(g["매출"].min()))])
    st.caption("최근 90일 요일별 평균")
    st.bar_chart(g["매출"], y_label="평균 매출(원)", alt="요일별 평균 매출")
    st.dataframe(g.reset_index(names="요일"), hide_index=True, width="stretch", alt="요일별 평균표",
                 column_config=num_cols("매출", "객수"))


@register("sales.hourly")
def hourly(leaf: Leaf):
    sales_notice()
    d = st.date_input("일자", value=get_today(), max_value=get_today(), key="sales_hourly_day")
    h = sd.hourly_sales(get_store(), d)
    peak = h.loc[h["sales"].idxmax()]
    kpis([("일 매출", won(h["sales"].sum()), None), ("피크 시간", f"{int(peak['hour'])}시", won(peak["sales"]))])
    chart_tab, table_tab = st.tabs([":material/bar_chart: 시간대 차트", ":material/table: 표"])
    with chart_tab:
        st.bar_chart(h.assign(시간=h["hour"].astype(str) + "시"), x="시간", y="sales", y_label="매출(원)",
                     alt="시간대별 매출")
    with table_tab:
        st.dataframe(h.rename(columns={"hour": "시", "sales": "매출", "customers": "객수"}), hide_index=True,
                     width="stretch", alt="시간대별 매출표", column_config=num_cols("매출", "객수"))


@register("sales.realtime")
def realtime(leaf: Leaf):
    sales_notice("POS 실시간")
    today = get_today()
    now_h = min(max(pd.Timestamp.now().hour, sd.OPEN_HOURS[0]), sd.OPEN_HOURS[-1])
    t, w = sd.hourly_sales(get_store(), today), sd.hourly_sales(get_store(), today - timedelta(days=7))
    t_cum = t[t["hour"] <= now_h]["sales"].cumsum()
    w_cum = w[w["hour"] <= now_h]["sales"].cumsum()
    st.button("새로고침", icon=":material/refresh:")
    kpis([(f"{now_h}시 기준 누적 매출", won(t_cum.iloc[-1]), pct_delta(t_cum.iloc[-1], w_cum.iloc[-1]) + " 전주 같은 시각"),
          ("누적 객수", f"{int(t[t['hour'] <= now_h]['customers'].sum()):,}명", None)])
    chart = pd.DataFrame({"오늘": t_cum.values, "지난주 같은 요일": w_cum.values},
                         index=[f"{x}시" for x in t[t["hour"] <= now_h]["hour"]])
    st.line_chart(chart, y_label="누적 매출(원)", alt="오늘과 지난주 누적 매출 비교")


@register("sales.ticket")
def ticket(leaf: Leaf):
    sales_notice()
    df = sd.daily_sales(get_store(), get_today(), 30)
    kpis([("평균 객단가", won(df["ticket"].mean()), None), ("평균 회전율", f"{df['turnover'].mean():.2f}회", f"좌석 {sd.SEATS}석 기준")])
    c1, c2 = st.columns(2)
    c1.markdown("**객단가**")
    c1.line_chart(iso(df), x="date", y="ticket", x_label="일자", y_label="원", alt="일자별 객단가")
    c2.markdown("**회전율** (객수 ÷ 좌석수)")
    c2.line_chart(iso(df), x="date", y="turnover", x_label="일자", y_label="회", alt="일자별 회전율")


@register("sales.cumulative")
def cumulative(leaf: Leaf):
    sales_notice()
    today = get_today()
    first = today.replace(day=1)
    df = sd.daily_sales(get_store(), today, (today - first).days + 1)
    prev_end = first - timedelta(days=1)
    prev = sd.daily_sales(get_store(), prev_end, prev_end.day)
    target = st.slider("이번 달 목표 (전월 대비)", 90, 130, 105, format="%d%%", key="cum_target") / 100 * prev["sales"].sum()
    cum = df["sales"].cumsum()
    kpis([("누적 매출", won(cum.iloc[-1]), None), ("월 목표", won(target), None),
          ("달성률", f"{cum.iloc[-1] / target * 100:.1f}%", f"{today.day}일차")])
    chart = pd.DataFrame({"누적": cum.values, "일별": df["sales"].values}, index=df["date"].dt.strftime("%m-%d"))
    st.area_chart(chart["누적"], y_label="누적(원)", alt="이번 달 누적 매출")
    st.bar_chart(chart["일별"], y_label="일별(원)", alt="이번 달 일별 매출")


@register("sales.compare")
def compare(leaf: Leaf):
    sales_notice()
    today = get_today()
    preset = st.segmented_control("비교", ["이번 주 vs 지난 주", "이번 달 vs 지난 달"], default="이번 주 vs 지난 주",
                                  key="cmp_preset") or "이번 주 vs 지난 주"
    if preset.startswith("이번 주"):
        a_start = today - timedelta(days=today.weekday())
        b_start, n = a_start - timedelta(days=7), today.weekday() + 1
    else:
        a_start = today.replace(day=1)
        b_end = a_start - timedelta(days=1)
        b_start, n = b_end.replace(day=1), today.day
    store = get_store()
    a = sd.daily_sales(store, a_start + timedelta(days=n - 1), n)
    b = sd.daily_sales(store, b_start + timedelta(days=n - 1), n)
    kpis([("현재 기간", won(a["sales"].sum()), pct_delta(a["sales"].sum(), b["sales"].sum()) + " 비교 기간 대비"),
          ("비교 기간", won(b["sales"].sum()), None),
          ("객수 증감", f"{int(a['customers'].sum() - b['customers'].sum()):+,}명", None)])
    chart = pd.DataFrame({"현재": a["sales"].values, "비교": b["sales"].values}, index=[f"{i + 1}일차" for i in range(n)])
    st.bar_chart(chart, stack=False, y_label="매출(원)", alt="기간별 매출 비교")


@register("sales.customers")
def customers(leaf: Leaf):
    sales_notice()
    start, end = date_range("기간", 30, "sales_cust_range")
    df = sd.daily_sales(get_store(), end, (end - start).days + 1)
    kpis([("총 객수", f"{int(df['customers'].sum()):,}명", None), ("일평균", f"{df['customers'].mean():.0f}명", None)])
    st.line_chart(iso(df), x="date", y="customers", x_label="일자", y_label="객수", alt="일자별 객수")


# ---------------- 메뉴매출분석 ----------------
@register("menu.status")
def menu_status(leaf: Leaf):
    sales_notice()
    start, end = date_range("기간", 30, "menu_range")
    t = sd.menu_table(get_store(), start, end)
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
    df = sd.menu_series(get_store(), get_today(), by, n)
    picked = st.pills("메뉴", list(df.columns), selection_mode="multi", default=list(df.columns), key=key) or list(df.columns)
    st.bar_chart(df[picked], y_label="매출(원)", alt=f"메뉴별 {label} 매출")
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
    _menu_series("hour", 11, "시간", "menu_h_pick")


# ---------------- 결제수단분석 ----------------
@register("pay.method")
def pay_method(leaf: Leaf):
    sales_notice("결제")
    method = leaf.arg
    start, end = date_range("기간", 30, "pay_range")
    share = sd.payment_share(get_store(), start, end)
    me = share[share["결제수단"] == method].iloc[0]
    kpis([(f"{method} 결제액", won(me["금액"]), f"비중 {me['비중(%)']}%"), ("전체 결제액", won(share["금액"].sum()), None)])
    c1, c2 = st.columns(2)
    c1.markdown("**결제수단별 비중**")
    c1.bar_chart(share, x="결제수단", y="금액", alt="결제수단별 결제액")
    c2.markdown(f"**{method} 일자별 추이**")
    pd_ = sd.payment_daily(get_store(), end, method, (end - start).days + 1)
    pd_.index = pd_.index.strftime("%Y-%m-%d")
    c2.line_chart(pd_, alt=f"{method} 일자별 결제액")
    st.dataframe(share, hide_index=True, width="stretch", alt="결제수단별 비중표", column_config=num_cols("금액"))


# ---------------- 매출취소분석 ----------------
@register("cancel.table")
def cancel_table(leaf: Leaf):
    sales_notice("POS 취소내역")
    types = leaf.arg.split(",")
    df = sd.cancellations(get_store(), get_today())
    df = df[df["유형"].isin(types)]
    kpis([("건수", f"{len(df)}건", None), ("취소 금액", won(df["금액"].sum()), None)])
    if df.empty:
        st.caption("해당 기간에 내역이 없어요.")
        return
    reason = df.groupby("사유")["금액"].sum().sort_values(ascending=False)
    st.markdown("**사유별 금액**")
    st.bar_chart(reason, horizontal=True, alt="취소 사유별 금액")
    st.dataframe(df, hide_index=True, width="stretch", alt=f"{leaf.title} 내역", column_config=num_cols("금액"))


# ---------------- 매출정산 ----------------
@register("settle.receipts")
def settle_receipts(leaf: Leaf):
    sales_notice("POS 영수증")
    d = st.date_input("일자", value=get_today(), max_value=get_today(), key="rcpt_day")
    df = sd.receipts(get_store(), d)
    pays = st.pills("결제수단", [p[0] for p in sd.payments()], selection_mode="multi", key="rcpt_pay") or []
    view = df[df["결제수단"].isin(pays)] if pays else df
    kpis([("영수증", f"{len(view)}건", None), ("합계", won(view["금액"].sum()), None)])
    st.dataframe(view, hide_index=True, width="stretch", alt="매출 영수증 목록", column_config=num_cols("금액"))


@register("settle.detail")
def settle_detail(leaf: Leaf):
    sales_notice("POS 영수증")
    d = st.date_input("일자", value=get_today(), max_value=get_today(), key="rcpt_d_day")
    df = sd.receipts(get_store(), d)
    no = st.selectbox("영수증", df["영수증번호"], format_func=lambda n: f"{n} · {df[df['영수증번호'] == n].iloc[0]['시각']}")
    lines = sd.receipt_lines(get_store(), d, no)
    head = df[df["영수증번호"] == no].iloc[0]
    kpis([("테이블", head["테이블"], None), ("결제수단", head["결제수단"], None), ("품목 합계", won(lines["금액"].sum()), None)])
    st.dataframe(lines, hide_index=True, width="stretch", alt="영수증 상세 품목", column_config=num_cols("단가", "수량", "금액"))


@register("settle.report")
def settle_report(leaf: Leaf):
    sales_notice("정산")
    df = sd.settlement(get_store(), get_today(), 7)
    kpis([("7일 순매출", won(df["순매출"].sum()), None), ("할인 합계", won(df["할인"].sum()), None),
          ("부가세 합계", won(df["부가세"].sum()), None)])
    st.dataframe(df, hide_index=True, width="stretch", alt="일자별 정산 레포트",
                 column_config=num_cols("총매출", "할인", "순매출", "부가세"))
    st.download_button("CSV 내려받기", df.to_csv(index=False).encode("utf-8-sig"), "정산레포트.csv", "text/csv",
                       icon=":material/download:")


@register("settle.pnc")
def settle_pnc(leaf: Leaf):
    sales_notice("정산")
    st.caption("결제채널별 정산 (PNC 양식 확정 전 임시 구성: 채널별 순매출·수수료·입금예정액)")
    df = sd.settlement_by_channel(get_store(), get_today())
    kpis([("입금예정액 합계", won(df["입금예정액"].sum()), None), ("수수료 합계", won(df["수수료"].sum()), None)])
    st.dataframe(df, hide_index=True, width="stretch", alt="결제채널별 정산표",
                 column_config=num_cols("순매출", "수수료", "입금예정액"))


@register("settle.salmon")
def settle_salmon(leaf: Leaf):
    sales_notice("입고")
    df = sd.salmon_receiving(get_store(), get_today())
    kpis([("입고량", f"{df['수량(kg)'].sum():.1f}kg", None), ("입고 금액", won(df["금액"].sum()), None),
          ("재검 건수", f"{(df['검수'] == '재검').sum()}건", None)])
    st.dataframe(df, hide_index=True, width="stretch", alt="연어 입고 내역", column_config=num_cols("단가(원/kg)", "금액"))
