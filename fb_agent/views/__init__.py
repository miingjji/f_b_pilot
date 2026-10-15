"""소메뉴(view 키) → 화면 렌더러 레지스트리."""
from collections.abc import Callable

import streamlit as st

from menu import Leaf

REGISTRY: dict[str, Callable[[Leaf], None]] = {}


def register(*keys: str):
    def deco(fn):
        for k in keys:
            REGISTRY[k] = fn
        return fn
    return deco


def placeholder(leaf: Leaf):
    st.info(f"'{leaf.title}' 화면은 준비 중입니다.", icon=":material/construction:")


def render(leaf: Leaf):
    """소메뉴에 연결된 화면을 그린다. 연결된 렌더러가 없으면 준비 중 화면."""
    REGISTRY.get(leaf.view, placeholder)(leaf)


# 모듈을 불러오면 @register 로 렌더러가 등록된다.
from . import ai, home, hr, purchase, sales, settings  # noqa: E402,F401
