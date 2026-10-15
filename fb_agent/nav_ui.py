"""좌측 네비게이션: 아이콘 레일 + 서브 패널(메뉴 검색, 대/중/소 아코디언).

- 레일 아이콘을 누르면 서브 패널에 해당 카테고리 메뉴가 펼쳐진다 (화면 이동 없음).
- 소메뉴를 누르면 해당 화면으로 이동한다. 소메뉴마다 URL(/sales-daily 등)을 가진다.
"""
import streamlit as st

import routing
import views
from data import DATASET_LABEL
from viewport import is_mobile
from menu import (DEFAULT_LEAF, FAV_RAIL, RAILS, Leaf, all_leaves, breadcrumb, get_leaf, has_leaf, icon_of, rail_by_id,
                  rail_of, search)

ss = st.session_state


def build_pages() -> dict:
    """소메뉴 id → st.Page. 화면은 views.render()가 그린다."""
    pages = {}
    for leaf in all_leaves():
        def _page(leaf=leaf):
            views.render(leaf)
        _page.__name__ = leaf.id.replace("-", "_")
        pages[leaf.id] = st.Page(_page, title=leaf.title, icon=icon_of(leaf.id), url_path=leaf.id,
                                 default=leaf.id == DEFAULT_LEAF)
    return pages


def current_leaf_id(page) -> str:
    path = getattr(page, "url_path", "") or ""
    return path if has_leaf(path) else DEFAULT_LEAF


def _set_rail(rail_id: str):
    ss.rail = rail_id


def _navigate(leaf_id: str):
    """버튼 콜백: 이동은 다음 실행 초반(app.py)에서 처리한다."""
    ss.nav_target = leaf_id
    ss.rail = None          # 이동 후에는 현재 화면이 속한 카테고리를 펼침
    ss.menu_query = ""


def apply_pending_navigation():
    target = ss.pop("nav_target", None)
    if target and has_leaf(target):
        routing.go(target)


def _leaf_button(leaf: Leaf, current_id: str, prefix: str, sub: str = ""):
    st.button(leaf.title, key=f"{prefix}_{leaf.id}", type="primary" if leaf.id == current_id else "tertiary",
              width="stretch", on_click=_navigate, args=(leaf.id,), help=sub or None)


def _panel(rail_id: str, current_id: str):
    rail = rail_by_id(rail_id)
    st.caption(f"{rail.label}")
    if rail.id == FAV_RAIL:
        favs = [get_leaf(i) for i in ss.favorites if has_leaf(i)]
        if not favs:
            st.caption("즐겨찾기가 없어요. 화면 제목 옆 :material/star: 를 눌러 추가하세요.")
        for leaf in favs:
            _leaf_button(leaf, current_id, "fav", " › ".join(breadcrumb(leaf.id)[:2]))
        return
    for major in rail.majors:
        has_current = any(lf.id == current_id for mid in major.mids for lf in mid.leaves)
        with st.expander(f"**{major.title}**", expanded=has_current or len(rail.majors) == 1):
            for mid in major.mids:
                with st.expander(mid.title, expanded=any(lf.id == current_id for lf in mid.leaves)):
                    for leaf in mid.leaves:
                        _leaf_button(leaf, current_id, "nav")


def _rail_buttons(active: str):
    for rail in RAILS:
        st.button(rail.icon, key=f"rail_{rail.id}", type="primary" if rail.id == active else "tertiary",
                  help=rail.label, on_click=_set_rail, args=(rail.id,), width="stretch")


def _panel_body(active: str, current_id: str):
    query = st.text_input("메뉴 검색", key="menu_query", placeholder="메뉴 검색", icon=":material/search:",
                          label_visibility="collapsed")
    if query.strip():
        found = search(query)
        st.caption(f"검색 결과 {len(found)}건")
        for leaf in found:
            _leaf_button(leaf, current_id, "sr", " › ".join(breadcrumb(leaf.id)[:2]))
            st.caption(" › ".join(breadcrumb(leaf.id)[:2]))
        if not found:
            st.caption("일치하는 메뉴가 없어요.")
    else:
        _panel(active, current_id)


def render_sidebar(current_id: str):
    active = ss.rail or rail_of(current_id).id
    with st.sidebar:
        if is_mobile():     # 좁은 화면: 아이콘을 가로 한 줄로, 그 아래에 서브 패널
            with st.container(horizontal=True, horizontal_alignment="distribute"):
                _rail_buttons(active)
            _panel_body(active, current_id)
        else:               # 레일(좁은 열) | 서브 패널
            rail_col, panel_col = st.columns([1, 6], gap="xsmall")
            with rail_col:
                _rail_buttons(active)
            with panel_col:
                _panel_body(active, current_id)
        st.divider()
        st.caption(f":material/database: {DATASET_LABEL}")
