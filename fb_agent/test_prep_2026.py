import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import tempfile
import unittest
from pathlib import Path

from prep import data_2026
from prep.blocks import UnhandledMissingError


def md(rows):
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def write(tmp, name, rows):
    (Path(tmp) / data_2026.FILES[name]).write_text(md(rows), encoding="utf-8")


SALES = [
    ["No.", "매출일자", "요일", "열 레이블", "Unnamed: 4", "Unnamed: 5", "Unnamed: 6", "Unnamed: 7", "Unnamed: 8", "Unnamed: 9", "Unnamed: 10"],
    ["---"] * 11,
    ["NaN"] * 11,
    ["NaN"] * 11,
    ["1.0", "2026-01-02", "금요일", "1000", "900", "800", "10", "1000", "900", "800", "10"],
    ["2.0", "2026-01-04", "일요일", "2000", "1800", "1600", "20", "2000", "1800", "1600", "20"],
    ["NaN", "총 합계", "NaN", "3000", "2700", "2400", "30", "3000", "2700", "2400", "30"],
]


class DailySalesTest(unittest.TestCase):
    def test_missing_day_is_marked_not_dropped(self):
        out, report, info = data_2026.clean_daily_sales(_rows(SALES))
        self.assertEqual(len(out), 4)                       # 01-01 ~ 01-04
        off = out[out["영업여부"] == "무매출일"]
        self.assertEqual(off["매출일자"].tolist(), ["2026-01-01", "2026-01-03"])
        self.assertTrue((off["순매출"] == 0).all())
        self.assertTrue(all(c["ok"] for c in info["checks"]))
        self.assertEqual(int(out["순매출"].sum()), 2400)

    def test_total_mismatch_is_reported(self):
        bad = [list(r) for r in SALES]
        bad[-1][5] = "9999"
        _, _, info = data_2026.clean_daily_sales(_rows(bad))
        self.assertTrue(any(not c["ok"] for c in info["checks"]))


def _rows(table):
    return [[None if c in ("", "NaN") else c for c in r] for r in table]


class NumberTest(unittest.TestCase):
    def test_comma_numbers(self):
        import pandas as pd
        self.assertEqual(data_2026.number(pd.Series(["1,332.00", "7,110", None])).tolist()[:2], [1332.0, 7110.0])

    def test_unreadable_value_raises(self):
        import pandas as pd
        with self.assertRaises(UnhandledMissingError):
            data_2026.number(pd.Series(["#NUM!"]))


class SplitItemTest(unittest.TestCase):
    def test_tag_name_spec_code(self):
        import pandas as pd
        r = data_2026.split_item(pd.Series(["[수D1/부D2]깐대파_1kg/pk_1kg/pk_1030014GD", "양상추_0.5kg/pk_0.5kg/pk_1030006GD"]))
        self.assertEqual(r["품명태그"].tolist(), ["[수D1/부D2]", "없음"])
        self.assertEqual(r["품명"].tolist(), ["깐대파", "양상추"])
        self.assertEqual(r["품목사양코드"].tolist(), ["1030014GD", "1030006GD"])


REAL = Path(__file__).resolve().parent / "data" / "source" / "2026"


@unittest.skipUnless((REAL / data_2026.FILES["입고"]).exists(), "data/source/2026 원본 없음")
class RealDataTest(unittest.TestCase):
    def test_all_checks_pass_and_nothing_missing(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(data_2026.main(["--src", str(REAL), "--out", out]), 0)
            import pandas as pd
            for name in data_2026.FILES:
                self.assertEqual(int(pd.read_csv(Path(out) / f"{name}_정제.csv").isna().sum().sum()), 0)


if __name__ == "__main__":
    unittest.main()
