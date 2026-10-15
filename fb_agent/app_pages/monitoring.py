import streamlit as st

st.caption("매장별 실시간 운영 지표를 모아 보는 화면입니다. 데이터 연동 전 스켈레톤입니다.")

with st.container(horizontal=True):
    for label, icon in [("오늘 매출", ":material/payments:"), ("객수", ":material/groups:"),
                        ("근무 인원", ":material/badge:"), ("대기 주문", ":material/receipt_long:")]:
        with st.container(border=True):
            st.metric(f"{icon} {label}", "—")

with st.container(border=True):
    st.subheader("시간대별 매출")
    st.info("POS 연동 후 시간대별 매출 차트가 표시됩니다.", icon=":material/construction:")

with st.container(border=True):
    st.subheader("매장 상태")
    st.info("매장별 영업·알림 상태가 표시됩니다.", icon=":material/construction:")
