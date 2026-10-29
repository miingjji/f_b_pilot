"""수불현황: 업체 선택과 품목 검색으로 표가 좁혀지는지 (테스트 마스터)."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import unittest

from streamlit.testing.v1 import AppTest

SCRIPT = '''
import streamlit as st
from state import init_state
init_state()
import views
from menu import get_leaf
views.render(get_leaf("stock-flow"))
'''


def rows(at) -> list:
    return list(at.dataframe[0].value["품목"]) if len(at.dataframe) and len(at.dataframe[0].value) else []


class StockFlowFilter(unittest.TestCase):
    def setUp(self):
        self.at = AppTest.from_string(SCRIPT, default_timeout=60).run()

    def test_renders_with_filters(self):
        self.assertFalse(self.at.exception)
        self.assertEqual(self.at.selectbox(key="sf_sup").value, "전체 업체")
        self.assertEqual(self.at.text_input(key="sf_q").value, "")

    def test_supplier_filter_narrows_rows(self):
        all_rows = rows(self.at)
        self.assertGreater(len(all_rows), 1)
        sups = [s for s in self.at.selectbox(key="sf_sup").options if s != "전체 업체"]
        at = self.at.selectbox(key="sf_sup").select(sups[0]).run()
        self.assertFalse(at.exception)
        self.assertLess(len(rows(at)), len(all_rows))
        self.assertGreater(len(rows(at)), 0)

    def test_item_search_matches_name(self):
        name = rows(self.at)[0]
        at = self.at.text_input(key="sf_q").set_value(name).run()
        self.assertIn(name, rows(at))
        self.assertLessEqual(len(rows(at)), len(rows(self.at)))

    def test_no_match_shows_empty_message(self):
        at = self.at.text_input(key="sf_q").set_value("없는품목이름zzz").run()
        self.assertEqual(rows(at), [])
        self.assertTrue(any("조건에 맞는 품목이 없어요" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
