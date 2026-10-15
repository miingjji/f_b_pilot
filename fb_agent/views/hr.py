"""인력 및 스케줄 관리: 근태·스케줄 · 인건비 분석 (샘플 데이터)."""
import calendar
from datetime import date

import pandas as pd
import streamlit as st

import sample_data as sd
from menu import Leaf
from state import get_store, get_today
from views import register
from views.common import iso, kpis, num_cols, sample_notice, won

ss = st.session_state
SHIFT_COLOR = {"오": "#DBEAFE", "후": "#EDE9FE", "풀": "#FEF3C7", "휴": "#F3F4F6"}
DOW = "월화수목금토일"


def _style_shift(v):
    return f"background-color: {SHIFT_COLOR.get(v, '')}; color: #1F2937; text-align: center"


@register("hr.schedule")
def schedule(leaf: Leaf):
    sample_notice("근태·스케줄")
    today = get_today()
    c1, c2 = st.columns(2)
    year = c1.number_input("연도", min_value=2020, max_value=2100, value=today.year, step=1)
    month = c2.number_input("월", min_value=1, max_value=12, value=today.month, step=1)
    df = sd.month_schedule(get_store(), int(year), int(month))
    with st.container(horizontal=True):
        for code, (name, s, e) in sd.SHIFTS.items():
            hours = f" {s}~{e}시" if s else ""
            st.badge(f"{code} {name}{hours}", color={"오": "blue", "후": "violet", "풀": "yellow", "휴": "gray"}[code])
    days_n = calendar.monthrange(int(year), int(month))[1]
    kpis([("직원", f"{len(df)}명", None),
          ("오늘 근무" if (year, month) == (today.year, today.month) else "1일 근무",
           f"{int((df[str(today.day if (year, month) == (today.year, today.month) else 1)] != '휴').sum())}명", None),
          ("총 근무일수", f"{int((df != '휴').sum().sum())}일", f"{days_n}일 기준")])
    dow_row = {str(d): DOW[date(int(year), int(month), d).weekday()] for d in range(1, days_n + 1)}
    st.caption("열 머리는 일자입니다. " + " · ".join(f"{d}일={dow_row[str(d)]}" for d in (1, 8, 15, 22)) + " …")
    st.dataframe(df.style.map(_style_shift), width="stretch", alt="월간 근무 스케줄표")
    kind = {n: k for n, k, _w in sd.STAFF}
    summary = pd.DataFrame({"구분": [kind[n] for n in df.index], "근무일수": (df != "휴").sum(axis=1).values},
                           index=df.index)
    st.subheader("직원별 근무일수")
    st.dataframe(summary.reset_index(names="직원"), hide_index=True, width="stretch", alt="직원별 근무일수")


@register("hr.punch")
def punch(leaf: Leaf):
    sample_notice("출퇴근 단말")
    df = sd.punch_records(get_store(), get_today(), 7)
    kind = st.segmented_control("구분", ["전체", "정직원", "파트타임"], default="전체", key="punch_kind") or "전체"
    view = df if kind == "전체" else df[df["구분"] == kind]
    kpis([("기록", f"{len(view)}건", None), ("총 근무시간", f"{view['근무시간'].sum():.1f}시간", None),
          ("인당 평균", f"{view['근무시간'].mean():.1f}시간", None)])
    st.bar_chart(view.groupby("직원")["근무시간"].sum().sort_values(ascending=False), y_label="시간",
                 alt="직원별 최근 7일 근무시간")
    st.dataframe(view, hide_index=True, width="stretch", alt="출퇴근 기록")


def _decide(req_no: str, status: str):
    for r in ss.shift_requests:
        if r["번호"] == req_no and r["상태"] == "요청":
            r["상태"] = status
            return


