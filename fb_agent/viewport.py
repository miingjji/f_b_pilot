"""브라우저 폭을 Python으로 전달하는 0 높이 커스텀 컴포넌트(CCv2).

서버는 화면 크기를 모르므로, 컴포넌트를 화면 맨 아래에 마운트하고 값은 session_state에 저장된
이전 실행 결과를 읽습니다. 창 크기가 바뀌면 값이 갱신되며 앱이 한 번 다시 실행됩니다.
"""
import streamlit as st

KEY = "vp_probe"
DEFAULT_VIEWPORT = 1600       # 값이 아직 없을 때(첫 로드) 가정하는 창 폭
DEFAULT_CONTENT = 1140        # 위와 같은 상황에서의 본문(사이드바 제외) 폭
MOBILE_MAX = 700

_JS = """
export default function (component) {
  const { parentElement, setStateValue } = component
  // isolate_styles=True라 parentElement는 ShadowRoot다. 크기는 host 요소에서 읽는다.
  const el = parentElement.host || parentElement
  let lastVw = -999, lastCw = -999, timer = null

  const report = () => {
    const vw = Math.round(window.innerWidth)
    const cw = Math.round(el.getBoundingClientRect().width)
    if (Math.abs(vw - lastVw) < 8 && Math.abs(cw - lastCw) < 8) return
    lastVw = vw
    lastCw = cw
    setStateValue("dims", { vw, cw })
  }
  const onResize = () => {
    clearTimeout(timer)
    timer = setTimeout(report, 200)
  }

  report()
  window.addEventListener("resize", onResize)
  return () => {
    clearTimeout(timer)
    window.removeEventListener("resize", onResize)
  }
}
"""

_PROBE = st.components.v2.component("viewport_probe", html="<div></div>", js=_JS)


def mount_probe():
    """앱 스크립트 맨 아래에서 한 번 호출."""
    _PROBE(key=KEY, on_dims_change=lambda: None, height="content")


def _dims():
    try:
        d = st.session_state.get(KEY, {}).get("dims")
        return (int(d["vw"]), int(d["cw"])) if d else None
    except Exception:
        return None


def _ua_mobile() -> bool:
    try:
        ua = st.context.headers.get("User-Agent", "")
    except Exception:
        return False
    return any(k in ua for k in ("Mobile", "Android", "iPhone"))


def viewport() -> tuple[int, int]:
    """(창 폭, 본문 폭) px. 아직 측정 전이면 기본값(휴대폰 UA면 좁은 값)."""
    d = _dims()
    if d:
        return d
    return (390, 358) if _ua_mobile() else (DEFAULT_VIEWPORT, DEFAULT_CONTENT)


def is_mobile() -> bool:
    return viewport()[0] < MOBILE_MAX
