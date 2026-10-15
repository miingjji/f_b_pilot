"""소메뉴 id → st.Page 조회와 이동. app.py가 매 실행마다 PAGES를 채운다."""
import streamlit as st

PAGES: dict = {}


def go(leaf_id: str):
    """해당 소메뉴 화면으로 이동 (현재 실행은 여기서 끝남)."""
    st.switch_page(PAGES[leaf_id])
