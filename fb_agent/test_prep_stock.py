import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prep.blocks import find_row, flatten_header, label
from prep.stock_sheets import (SHEET_COUNT, SHEET_RECEIVING, UnhandledMissingError, clean_inventory_count,
                               clean_receiving)

NA = pd.NA


def grid(rows, ncols):
    """행 목록(칸 수 부족하면 NA로 채움) -> 마크다운에서 읽은 것과 같은 모양의 문자열 DataFrame."""
    data = [list(r) + [NA] * (ncols - len(r)) for r in rows]
    return pd.DataFrame(data, columns=[f"c{i}" for i in range(ncols)], dtype=object)


def count_sheet(body, total=("합 계", 4.0, 2000.0)):
    """실사재고 모양: 제목행, 단위점검 행, 2줄 머리글, 데이터, 빈 행, 합 계 행."""
    rows = [
        [NA, "기말재고 (재고실사)", *[NA] * 9, "*재고조사 기준은 무조건 규격기준"],
        [NA] * 9 + ["단위점검"],
        [NA, "계정명", "품목코드\\n(RMS)", "품목코드\\n(CK)", "품목코드\\n(매장)", "거래처명", "품명", "규격", "과세/면세", "환산단위", "재고실사"],
        [NA] * 10 + ["수량", "중량(g)"],
        *body,
        [NA] * 12,
        [NA, total[0]] + [NA] * 8 + [str(total[1]), str(total[2])],
    ]
    return grid(rows, 14)


BODY = [
    [NA, "반제품", "0202010008", NA, "1000036CK", "CK", "게살", "500g/pk", "과세", "500", "3.76", "1880"],
    [NA, "반제품", "0202010009", NA, NA, "CK", "닭고기", NA, NA, "470", NA, "0"],            # 수량 비고 중량 0
    [NA, "저장품", NA, NA, NA, "다와", "죽용기", "300ea/box", "과세", "1", NA, "0"],          # 코드 없음
    [NA, "원재료", "0101010137", "8060145DM", "1000999", "아워홈", "떡국떡", "1kg", "면세", "1000", "0.12", "120"],
]


class Labels(unittest.TestCase):
    def test_label_normalizes_headers(self):
        cases = {"품목코드\\n(RMS)": "품목코드_RMS", "중량(g)": "중량_g", "과세/면세": "과세면세", "전월\\n미입고": "전월미입고",
                 "입고 횟수": "입고횟수", "  계정명 ": "계정명", "합 계": "합계", "단가(g)": "단가_g"}
        for raw, want in cases.items():
            self.assertEqual(label(raw), want, raw)

    def test_find_row(self):
        df = count_sheet(BODY)
        self.assertEqual(find_row(df, 1, "계정명"), 2)
        self.assertIsNone(find_row(df, 1, "없는값"))

    def test_flatten_two_row_header_with_groups(self):
        df = count_sheet(BODY)
        names = flatten_header(df, 2, last_col=11)
        self.assertEqual(names[1:], ["계정명", "품목코드_RMS", "품목코드_CK", "품목코드_매장", "거래처명", "품명", "규격", "과세면세",
                                     "환산단위", "재고실사_수량", "재고실사_중량_g"])
        self.assertIsNone(names[0])


