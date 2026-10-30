"""메뉴명 -> BOM 메뉴 변환 규칙."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import unittest

import pandas as pd

from prep.menu_map import ALIAS_COLUMNS, map_name

BOM = {"새우볶음밥", "샤오롱바오(6)", "깐풍기", "깐풍기(소)", "(배달)우육면", "우육면", "사이다제로", "샤오롱바오샘플러신규", "샤오롱바오샘플러", "유린기(소)", "유린기", "펩시콜라"}
ALIASES = pd.DataFrame([
    ["제로사이다", "사이다제로", "", "", ""],
    ["깐풍기(중)", "깐풍기", "", "", ""],
    ["샤오롱바오샘플러", "샤오롱바오샘플러신규", "2026-05", "", ""],
    ["콜라", "펩시콜라", "", "", ""],
    ["유린기", "[무가제외]", "2026-02", "", ""],
], columns=ALIAS_COLUMNS)


def run(name, sub="음식", priced=True, month="2026-07"):
    return map_name(name, sub, priced, month, BOM, ALIASES)


class MenuMapTest(unittest.TestCase):
    def test_exact_and_space(self):
        self.assertEqual(run("새우볶음밥"), ("새우볶음밥", "정확일치"))
        self.assertEqual(run("새우 볶음밥"), ("새우볶음밥", "공백무시"))

    def test_free_etc_row_is_option_even_if_name_matches_bom(self):
        self.assertEqual(run("유린기", sub="ETC", priced=False), (None, "옵션"))
        self.assertEqual(run("유린기", sub="ETC", priced=True), ("유린기", "정확일치"))

    def test_set_component_prefixes(self):
        self.assertEqual(run("A - 새우볶음밥", sub="세트", priced=False), ("새우볶음밥", "세트구성품"))
        self.assertEqual(run("#세트1-샤오롱바오(6)", sub="세트", priced=False), ("샤오롱바오(6)", "세트구성품"))
        self.assertEqual(run("A-  제로사이다", sub="세트", priced=False), ("사이다제로", "세트구성품"))

    def test_channel_prefix_prefers_delivery_column(self):
        self.assertEqual(run("(배민)우육면"), ("(배달)우육면", "채널접두사"))
        self.assertEqual(run("(쿠팡)-새우볶음밥"), ("새우볶음밥", "채널접두사"))

    def test_alias_respects_start_month_and_existing_target(self):
        self.assertEqual(run("샤오롱바오샘플러", month="2026-05"), ("샤오롱바오샘플러신규", "별칭"))
        self.assertEqual(run("샤오롱바오샘플러", month="2026-04"), ("샤오롱바오샘플러", "정확일치"))
        self.assertEqual(run("깐풍기(중)"), ("깐풍기", "별칭"))

    def test_unpriced_rows_are_excluded_only_from_start_month_and_priced_rows_still_count(self):
        self.assertEqual(run("유린기", sub="요리", priced=False, month="2026-03"), (None, "무가행"))
        self.assertEqual(run("유린기", sub="요리", priced=True, month="2026-03"), ("유린기", "정확일치"))
        self.assertEqual(run("유린기", sub="요리", priced=False, month="2026-01"), ("유린기", "정확일치"))

    def test_choice_component_uses_chosen_item_and_dessert_set_parent_is_not_counted(self):
        self.assertEqual(run("혼면 - 콜라", sub="세트", priced=False), ("펩시콜라", "세트구성품"))
        self.assertEqual(run("꽃빵튀김세트", sub="디저트"), (None, "세트대표"))

    def test_set_parent_non_food_and_unmapped(self):
        self.assertEqual(run("A 세트", sub="세트"), (None, "세트대표"))
        self.assertEqual(run("고량주잔", sub="잔", priced=False), (None, "비식재"))
        self.assertEqual(run("처음 보는 메뉴"), (None, "미매핑"))


if __name__ == "__main__":
    unittest.main()
