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

    def test_check_flags_zero_huge_and_sudden_changes_but_not_ordinary_edits(self):
        j = dataclasses.replace(ITEMS["짜사이"], daily_usage_g=500.0, usage_known=True)     # 1PK=1,000g, 하루 500g
        base = (0, 4, 0)                                                                    # 추정 4PK = 4,000g (8일치)
        chk = lambda now: purchase.entry_check(j, now, base)
        self.assertEqual(chk((0, 4, 0)), "추정값")                                           # 건드리지 않은 행
        self.assertEqual(chk((0, 5, 0)), "입력함")                                           # 조금 다른 값은 그냥 입력
        self.assertEqual(chk((0, 0, 0)), "확인 필요 · 0으로 입력")
        self.assertEqual(chk((0, 20, 0)), "확인 필요 · 추정의 5배")
        self.assertEqual(chk((0, 1, 0)), "확인 필요 · 추정의 1/4")
        self.assertEqual(chk((0, 2, 0)), "입력함")                                           # 4,000 → 2,000 은 절반이라 3배 미만
        self.assertEqual(chk((0, 0, 900)), "확인 필요 · 추정의 1/4")                          # 900g: 4,000 의 1/4.4
        self.assertEqual(chk((0, 40, 0)), "확인 필요 · 소비 80일치")                          # 40,000g 은 소비 60일치(30,000g)를 넘는다 — 배수보다 먼저 알려 준다
        self.assertEqual(chk((0, -1, 0)), "확인 필요 · 입력 확인")
        self.assertEqual(chk((0, float("nan"), 0)), "확인 필요 · 입력 확인")

    def test_check_does_not_guess_when_there_is_no_estimate_or_usage(self):
        j = dataclasses.replace(ITEMS["짜사이"], usage_known=False, daily_usage_g=0.0)
        self.assertEqual(purchase.entry_check(j, (0, 7, 0), (0, 0, 0)), "입력함")           # 추정이 0이면 비교할 기준이 없고, 소비를 모르면 일수도 못 잰다
        self.assertEqual(purchase.entry_check(j, (0, 48300, 0), (0, 0, 0)), "확인 필요 · 너무 큰 값")   # 그래도 48,300kg(5만 kg 가까이)은 한 품목으로 불가능하다
        n = dataclasses.replace(ITEMS["냅킨"], usage_known=False, daily_usage_g=0.0)         # 개수 품목은 5만 개 기준
        self.assertEqual(purchase.entry_check(n, (0, 0, 60000), (0, 0, 0)), "확인 필요 · 너무 큰 값")
        self.assertEqual(purchase.entry_check(n, (0, 0, 40000), (0, 0, 0)), "입력함")

    def test_number_columns_reject_negative_values_and_name_the_unit_of_loose_counts(self):
        cfg = purchase.ENTRY_CONFIG
        self.assertEqual(purchase.ENTRY_COLUMNS, ["품목", "BOX", "PK", "낱개", "합계", "확인", "환산 기준"])
        for k in ("BOX", "PK", "낱개"):
            self.assertIsNotNone(cfg[k])
        self.assertIn("기본단위", str(cfg["낱개"]))


if __name__ == "__main__":
    unittest.main()
