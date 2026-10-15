import unittest

from data import ITEMS
from models import Item, Supplier
from state import demo_items


def item(name, supplier, usage=1.0):
    return Item(name, 1000, usage, Supplier(supplier, frozenset({0}), 1))


class DemoItems(unittest.TestCase):
    def test_sample_master_keeps_the_original_demo_items(self):
        self.assertEqual([i.name for i in demo_items(ITEMS)], ["짜사이", "단무지", "청양고추"])

    def test_other_masters_get_active_items_from_different_suppliers(self):
        items = {n: item(n, s, u) for n, s, u in [("a", "X", 0), ("b", "X", 2), ("c", "X", 3), ("d", "Y", 1), ("e", "Z", 1), ("f", "Z", 5)]}
        picked = demo_items(items)
        self.assertEqual([i.name for i in picked], ["b", "d", "e"])              # 소비 있는 품목, 업체가 겹치지 않게

    def test_fewer_than_three_suppliers_still_returns_three(self):
        items = {n: item(n, "X", 1.0) for n in "abcde"}
        picked = demo_items(items)
        self.assertEqual(len(picked), 3)
        self.assertEqual(len({i.name for i in picked}), 3)

    def test_tiny_master_returns_what_exists(self):
        self.assertEqual([i.name for i in demo_items({"a": item("a", "X")})], ["a"])
        self.assertEqual(demo_items({}), [])


if __name__ == "__main__":
    unittest.main()
