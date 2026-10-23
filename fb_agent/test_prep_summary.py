import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import unittest
from pathlib import Path

import pandas as pd

from prep.blocks import UnhandledMissingError
from prep.summary_sheets import SHEET_SUMMARY, clean_summary

NA = pd.NA


def grid(rows, ncols=16):
    data = [list(r) + [NA] * (ncols - len(r)) for r in rows]
    return pd.DataFrame(data, columns=[f"c{i}" for i in range(ncols)], dtype=object)


def summary_sheet(profit=("1000", "10", "100"), stray=True):
    """수불요약 모양: 수불 마감표, 매출 지표, 로스, COST 비율, 차이 순위(금액/중량), 폐기 월계, 사용량 품목이 쌓인 보고서."""
    sales, guests, per = profit
    rank_head = [
        [NA, "구분", "순위", "품목코드\\n(RMS)", "품명", NA, "규격", "기말재고", NA, "실사재고", NA, "차이"],
        [NA] * 7 + ["중량(g)", "금액", "중량(g)", "금액", "중량(g)", "금액"],
    ]
    rank_rows = [
        [NA, "로스", "1", "C1", "돼지사골", NA, "5kg", "100", "200", "40", "80", "60", "120"],
        [NA, NA, "2", "C2", "쌀", NA, "20kg", "50", "100", "20", "40", "30", "60"],              # 구분 병합 셀(빈칸)
        [NA, "역로스", "1", "C3", "전분", NA, "1kg", "-10", "-20", "0", "0", "-10", "-20", NA, "223"],
    ]
    rows = [
        [NA, "수불 마감", *[NA] * 9, "[단위 : 원]"],
        [],
        [NA, "계정명", "기초재고", "입고", NA, "출고", NA, NA, NA, NA, NA, "기말재고"],
        [NA, NA, NA, "구매", "매장이동 입고", "원재료비", "잡비", "소모품비", "복리후생비", "재고자산폐기손실", "매장이동 출고"],
        [NA, "원재료", "100", "50", "0", "30", "1", NA, "0", "2", "0", "117"],
        [NA, "저장품", "0", "10", "0", NA, NA, "10", NA, NA, "0", "0"],
        [NA, "합계", "100", "60", "0", "30", "1", "10", "0", "2", "0", "117", NA, NA, "15000000"] if stray
        else [NA, "합계", "100", "60", "0", "30", "1", "10", "0", "2", "0", "117"],
        [],
        [NA, "COST", NA, NA, NA, "Loss", NA, NA, "검은글씨 : 로스", "적색글씨 : 역로스"],
        [],
        [NA, "매출", sales, NA, NA, NA, "이론사용", "실사기준 사용", "로스 금액", "로스율"],
        [NA, "객수", guests, NA, NA, "원재료", "80", "100", "20", "0.2"],
        [NA, "객단가", per, NA, NA, "반제품", "40", "30", "-10", "-0.333333333333"],
        [NA, "구분", "원재료", "소모품", NA, "합계", "120", "130", "10", "0.076923076923"],
        [NA, "전달재고", "0.05", "0"],
        [NA, "입고", "0.3", "0.01"],
        [NA, "이달재고", "0.07", "0"],
        [NA, "COST(%)", "0.26", "0.01"],
        [],
        [NA, "표준, 실사 차이발생 순위 (금액기준)", *[NA] * 9, "검은글씨 : 로스"],
        [],
        *rank_head, *rank_rows,
        [],
        [NA, "표준, 실사 차이발생 순위 (중량기준)"],
        [],
        *rank_head, *rank_rows[:1],
        [],
        [NA, "일일 폐기 품목 월계"],
        [],
        [NA, "품명", "전월", NA, "당월"],
        [NA, NA, "폐기량(g)", "폐기금액(원)", "폐기량(g)", "폐기금액(원)", "사용량(g) 대비", "판매액(원) 대비", NA, "코드"],
        [NA, "짜사이", "45705", "259693.9", "0", "0", "0", NA, NA, "0102010012"],
        [NA, "밥", "29825", NA, "73600", NA, NA, NA, NA, NA],
        [NA, "타_폐기 기준(Dead 미포함)"],
        [NA, "실사 기준 사용량 품목(기본제공)"],
        [],
        [NA, "코드", "품명", NA, "총 사용", NA, "1인당 제공", NA, "매출대비"],
        [NA] * 4 + ["중량(g)", "금액(원)", "중량(g)", "금액(원)"],
        [NA, "0101030002", "곡성식초", NA, "68500", "315767.39", "9.04", "41.67", "0.019266"],
        [NA, "0101010074", "양조간장", NA, "18000", "101666.2", "2.37", "13.41", NA],
        [NA, "제품에 사용되는 재료부분은 제외필요"],
    ]
    return grid(rows)