class InventoryCount(unittest.TestCase):
    def setUp(self):
        self.raw = count_sheet(BODY, total=("합 계", 3.88, 2000.0))
        self.clean, self.report, self.info = clean_inventory_count(self.raw)

    def test_data_block_only_and_no_missing_left(self):
        self.assertEqual(len(self.clean), 4)                       # 제목·머리글·빈 행·합계 행은 제외
        self.assertEqual(int(self.clean.isna().sum().sum()), 0)
        self.assertNotIn("합계", set(self.clean["계정명"]))

    def test_columns_are_flat_and_unnamed_empty_columns_dropped(self):
        self.assertEqual(list(self.clean.columns), ["계정명", "품목코드_RMS", "품목코드_CK", "품목코드_매장", "거래처명", "품명",
                                                    "규격", "과세면세", "환산단위", "재고실사_수량", "재고실사_중량_g"])

    def test_quantity_blank_is_zero_when_weight_zero_and_types_are_numeric(self):
        self.assertEqual(self.clean["재고실사_수량"].tolist(), [3.76, 0.0, 0.0, 0.12])
        self.assertEqual(self.clean["재고실사_중량_g"].tolist(), [1880.0, 0.0, 0.0, 120.0])
        self.assertTrue(pd.api.types.is_float_dtype(self.clean["재고실사_수량"]))

    def test_quantity_is_derived_from_weight_when_weight_nonzero(self):
        body = [[NA, "반제품", "A", NA, NA, "CK", "x", "1kg", "과세", "500", NA, "1000"]]
        clean, report, _ = clean_inventory_count(count_sheet(body, total=("합 계", 2.0, 1000.0)))
        self.assertEqual(clean["재고실사_수량"].tolist(), [2.0])                # 1000g ÷ 500
        self.assertIn("중량", report.set_index("열").loc["재고실사_수량", "규칙"])

    def test_text_blanks_get_labels(self):
        c = self.clean
        self.assertEqual(c["품목코드_CK"].tolist()[:3], ["없음"] * 3)
        self.assertEqual(c["품목코드_매장"].tolist()[1], "없음")
        self.assertEqual(c["품목코드_RMS"].tolist()[2], "없음")
        self.assertEqual(c["규격"].tolist()[1], "미기재")
        self.assertEqual(c["과세면세"].tolist()[1], "미기재")
        self.assertEqual(c["품목코드_CK"].tolist()[3], "8060145DM")           # 있는 값은 그대로

    def test_report_explains_every_filled_cell(self):
        block_nan = int(self.raw.iloc[4:8, 1:12].isna().sum().sum())
        self.assertEqual(int(self.report["채운 개수"].sum()), block_nan)

    def test_totals_row_is_used_as_a_check_not_as_data(self):
        checks = {c["항목"]: c for c in self.info["checks"]}
        self.assertTrue(all(c["ok"] for c in checks.values()), checks)
        self.assertEqual(set(checks), {"재고실사_수량 합계", "재고실사_중량_g 합계"})
        bad, _, info = clean_inventory_count(count_sheet(BODY, total=("합 계", 99.0, 2000.0)))
        self.assertFalse(all(c["ok"] for c in info["checks"]))                # 합계가 안 맞으면 알려줌

    def test_notes_from_title_rows_are_kept(self):
        self.assertTrue(any("재고조사 기준" in n for n in self.info["notes"]))

    def test_weight_blank_or_inconsistent_data_is_not_filled_silently(self):
        body = [[NA, "반제품", "A", NA, NA, "CK", "x", "1kg", "과세", "500", "1", NA]]            # 중량 비어 있음
        with self.assertRaises(UnhandledMissingError):
            clean_inventory_count(count_sheet(body))


def receiving_sheet(body, days=2, summary_total=None):
    """입고내역 모양: 요약 2행, 빈 행, 2줄 머리글(일자 그룹), 데이터, 빈 행, '합 계', 요약 블록('합계')."""
    ncol = 18 + 3 * days + 4
    top = [NA, "계정명", "품목코드\\n(RMS)", "품목코드\\n(CK)", "품목코드\\n(매장)", "거래처명", "품명", "규격", "과세/면세", "단가(g)", "단가",
           "환산단위", "전월\\n미입고", "당월발주", "차이", "당월합계", NA, NA]
    sub = [NA] * 15 + ["수량", "중량(g)", "금액"]
    for d in range(1, days + 1):
        top += [f"{d}일", NA, NA]
        sub += ["수량", "중량(g)", "금액"]
    top += [NA, NA, NA, NA]
    sub += [NA, "입고 횟수", "평균 수량", "코드"]                              # 머리글 없는 보조열
    rows = [[NA] * 5 + ["CK단가\\n적용"], [NA] * 17 + ["[단위 : 원]"], [], top, sub, *body, [], [NA, "합 계"] + [NA] * 10 + ["-"]]
    if summary_total:
        rows += [[], [NA] * 11 + ["합계", NA, NA, NA, *map(str, summary_total)]]
    return grid(rows, ncol)


def rec_row(account, rms, code_ck, supplier, name, spec, tax, unit, order, diff, total, days):
    """total=(수량, 중량, 금액); days=[(수량, 중량, 금액), ...]"""
    row = ["CK과세", account, rms, code_ck, NA, supplier, name, spec, tax, "1.5", "750", unit, NA, order, diff]
    row += [NA if v is None else str(v) for v in total]
    for d in days:
        row += [NA if v is None else str(v) for v in d]
    return row


REC_BODY = [
    rec_row("반제품", "R1", NA, "CK", "게살", "500g/pk", "과세", "500", NA, "-3", (3, 1500, 4500), [(2, 1000, 3000), (1, 500, 1500)]),
    rec_row("원재료", "R2", "C2", "롯데", "사이다", NA, "과세", "10000", "6", "0", (6, 60000, 9000), [(None, 0, 0), (6, 60000, 9000)]),
    rec_row("저장품", "R3", NA, "다와", "용기", "300ea", NA, "1", NA, NA, (0, 0, 0), [(None, 0, 0), (None, 0, 0)]),    # 차이 비어 있음
    rec_row("저장품", "R4", NA, "다와", "빨대", "1ea", "과세", "1", NA, NA, (5, 5, 50), [(None, 0, 0), (5, 5, 50)]),
]