@register("hr.swap")
def swap(leaf: Leaf):
    names = [n for n, _k, _w in sd.STAFF]
    with st.form("swap_form", border=True):
        c1, c2, c3 = st.columns(3)
        who = c1.selectbox("요청자", names)
        day = c2.date_input("근무일", value=get_today(), min_value=get_today())
        target = c3.selectbox("교대 대상", [n for n in names if n != who])
        reason = st.text_input("사유", placeholder="예: 개인 일정")
        if st.form_submit_button("교대 요청", type="primary", icon=":material/swap_horiz:"):
            ss.shift_requests = [*ss.shift_requests, {
                "번호": f"SW-{len(ss.shift_requests) + 1:04d}", "매장": get_store(), "요청자": who, "근무일": day,
                "교대 대상": target, "사유": reason, "상태": "요청"}]
            st.toast("교대 요청을 등록했어요.", icon=":material/check_circle:")
    mine = [r for r in ss.shift_requests if r["매장"] == get_store()]
    st.subheader("요청 목록")
    if not mine:
        st.caption("교대 요청이 없어요.")
    for r in reversed(mine):
        with st.container(border=True):
            left, a, b = st.columns([5, 1, 1], vertical_alignment="center")
            left.markdown(f"**{r['번호']}** · {r['요청자']} ↔ {r['교대 대상']} · {r['근무일']:%m/%d} · {r['사유'] or '사유 없음'}")
            if r["상태"] == "요청":
                a.button("승인", key=f"sw_ok_{r['번호']}", on_click=_decide, args=(r["번호"], "승인"))
                b.button("반려", key=f"sw_no_{r['번호']}", on_click=_decide, args=(r["번호"], "반려"))
            else:
                a.caption(r["상태"])
    st.caption("승인 상태는 기록만 하며, 월간 스케줄표에는 아직 자동 반영되지 않아요.")


@register("hr.staffing")
def staffing(leaf: Leaf):
    sample_notice("매출·근태")
    d = st.date_input("일자", value=get_today(), key="staffing_day")
    df = sd.staffing_by_hour(get_store(), d)
    gap = df["배치 인력"] - df["적정 인력"]
    short, over = int((gap < 0).sum()), int((gap > 0).sum())
    kpis([("부족 시간대", f"{short}개", None), ("과잉 시간대", f"{over}개", None),
          ("최대 부족", f"{int(-gap.min()) if gap.min() < 0 else 0}명", None)])
    st.line_chart(df.set_index("시간")[["적정 인력", "배치 인력"]], y_label="인원", alt="시간대별 적정 인력과 배치 인력")
    st.caption(f"적정 인력 = 시간대 매출 ÷ {sd.HOURLY_SALES_PER_STAFF:,}원 (직원 1명이 1시간에 감당하는 매출), 최소 2명")
    out = df.assign(과부족=gap.map(lambda x: f"{x:+d}" if x else "적정"))
    st.dataframe(out, hide_index=True, width="stretch", alt="시간대별 인력 과부족표")


@register("hr.labor_ratio")
def labor_ratio(leaf: Leaf):
    sample_notice("매출·근태")
    df = sd.labor_cost(get_store(), get_today(), 30)
    target = st.slider("목표 인건비율 (L%)", 15, 40, 28, key="labor_target")
    avg = df["labor"].sum() / df["sales"].sum() * 100
    kpis([("30일 인건비", won(df["labor"].sum()), None), ("평균 L%", f"{avg:.1f}%", f"목표 {target}% 대비 {avg - target:+.1f}p"),
          ("목표 초과일", f"{int((df['L%'] > target).sum())}일", None)])
    st.line_chart(iso(df).set_index("date")["L%"], y_label="L%", alt="일자별 매출 대비 인건비율")
    st.dataframe(df.assign(일자=df["date"].dt.strftime("%Y-%m-%d"))[["일자", "sales", "labor", "L%"]]
                 .rename(columns={"sales": "매출", "labor": "인건비"}).sort_values("일자", ascending=False),
                 hide_index=True, width="stretch", alt="일자별 인건비 분석표", column_config=num_cols("매출", "인건비"))
