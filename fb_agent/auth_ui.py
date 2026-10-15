"""상단 헤더: 페이지 제목 + 에이전트 토글 + 로그인/회원가입/프로필.

[auth] 시크릿이 설정되어 있으면 st.login()(OIDC)을 쓰고, 없으면 데모 모드(비밀번호 없는 이름·이메일 입력)로 동작.
"""
import streamlit as st


def _auth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:  # secrets 파일 없음
        return False


def current_user():
    if _auth_configured():
        if st.user.is_logged_in:
            return {"name": st.user.get("name") or st.user.get("email") or "사용자", "email": st.user.get("email", "")}
        return None
    return st.session_state.user


@st.dialog("로그인 · 회원가입")
def _demo_dialog(mode: str):
    st.caption("데모 모드입니다. 실제 인증은 연결되어 있지 않으며 비밀번호는 받지 않습니다.")
    with st.form("demo_auth", border=False):
        name = st.text_input("이름")
        email = st.text_input("이메일")
        if st.form_submit_button("가입하고 시작" if mode == "signup" else "로그인", type="primary"):
            if not name.strip() or "@" not in email:
                st.error("이름과 올바른 이메일을 입력해 주세요.")
            else:
                st.session_state.user = {"name": name.strip(), "email": email.strip()}
                st.rerun()


def _open_auth(mode: str):
    if _auth_configured():
        st.login()
    else:
        _demo_dialog(mode)


def _toggle_agent():
    st.session_state.agent_open = not st.session_state.agent_open


def _logout():
    if _auth_configured():
        st.logout()
    else:
        st.session_state.user = None


def render_header(page, agent_mode: str, open_drawer):
    left, right = st.columns([5, 4], vertical_alignment="center")
    with left:
        st.title(page.title, icon=page.icon)
    with right:
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
            if agent_mode == "dock":
                open_ = st.session_state.agent_open
                st.button("F&B Agent", icon=":material/smart_toy:", type="primary" if open_ else "secondary",
                          on_click=_toggle_agent, help="에이전트 패널 열기/닫기")
            elif st.button("F&B Agent", icon=":material/smart_toy:", type="primary",
                           help="에이전트를 우측 서랍으로 엽니다"):
                open_drawer()
            user = current_user()
            if user:
                with st.popover(user["name"], icon=":material/account_circle:"):
                    st.caption(user["email"] or "데모 사용자")
                    st.button("로그아웃", icon=":material/logout:", on_click=_logout, width="stretch")
            else:
                if st.button("로그인", icon=":material/login:", type="tertiary"):
                    _open_auth("login")
                if st.button("회원가입", type="secondary"):
                    _open_auth("signup")