class Summary(unittest.TestCase):
    def setUp(self):
        self.raw = summary_sheet()
        self.tables, self.report, self.info = clean_summary(self.raw)

    def test_every_block_becomes_its_own_table(self):
        self.assertEqual(list(self.tables), ["수불마감", "매출지표", "로스요약", "COST비율", "차이순위_금액기준", "차이순위_중량기준",
                                             "폐기월계", "실사기준_사용량"])

    def test_no_missing_values_in_any_table(self):
        for name, t in self.tables.items():
            self.assertEqual(int(t.isna().sum().sum()), 0, name)

    def test_ledger_flattened_header_zero_fill_and_stray_value_ignored(self):
        t = self.tables["수불마감"]
        self.assertEqual(list(t.columns), ["계정명", "기초재고", "입고_구매", "입고_매장이동입고", "출고_원재료비", "출고_잡비", "출고_소모품비",
                                          "출고_복리후생비", "출고_재고자산폐기손실", "출고_매장이동출고", "기말재고"])
        self.assertEqual(t["계정명"].tolist(), ["원재료", "저장품", "합계"])
        self.assertEqual(t["출고_소모품비"].tolist(), [0.0, 10.0, 10.0])               # 원재료의 빈 소모품비는 0
        self.assertEqual(t["출고_원재료비"].tolist(), [30.0, 0.0, 30.0])
        self.assertTrue(any("15000000" in n for n in self.info["notes"]))              # 표 밖 값은 알려주고 제외
        self.assertNotIn("15000000", t.astype(str).to_string())

    def test_kpis(self):
        t = self.tables["매출지표"]
        self.assertEqual(t["지표"].tolist(), ["매출", "객수", "객단가"])
        self.assertEqual(t["값"].tolist(), [1000.0, 10.0, 100.0])

    def test_loss_summary(self):
        t = self.tables["로스요약"]
        self.assertEqual(list(t.columns), ["구분", "이론사용", "실사기준사용", "로스금액", "로스율"])
        self.assertEqual(t["구분"].tolist(), ["원재료", "반제품", "합계"])
        self.assertAlmostEqual(t["로스율"].tolist()[1], -10 / 30, places=9)

    def test_cost_ratio(self):
        t = self.tables["COST비율"]
        self.assertEqual(list(t.columns), ["항목", "원재료", "소모품"])
        self.assertEqual(t["항목"].tolist(), ["전달재고", "입고", "이달재고", "COST(%)"])

    def test_rank_tables_fill_merged_category_and_drop_unlabeled_column(self):
        t = self.tables["차이순위_금액기준"]
        self.assertEqual(t["구분"].tolist(), ["로스", "로스", "역로스"])                # 병합 셀의 빈칸은 위 값
        self.assertEqual(t["순위"].tolist(), [1, 2, 1])
        self.assertEqual(list(t.columns), ["구분", "순위", "품목코드_RMS", "품명", "규격", "기말재고_중량_g", "기말재고_금액",
                                          "실사재고_중량_g", "실사재고_금액", "차이_중량_g", "차이_금액"])
        self.assertEqual(len(self.tables["차이순위_중량기준"]), 1)
        self.assertTrue(any("머리글 없는" in n for n in self.info["notes"]))

    def test_disposal_table_blanks(self):
        t = self.tables["폐기월계"]
        self.assertEqual(t["품명"].tolist(), ["짜사이", "밥"])
        self.assertEqual(t["코드"].tolist(), ["0102010012", "없음"])
        self.assertEqual(t["전월_폐기금액_원"].tolist(), [259693.9, 0.0])
        self.assertEqual(int(t.isna().sum().sum()), 0)

    def test_usage_table_drops_mostly_empty_ratio_column(self):
        t = self.tables["실사기준_사용량"]
        self.assertNotIn("매출대비", t.columns)
        self.assertEqual(t["품명"].tolist(), ["곡성식초", "양조간장"])
        self.assertTrue(any("매출대비" in d for d in self.info["dropped"]))
        self.assertEqual(t["코드"].tolist()[0], "0101030002")

    def test_all_identities_hold_on_good_data(self):
        failed = [c for c in self.info["checks"] if not c["ok"]]
        self.assertEqual(failed, [])
        names = {c["항목"] for c in self.info["checks"]}
        for must in ("수불마감: 기초+입고−출고=기말 (불일치 행 수)", "수불마감: 합계행 = 계정별 합 (불일치 열 수)", "객단가 = 매출 ÷ 객수",
                     "로스요약: 로스금액 = 실사−이론 (불일치 행 수)", "로스요약: 로스율 = 로스금액 ÷ 실사기준사용 (불일치 행 수)",
                     "차이순위_금액기준: 차이 = 기말−실사 (불일치 칸 수)"):
            self.assertIn(must, names)

    def test_broken_identities_are_reported(self):
        bad = summary_sheet(profit=("1000", "10", "999"))                              # 객단가가 맞지 않음
        _, _, info = clean_summary(bad)
        self.assertFalse(next(c for c in info["checks"] if c["항목"] == "객단가 = 매출 ÷ 객수")["ok"])
        raw = summary_sheet()
        raw.iat[4, 11] = "999"                                                         # 원재료 기말재고를 틀리게
        _, _, info = clean_summary(raw)
        self.assertFalse(next(c for c in info["checks"] if c["항목"].startswith("수불마감: 기초+입고−출고=기말"))["ok"])

    def test_report_names_are_prefixed_with_table(self):
        r = self.report.set_index("열")
        self.assertEqual(int(r.loc["수불마감.출고_소모품비", "채운 개수"]), 1)
        self.assertIn("차이순위_금액기준.구분", r.index)
        self.assertEqual(int(r.loc["폐기월계.코드", "채운 개수"]), 1)

    def test_unexplained_missing_is_rejected(self):
        raw = summary_sheet()
        raw.iat[11, 2] = NA                                                            # 객수 비어 있음
        with self.assertRaises(UnhandledMissingError):
            clean_summary(raw)

    def test_missing_blocks_raise_clear_errors(self):
        with self.assertRaisesRegex(ValueError, "계정명"):
            clean_summary(grid([[NA, "아무거나"]]))


REAL = Path(__file__).resolve().parent / "data" / "f_b_menu_data.md"


@unittest.skipUnless(REAL.exists(), "실제 데이터 파일이 없으면 건너뜀")
class RealFile(unittest.TestCase):
    def test_real_sheet(self):
        from prep.md_tables import read_sheet
        tables, report, info = clean_summary(read_sheet(REAL, SHEET_SUMMARY))
        for name, t in tables.items():
            self.assertEqual(int(t.isna().sum().sum()), 0, name)
        failed = [c for c in info["checks"] if not c["ok"]]
        self.assertEqual(failed, [], failed)
        led = tables["수불마감"].set_index("계정명")
        self.assertAlmostEqual(led.loc["합계", "기말재고"], 11681725.58004, places=3)
        kp = tables["매출지표"].set_index("지표")["값"]
        self.assertEqual((kp["매출"], kp["객수"]), (169804535.0, 7578.0))
        self.assertEqual(len(tables["차이순위_금액기준"]), 20)
        self.assertEqual(len(tables["차이순위_중량기준"]), 20)


if __name__ == "__main__":
    unittest.main()
