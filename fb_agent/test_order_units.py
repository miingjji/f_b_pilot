"""order_units: 발주단위 수량 → 앱 구매청구 PK 수량 환산."""
import unittest

from order_units import packs_for, spec_amount


class SpecAmount(unittest.TestCase):
    def test_reads_the_first_amount_in_base_units(self):
        self.assertEqual(spec_amount("1kg/pk"), 1000)
        self.assertEqual(spec_amount("0.25kg/pk"), 250)
        self.assertEqual(spec_amount("500G/PK"), 500)
        self.assertEqual(spec_amount("500ml/ea"), 500)
        self.assertEqual(spec_amount("18L"), 18000)
        self.assertEqual(spec_amount("200g*10pack/box"), 200)

    def test_returns_none_when_there_is_no_amount(self):
        for s in ("골든피트", "이탈리아", "ea", "", None):
            self.assertIsNone(spec_amount(s), s)


class Packs(unittest.TestCase):
    def test_pack_or_each_equal_to_one_pk_stays_as_is(self):
        self.assertEqual(packs_for(3, "팩", "1kg/pk", 1000), (3, ""))
        self.assertEqual(packs_for(2, "개", "2.8kg/ea", 2800), (2, ""))

    def test_box_uses_pk_per_box(self):
        self.assertEqual(packs_for(2, "박스", "200g*10pack/box", 2000), (2, ""))
        self.assertEqual(packs_for(2, "박스", "x", 500, box_pk=4), (8, ""))

    def test_kilogram_orders_are_divided_by_pk_weight(self):
        self.assertEqual(packs_for(3, "킬로그램", "kg", 1000), (3, ""))              # 1 PK = 1kg
        self.assertEqual(packs_for(10, "킬로그램", "5kg/pk", 5000), (2, ""))          # 닭뼈 10kg = 5kg 팩 2개

    def test_bottles_of_a_box_spec_become_one_pk(self):
        self.assertEqual(packs_for(24, "병", "1BOX/24EA", 3000), (1, ""))             # 연태고량125ML 24병 = 1박스 = 1 PK
        self.assertEqual(packs_for(48, "병", "1BOX/24EA", 3000), (2, ""))

    def test_count_based_master_items_keep_the_quantity(self):
        self.assertEqual(packs_for(1.5, "개", "20kg/ea", 1, base_unit="개"), (1.5, ""))   # 세제: 마스터가 개수 기준이라 규격의 20kg 은 무시

    def test_unreadable_spec_keeps_the_order_unit_quantity(self):
        self.assertEqual(packs_for(10, "팩", "이탈리아", 1000), (10, ""))

    def test_real_mismatch_is_flagged_but_not_changed(self):
        q, why = packs_for(2, "개", "20kg/ea", 1000)                                   # 규격이 마스터 1 PK 보다 훨씬 큰 경우
        self.assertEqual(q, 2)
        self.assertIn("확인 필요", why)


if __name__ == "__main__":
    unittest.main()
