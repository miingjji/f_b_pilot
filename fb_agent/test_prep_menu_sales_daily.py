"""일자기준 메뉴매출조회(하루치 파일) 정제."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import tempfile
import unittest
from pathlib import Path

from prep.menu_sales_daily import clean

HEAD = "| No. | 브랜드 | 대분류 | 중분류 | 소분류 | 메뉴코드 | 메뉴명 | 매장 | 단가 | 매출수량 | 총매출 | 실매출 | 순매출 | 부가세 | 할인 | 실매출비중(%) |"


def day_file(period, rows, total):
    lines = [f"| 조회기간: {period} | NaN |", HEAD]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    lines.append("| NaN | 합계 | " + " | ".join(total) + " | 100% |")
    return "\n".join(lines)


ROW1 = ["1", "딘타이펑", "음식", "덤플링", "덤플링", "10020200", "매운게살샤오마이(4)", "수원점", "10500", "2", "21000", "20000", "18182", "1818", "-1000", "50%"]
ROW2 = ["2", "딘타이펑", "NaN", "NaN", "NaN", "10060200", "새우\\_샤오마이", "수원점", "0", "1", "0", "0", "0", "0", "0", "0%"]
TOTAL = ["3", "21000", "20000", "18182", "1818", "-1000"]


class MenuSalesDailyTest(unittest.TestCase):
    def run_clean(self, files, **kw):
        with tempfile.TemporaryDirectory() as d:
            for name, text in files.items():
                (Path(d) / name).write_text(text, encoding="utf-8")
            return clean(Path(d), **kw)

    def test_fills_merged_class_cells_and_unescapes_names(self):
        menu, daily, notes = self.run_clean({"a.md": day_file("2026-10-02 ~ 2026-10-02", [ROW1, ROW2], TOTAL)})
        self.assertEqual(list(menu["소분류명"]), ["덤플링", "덤플링"])
        self.assertIn("새우_샤오마이", list(menu["메뉴명"]))
        self.assertEqual(int(daily.loc[0, "수량"]), 3)

    def test_multi_day_file_is_skipped_and_reported(self):
        menu, daily, notes = self.run_clean({"a.md": day_file("2026-10-02 ~ 2026-10-02", [ROW1, ROW2], TOTAL),
                                              "b.md": day_file("2025-01-01 ~ 2025-11-30", [ROW1, ROW2], TOTAL)})
        self.assertEqual(list(daily["날짜"]), ["2026-10-02"])
        self.assertTrue(any("b.md" in n for n in notes))

    def test_total_row_mismatch_stops(self):
        bad = ["3", "99999", "20000", "18182", "1818", "-1000"]
        with self.assertRaises(ValueError):
            self.run_clean({"a.md": day_file("2026-10-02 ~ 2026-10-02", [ROW1, ROW2], bad)})

    def test_reports_missing_days_between_first_and_last(self):
        menu, daily, notes = self.run_clean({"a.md": day_file("2026-10-02 ~ 2026-10-02", [ROW1, ROW2], TOTAL),
                                              "b.md": day_file("2026-10-04 ~ 2026-10-04", [ROW1, ROW2], TOTAL)})
        self.assertTrue(any("2026-10-03" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
