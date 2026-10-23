"""인력 및 스케줄 관리: 근태·스케줄 · 인건비 분석. 근태·인건비 원본 데이터가 아직 없어 데이터 없음 안내만 보여 준다."""
import streamlit as st

from menu import Leaf
from views import register
from views.common import no_data

NEEDS = {
    "hr.schedule": "월간 근무 스케줄표에는 직원별 근무 배치(출근 시간·교대) 데이터가 필요해요.",
    "hr.punch": "출퇴근 기록에는 출퇴근 단말(근태 시스템)의 기록 데이터가 필요해요.",
    "hr.swap": "근무 교대 요청에는 직원 명단과 근무 배치 데이터가 필요해요.",
    "hr.staffing": "시간대별 적정 인력은 시간대별 배치 인력 데이터가 있어야 비교할 수 있어요 (시간대별 매출은 매출 메뉴에 있어요).",
    "hr.labor_ratio": "매출 대비 인건비율에는 인건비(급여·근무시간) 데이터가 필요해요 (매출은 있어요).",
}


@register(*NEEDS)
def hr_no_data(leaf: Leaf):
    no_data("근태·스케줄·인건비 데이터가 아직 연결되지 않았어요.")
    st.caption(NEEDS[leaf.view] + " 데이터가 준비되면 이 화면에 실제 값으로 보여 드려요. 임의로 만든 값은 쓰지 않아요.")
