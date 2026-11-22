"""인력 및 스케줄 관리: 월간 근무 스케줄표 · 매출 대비 인건비율. 근태·교대·시간대별 인력은 원본 데이터가 없어 안내만 보여 준다.
스케줄은 실제 스케줄 엑셀(2024-01~)을 `python -m labor` 로 정제한 값이다. 직원은 연봉이라 근무시간만, PT·PT리더는 시급×시간(+주휴)으로 비용을 낸다."""
import streamlit as st

import labor_data
import sales_data
from menu import Leaf
from views import register
from views.common import axis_chart, kpis, no_data, num_cols, won_short

NEEDS = {
    "hr.punch": "출퇴근 기록에는 출퇴근 단말(근태 시스템)의 기록 데이터가 필요해요.",
    "hr.swap": "근무 교대 요청에는 직원 명단과 근무 배치 데이터가 필요해요.",
    "hr.staffing": "시간대별 적정 인력은 시간대별 배치 인력 데이터가 있어야 비교할 수 있어요 (시간대별 매출은 매출 메뉴에 있어요).",
}
NOTE = ("수원점 실제 스케줄 엑셀(FOH·BK·FK, {a}~{b})을 읽은 값입니다. 평일 '+'는 휴게 2시간으로 계산했고, 대휴·연차·반차는 근무시간에 넣지 않았어요. "
        "원본은 `data/cleaned/스케줄/`에 있어요.")
NO_FILES = "스케줄 정제 데이터(data/cleaned/스케줄)가 없어요. `python -m labor` 로 만들 수 있어요."


@register(*NEEDS)
def hr_no_data(leaf: Leaf):
    no_data("근태·교대·시간대별 인력 데이터가 아직 연결되지 않았어요.")
    st.caption(NEEDS[leaf.view] + " 데이터가 준비되면 이 화면에 실제 값으로 보여 드려요. 임의로 만든 값은 쓰지 않아요.")


def _month_picker(key: str, upto: str | None = None) -> str:
    """월 선택. upto 를 주면 기본 선택을 그 달(없으면 그 이전 마지막 달)로 둔다 — 매출이 있는 마지막 달 같은 때."""
    ms = labor_data.months()
    default = max((i for i, m in enumerate(ms) if upto is None or m <= upto), default=len(ms) - 1)
    with st.container(key="filterbar"):
        return st.selectbox("월", ms, index=default, key=key)


@register("hr.schedule")
def schedule(leaf: Leaf):
    if not labor_data.available():
        return no_data(NO_FILES)
    ms = labor_data.months()
    st.caption(":material/database: " + NOTE.format(a=ms[0], b=ms[-1]))
    ym = _month_picker("hr_sch_month")
    dept = st.pills("부서", labor_data.DEPTS, default="전체", key="hr_sch_dept") or "전체"
    grid = labor_data.schedule_grid(ym, dept)
    if grid.empty:
        return no_data("이 달·부서에 스케줄이 없어요.")
    kpis([("근무 인원", f"{len(grid)}명", f"{ym} · {dept}"), ("총 근무시간", f"{grid['근무시간(시간)'].sum():,.1f}시간", None)])
    sched_tab, cand_tab = st.tabs([":material/calendar_month: 스케줄표", ":material/person_search: 입퇴사 후보"])
    with sched_tab:
        st.caption("직급 순(점장 > SM·KM > AM > TR > PT리더 > 사원 > PT). 칸의 값은 시트의 근무 코드 그대로이고 '/'는 휴무, 빈칸은 입사 전·퇴사 후예요.")
        st.dataframe(grid, hide_index=True, width="stretch", alt=f"{ym} 월간 근무 스케줄표", column_config=num_cols("근무시간(시간)"))
    with cand_tab:
        r = labor_data.roster(ym)
        st.caption("스케줄의 첫 기록·마지막 근무일로 추정한 후보예요. 다음 달에 다시 나오면 퇴사가 아니라 휴가로 보고, 최종 확정은 직접 해 주세요.")
        if r.empty:
            st.info("이 달에는 입퇴사 후보가 없어요.", icon=":material/check_circle:")
        else:
            st.dataframe(r, hide_index=True, width="stretch", alt=f"{ym} 입퇴사 후보표")


def _num(v, fmt: str, none: str = "—") -> str:
    return fmt.format(v) if v == v else none      # NaN 은 자기 자신과 다르다


@register("hr.labor_ratio")
def labor_ratio(leaf: Leaf):
    if not labor_data.available():
        return no_data(NO_FILES)
    ms = labor_data.months()
    st.caption(":material/database: " + NOTE.format(a=ms[0], b=ms[-1]))
    st.caption("직원 급여는 연봉(고정)이라 비용에 넣지 않고 근무시간만 보여 줘요. 인건비율은 PT·PT리더의 변동 인건비(주휴 포함) ÷ 순매출이에요. 순매출은 POS 기준이라 매출이 있는 달만 비율을 내요.")
    ym = _month_picker("hr_lab_month", upto=f"{sales_data.last_date():%Y-%m}")
    sm = labor_data.month_summary(sales_data.monthly(sales_data.last_date(), 48))
    cur = sm[sm["월"] == ym].iloc[0]
    kpis([("변동 인건비", won_short(cur["합계(원)"]), f"PT {won_short(cur['PT(원)'])} · PT리더 {won_short(cur['PT리더(원)'])}"),
          ("순매출", won_short(cur["순매출(원)"]) if cur["순매출(원)"] == cur["순매출(원)"] else "데이터 없음", None),
          ("변동 인건비율", _num(cur["변동 인건비율(%)"], "{:.1f}%"), None),
          ("직원 근무시간", _num(cur["직원 근무시간(시간)"], "{:,.0f}시간"), None)])
    trend, who, staff_tab, tbl = st.tabs([":material/show_chart: 월별 추이", ":material/payments: PT·PT리더 인건비", ":material/badge: 직원 근무시간", ":material/table: 월별 표"])
    with trend:
        axis_chart("line", sm.dropna(subset=["변동 인건비율(%)"]), x="월", y="변동 인건비율(%)", x_label="월", y_label="변동 인건비율(%)", alt_text="월별 변동 인건비율 추이")
        axis_chart("bar", sm, x="월", y=["PT(원)", "PT리더(원)"], x_label="월", y_label="변동 인건비(원)", alt_text="월별 PT·PT리더 변동 인건비")
    with who:
        st.caption("인건비 = (근무시간 + 주휴시간) × 시급. 주휴는 그 주 일요일이 속한 달에 넣어요.")
        st.dataframe(labor_data.hourly_pay(ym), hide_index=True, width="stretch", alt=f"{ym} PT·PT리더 인건비표",
                     column_config=num_cols("근무시간(시간)", "주휴(시간)", "시급(원)", "인건비(원)"))
    with staff_tab:
        st.caption("월 소정 174시간(주5일·8시간) 기준이에요. '174시간 대비'가 +면 연장(OT) 추정이고, 유급휴가(대휴·연차·반차)는 근무시간에 넣지 않았어요.")
        st.dataframe(labor_data.staff_hours(ym), hide_index=True, width="stretch", alt=f"{ym} 직원 근무시간표",
                     column_config=num_cols("근무시간(시간)", "유급휴가(시간)", "174시간 대비(시간)"))
    with tbl:
        st.dataframe(sm, hide_index=True, width="stretch", alt="월별 변동 인건비·인건비율표",
                     column_config=num_cols("PT(원)", "PT리더(원)", "합계(원)", "순매출(원)", "직원 근무시간(시간)"))
