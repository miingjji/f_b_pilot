"""재고 실사 입력 표의 표시 열: 환산 기준과 입력 즉시 환산 합계 (소형 fixture 마스터)."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import dataclasses
import unittest

from data import ITEMS
from unit_info import stock_of
from views import purchase


class EntryColumns(unittest.TestCase):
    def test_convert_basis_tells_what_one_pk_and_one_box_are(self):
        self.assertEqual(purchase.convert_basis(ITEMS["짜사이"]), "1PK=1kg · 1BOX=10PK · 낱개=g")           # 낱개는 기본단위로 센다
        self.assertEqual(purchase.convert_basis(ITEMS["주방세제"]).endswith("낱개=ml"), True)

    def test_count_items_with_one_per_pk_only_say_how_to_count(self):
        n = ITEMS["냅킨"]
        self.assertEqual(purchase.convert_basis(n), "1PK=500장 · 1BOX=10PK · 낱개=장")                       # 팩에 500장, 박스에 10팩
        one = dataclasses.replace(n, pk_weight_g=1, box_pk=1, base_unit="개")                                # 1PK=1개: 환산할 것이 없다
        self.assertEqual(purchase.convert_basis(one), "낱개=개")

    def test_total_converts_box_pk_and_loose_together(self):
        j = ITEMS["짜사이"]                                            # 1PK=1,000g, 1BOX=10PK
        self.assertEqual(purchase.entry_total(j, 0, 2, 400), f"2.4kg = {stock_of(j, 2400)}")
        self.assertEqual(purchase.entry_total(j, 1, 0, 0), f"10kg = {stock_of(j, 10000)}")
        self.assertEqual(purchase.entry_total(j, 0, 0, 0), "0")        # 0 은 군더더기 없이

    def test_count_items_show_the_count_only(self):
        n = ITEMS["냅킨"]
        self.assertEqual(purchase.entry_total(n, 0, 3, 0), stock_of(n, 3 * n.pk_weight_g))

    def test_bad_values_say_check_the_input(self):
        j = ITEMS["짜사이"]
        for box, pk, loose in ((0, -1, 0), (float("nan"), 0, 0), (0, 0, None)):
            self.assertEqual(purchase.entry_total(j, box, pk, loose), "입력 확인", (box, pk, loose))

    def test_number_columns_reject_negative_values_and_name_the_unit_of_loose_counts(self):
        cfg = purchase.ENTRY_CONFIG
        self.assertEqual(purchase.ENTRY_COLUMNS, ["품목", "BOX", "PK", "낱개", "합계", "환산 기준"])
        for k in ("BOX", "PK", "낱개"):
            self.assertIsNotNone(cfg[k])
        self.assertIn("기본단위", str(cfg["낱개"]))


if __name__ == "__main__":
    unittest.main()
