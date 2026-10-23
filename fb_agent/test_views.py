"""소메뉴 화면이 모두 예외 없이 그려지는지 확인 (AppTest, 매장별)."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import unittest

from streamlit.testing.v1 import AppTest

from menu import STORES, all_leaves

SCRIPT = """
import streamlit as st
from state import init_state
init_state()
st.session_state.store = {store!r}
import views
from menu import get_leaf
views.render(get_leaf({leaf!r}))
"""


class RenderEveryLeaf(unittest.TestCase):
    def test_all_leaves_render(self):
        failures = []
        for leaf in all_leaves():
            at = AppTest.from_string(SCRIPT.format(store=STORES[0], leaf=leaf.id), default_timeout=60).run()
            if at.exception:
                failures.append(f"{leaf.id}: {at.exception[0].message[:300]}")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
