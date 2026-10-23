import unittest

import pandas as pd

from prep import price_tables as pt


def table(rows):
    return pd.DataFrame(rows, columns=["메뉴코드", "월", "판매단가", "판매수량", "메뉴명"])


class PriceTables(unittest.TestCase):
    def test_changes_flags_persistent_and_reverted_prices(self):
        t = table([("A", "2025-01", 100.0, 1, "가"), ("A", "2025-02", 110.0, 1, "가"), ("A", "2025-03", 110.0, 1, "가"),
                   ("B", "2025-01", 100.0, 1, "나"), ("B", "2025-02", 120.0, 1, "나"), ("B", "2025-03", 100.0, 1, "나"),
                   ("C", "2025-01", 100.0, 1, "다"), ("C", "2025-02", 100.2, 1, "다")])
        c = pt.changes(t, ["메뉴코드"], "판매단가").set_index("메뉴코드")
        self.assertEqual(c.loc["A", "다음달_유지"], "유지")
        self.assertEqual(c.loc[c.index == "B", "다음달_유지"].tolist(), ["되돌아감·재변경", "마지막 달"])
        self.assertNotIn("C", c.index)                                           # 0.2% 는 변동으로 보지 않는다

    def test_chained_index_uses_only_items_present_in_both_months(self):
        t = table([("A", "2024-01", 100.0, 1, "가"), ("A", "2024-02", 110.0, 1, "가"),
                   ("B", "2024-02", 50.0, 1, "나"), ("B", "2024-03", 50.0, 1, "나"), ("A", "2024-03", 110.0, 1, "가")])
        s = pt.chained_index(t, ["메뉴코드"], "판매단가", "판매수량")
        self.assertEqual(s["2024-01"], 100.0)
        self.assertAlmostEqual(s["2024-02"], 110.0)                              # B 는 1월에 없어 제외
        self.assertAlmostEqual(s["2024-03"], 110.0)                              # 2→3월은 A·B 모두 그대로


if __name__ == "__main__":
    unittest.main()
