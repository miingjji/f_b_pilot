"""발주 추천 화면의 근거 표시 도우미: 예상 범위와 검증 정확도 문구."""
import unittest

from views.purchase import md_range, qty_range, reliability_line

EV = {"검증기간": "2026-01-01~2026-09-30", "시점": {"엔진": {"정밀도": 0.67, "재현율": 0.91, "F1": 0.77}}, "수량": {"엔진": 31.0}}


class QtyRangeTest(unittest.TestCase):
    def test_range_around_quantity(self):
        self.assertEqual(qty_range(10, "박스", 0.31), "7~13 박스")

    def test_small_quantity_collapses_to_single_value(self):
        self.assertEqual(qty_range(1, "박스", 0.31), "1 박스")

    def test_never_below_one_step(self):
        self.assertEqual(qty_range(2, "병", 0.9), "1~4 병")

    def test_kg_keeps_decimal_step(self):
        self.assertEqual(qty_range(5.0, "킬로그램", 0.3), "3.5~6.5 킬로그램")


class ReliabilityLineTest(unittest.TestCase):
    def test_text_has_verified_numbers(self):
        t = reliability_line(EV)
        self.assertIn("67%", t)
        self.assertIn("91%", t)
        self.assertIn("±31%", t)
        self.assertIn("2026-01-01~2026-09-30", t)

    def test_empty_without_eval(self):
        self.assertEqual(reliability_line(None), "")


if __name__ == "__main__":
    unittest.main()


class MarkdownTildeTest(unittest.TestCase):
    def test_range_tilde_is_escaped_so_two_periods_do_not_become_strikethrough(self):
        self.assertEqual(md_range("2024-01-01~2025-12-31"), "2024-01-01\\~2025-12-31")
        line = f"(학습 {md_range('2024-01-01~2025-12-31')} → 학습에 쓰지 않은 {md_range('2026-01-01~2026-09-30')})"
        self.assertEqual(line.count("~"), line.count("\\~"))               # 이스케이프 안 된 ~ 가 없다
