import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from prep.__main__ import CLEANERS, cross_checks, main

REAL = Path(__file__).resolve().parent / "data" / "f_b_menu_data.md"


def fake_results(guests=100, net=1000.0, ledger_sales=1000.0, ledger_guests=100, amount=1000, rec=(1000.0, 50.0)):
    sales = pd.DataFrame({"순매출_합계": [net / 2, net / 2], "객수_합계": [guests / 2, guests / 2], "수량_합계": [25, 25]})
    kpi = pd.DataFrame({"지표": ["매출", "객수", "객단가"], "값": [ledger_sales, ledger_guests, ledger_sales / ledger_guests]})
    return {
        "매출입력": {"tables": {None: sales}},
        "수불요약": {"tables": {"매출지표": kpi}},
        "판매및할인": {"info": {"amount_without_duplicates": amount, "reconcile_rows": {"매출입력": {"금액": rec[0], "수량": rec[1]}}}},
    }


class CrossChecks(unittest.TestCase):
    def test_all_consistent(self):
        checks = cross_checks(fake_results())
        self.assertEqual(len(checks), 5)
        self.assertTrue(all(c["ok"] for c in checks), checks)

    def test_source_difference_is_a_note_not_a_failure(self):
        checks = {c["항목"]: c for c in cross_checks(fake_results(ledger_sales=1200.0))}
        sales_check = checks["수불요약 매출 = 매출입력 순매출_합계 합 (원본 차이)"]
        self.assertFalse(sales_check["ok"])
        self.assertTrue(sales_check["참고"])                       # 원본 차이는 '참고'라 정제 실패로 보지 않음

    def test_real_mismatch_in_counts_is_a_failure(self):
        checks = {c["항목"]: c for c in cross_checks(fake_results(ledger_guests=99))}
        c = checks["수불요약 객수 = 매출입력 객수_합계 합"]
        self.assertFalse(c["ok"])
        self.assertFalse(c["참고"])

    def test_duplicate_amount_mismatch_is_reported(self):
        checks = {c["항목"]: c for c in cross_checks(fake_results(amount=1355))}
        self.assertFalse(checks["판매및할인 판매금액(중복행 제외) = 매출입력 순매출_합계 합"]["ok"])

    def test_without_sales_nothing_to_compare(self):
        self.assertEqual(cross_checks({}), [])

    def test_registry_covers_five_sheets_in_order(self):
        self.assertEqual([n for n, _, _ in CLEANERS], ["매출입력", "판매및할인", "실사재고", "입고내역", "수불요약"])


@unittest.skipUnless(REAL.exists(), "실제 데이터 파일이 없으면 건너뜀")
class RunnerOnRealFile(unittest.TestCase):
    def test_main_writes_every_file_and_exits_zero(self):
        out = Path(tempfile.mkdtemp())
        self.assertEqual(main(["--src", str(REAL), "--out", str(out)]), 0)        # 원본 차이(참고)는 실패가 아님
        names = {p.name for p in out.iterdir()}
        for must in ("매출입력_정제.csv", "판매및할인_정제.csv", "실사재고_정제.csv", "입고내역_정제.csv", "수불요약_수불마감_정제.csv",
                     "수불요약_매출지표_정제.csv", "수불요약_차이순위_금액기준_정제.csv", "정제_점검결과.csv"):
            self.assertIn(must, names)
        self.assertTrue(all(n.endswith("_결측치_처리내역.csv") for n in names if "처리내역" in n))
        for p in out.glob("*_정제.csv"):
            df = pd.read_csv(p, dtype=str, keep_default_na=False)
            self.assertFalse((df == "NaN").any().any(), p.name)                      # 문자열 'NaN'도 남지 않음
            self.assertFalse((df == "").any().any(), p.name)                         # 빈 칸도 남지 않음

    def test_only_option_limits_work(self):
        out = Path(tempfile.mkdtemp())
        self.assertEqual(main(["--src", str(REAL), "--out", str(out), "--only", "실사재고"]), 0)
        self.assertEqual({p.name for p in out.glob("*_정제.csv")}, {"실사재고_정제.csv"})


if __name__ == "__main__":
    unittest.main()