class Receiving(unittest.TestCase):
    def setUp(self):
        self.raw = receiving_sheet(REC_BODY, days=2, summary_total=(14, 61505, 13550))
        self.clean, self.report, self.info = clean_receiving(self.raw)

    def test_only_the_detail_block_is_kept(self):
        self.assertEqual(len(self.clean), 4)
        self.assertEqual(int(self.clean.isna().sum().sum()), 0)
        self.assertEqual(self.clean["계정명"].tolist(), ["반제품", "원재료", "저장품", "저장품"])

    def test_header_is_flattened_with_day_groups(self):
        cols = list(self.clean.columns)
        for name in ("구분", "품목코드_CK", "환산단위", "당월발주", "차이", "당월합계_수량", "당월합계_중량_g", "당월합계_금액",
                     "1일_수량", "1일_중량_g", "1일_금액", "2일_금액"):
            self.assertIn(name, cols)
        self.assertNotIn("전월미입고", cols)                                       # 전부 비어 있는 열은 삭제
        self.assertFalse(any("입고횟수" in c or c.startswith("Unnamed") for c in cols))   # 머리글 없는 보조열 제외
        self.assertIn("전월미입고", self.info["dropped"])

    def test_daily_quantity_blank_becomes_zero_only_when_weight_and_amount_are_zero(self):
        self.assertEqual(self.clean["1일_수량"].tolist(), [2.0, 0.0, 0.0, 0.0])
        self.assertEqual(self.clean["2일_수량"].tolist(), [1.0, 6.0, 0.0, 5.0])
        raw = receiving_sheet([rec_row("반제품", "R1", NA, "CK", "게살", "1kg", "과세", "500", NA, "-1", (1, 500, 10), [(None, 500, 10), (1, 500, 10)])])
        clean, report, _ = clean_receiving(raw)                                   # 중량이 있는데 수량이 비면 환산단위로 계산
        self.assertEqual(clean["1일_수량"].tolist(), [1.0])
        self.assertTrue(report["규칙"].str.contains("환산").any())                   # 환산단위로 계산한 규칙이 기록됨

    def test_order_blank_is_zero_and_difference_is_computed_by_the_verified_formula(self):
        self.assertEqual(self.clean["당월발주"].tolist(), [0.0, 6.0, 0.0, 0.0])
        self.assertEqual(self.clean["차이"].tolist(), [-3.0, 0.0, 0.0, -5.0])     # 당월발주 - 당월합계수량

    def test_text_blank_labels(self):
        c = self.clean
        self.assertEqual(c["품목코드_CK"].tolist(), ["없음", "C2", "없음", "없음"])
        self.assertEqual(c["품목코드_매장"].tolist(), ["없음"] * 4)
        self.assertEqual(c["규격"].tolist()[1], "미기재")
        self.assertEqual(c["과세면세"].tolist()[2], "미기재")

    def test_totals_match_summary_row(self):
        checks = {c["항목"]: c for c in self.info["checks"]}
        self.assertTrue(all(c["ok"] for c in checks.values()), checks)
        self.assertIn("당월합계_금액 합계", checks)
        _, _, bad = clean_receiving(receiving_sheet(REC_BODY, days=2, summary_total=(14, 61505, 99999)))
        self.assertFalse(all(c["ok"] for c in bad["checks"]))

    def test_row_totals_equal_sum_of_days_is_checked(self):
        names = {c["항목"] for c in self.info["checks"]}
        self.assertIn("행별 당월합계 = 일자 합 (금액)", names)

    def test_report_counts_every_filled_cell(self):
        kept = self.raw.iloc[5:9, :24].drop(columns=["c12"])                      # c12(전월미입고)는 열째 삭제라 '채움'이 아님
        self.assertEqual(int(self.report["채운 개수"].sum()), int(kept.isna().sum().sum()))

    def test_unexplained_missing_is_rejected(self):
        bad = [rec_row("반제품", "R1", NA, "CK", "게살", "500g/pk", "과세", "500", NA, "-3", (3, 1500, None), [(2, 1000, 3000), (1, 500, 1500)])]
        with self.assertRaises(UnhandledMissingError) as cm:
            clean_receiving(receiving_sheet(bad))
        self.assertIn("당월합계_금액", str(cm.exception))


REAL = Path(__file__).resolve().parent / "data" / "f_b_menu_data.md"


@unittest.skipUnless(REAL.exists(), "실제 데이터 파일이 없으면 건너뜀")
class RealFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from prep.md_tables import read_sheets
        cls.sheets = read_sheets(REAL)

    def test_real_inventory_count(self):
        clean, report, info = clean_inventory_count(self.sheets[SHEET_COUNT])
        self.assertEqual(len(clean), 901)
        self.assertEqual(int(clean.isna().sum().sum()), 0)
        self.assertTrue(all(c["ok"] for c in info["checks"]), info["checks"])
        self.assertAlmostEqual(clean["재고실사_중량_g"].sum(), 1214559.9, places=1)
        self.assertEqual(int((clean["재고실사_수량"] == 0).sum()), int((clean["재고실사_중량_g"] == 0).sum()))   # 수량 0 ⇔ 중량 0

    def test_real_receiving(self):
        clean, report, info = clean_receiving(self.sheets[SHEET_RECEIVING])
        self.assertEqual(len(clean), 894)
        self.assertEqual(int(clean.isna().sum().sum()), 0)
        failed = [c for c in info["checks"] if not c["ok"]]
        self.assertEqual(failed, [], failed)
        self.assertEqual(round(clean["당월합계_금액"].sum(), 4), 48880256.4209)


if __name__ == "__main__":
    unittest.main()
