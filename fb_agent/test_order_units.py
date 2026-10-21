"""order_units: 발주단위 수량 → 앱 구매청구 PK 수량 환산."""
import unittest

from order_units import box_pack, item_units, order_unit, packs_for, pk_per_unit, qty_text, spec_amount, stock_text


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


class OrderUnit(unittest.TestCase):
    def test_history_unit_wins_then_spec_suffix_then_pack(self):
        self.assertEqual(order_unit("375ml*12ea/box", "박스"), "박스")
        self.assertEqual(order_unit("375ml*12ea/box"), "박스")
        self.assertEqual(order_unit("1kg/pk"), "팩")
        self.assertEqual(order_unit("20g/1ea"), "개")
        self.assertEqual(order_unit("24btl"), "병")
        self.assertEqual(order_unit("골든피트"), "팩")

    def test_pk_per_unit_matches_packs_for(self):
        self.assertEqual(pk_per_unit("박스", "375ml*12ea/box", 4500, 1.0, "g"), 1.0)      # 1박스 = 마스터 1 PK
        self.assertAlmostEqual(pk_per_unit("킬로그램", "1kg", 4500, 1.0, "g"), 1000 / 4500, places=2)
        self.assertEqual(pk_per_unit("개", "1ea", 1, 1.0, "개"), 1.0)


class BoxPack(unittest.TestCase):
    def test_reads_each_amount_and_count_per_box(self):
        self.assertEqual(box_pack("375ml*12ea/box"), (375.0, 12, "ea"))
        self.assertEqual(box_pack("2.5kg*8pk/BOX"), (2500.0, 8, "pk"))
        self.assertEqual(box_pack("6병/box"), (None, 6, "병"))
        self.assertEqual(box_pack("330ml/30ea"), (330.0, 30, "ea"))
        self.assertIsNone(box_pack("1kg/pk"))
        self.assertIsNone(box_pack("500ml/ea"))

    def test_liquor_stock_and_order_are_counted_in_bottles(self):
        u = item_units("서울의밤_375ml*12ea/box (0105010023)", "신합상사", "g", 4500, 1, "박스")
        self.assertEqual((u.unit, u.each, u.count, u.per), ("박스", "병", 12, 1.0))
        self.assertEqual(stock_text(u, 7500, 4500), "20병")
        self.assertEqual(qty_text(u, 2), "24병 (2박스)")

    def test_box_of_packs_uses_the_box_amount_not_box_pk(self):
        u = item_units("다크초콜렛(칼리바우트)_2.5kg*8pk/BOX", "x", "g", 2500, 1, None)
        self.assertEqual((u.unit, u.each, u.per), ("박스", "팩", 8.0))                 # 1박스 = 8 PK(2.5kg)
        self.assertEqual(packs_for(1, "박스", "2.5kg*8pk/BOX", 2500, 1, "g")[0], 8.0)

    def test_count_only_specs_and_unrounded_ratio(self):
        self.assertEqual(box_pack("24ea/box"), (None, 24, "ea"))
        u = item_units("설화맥주500ML", "신합상사", "g", 6000, 1, "박스")                 # 500ml 12병 = 1박스
        self.assertEqual((u.each, u.count), ("병", 12))
        self.assertEqual(stock_text(u, 4500, 6000), "9병")
        v = item_units("연태고량125ML", "서정주류", "g", 3000, 1, "병")                  # 1 PK = 24병, 발주는 병 단위
        self.assertEqual(stock_text(v, 2125, 3000), "17병")
        self.assertEqual(qty_text(v, 48), "48병")

    def test_inner_multiplied_specs_keep_one_pack(self):
        self.assertEqual(pk_per_unit("팩", "5g*1000ea/pk", 5000, 1.0, "g"), 1.0)
        self.assertEqual(pk_per_unit("팩", "25g*24ea*16pk/box", 9600, 1.0, "g"), 1.0)
        self.assertEqual(pk_per_unit("팩", "50장(400g)/pk", 450, 1.0, "g"), 1.0)

    def test_supplies_default_to_pieces_and_food_to_packs(self):
        self.assertEqual(item_units("BK_K-2안전화(250)", "x", "개", 1).unit, "개")
        self.assertEqual(item_units("매트지2 (세트용)", "x", "g", 1000).unit, "팩")
        self.assertEqual(item_units("얼음_1kg*12ea/box(D-2)", "x", "g", 12000).unit, "박스")


if __name__ == "__main__":
    unittest.main()
