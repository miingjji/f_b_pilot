"""실제 매출 조회(sales_data)와 집계 표(prep.sales_aggregates) 검증. 값은 모두 실제 POS 데이터이고, 데이터가 없으면 빈 표다."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import unittest
from datetime import date

import pandas as pd

import sales_data as sd
from prep import sales_aggregates as sa

HAS = sd.available()


def receipt_rows():
    """영수증 3장: 정상 2(둘째는 객수 3, 두 줄), 주문취소 1."""
    cols = ["날짜", "시", "포스번호", "영수증번호", "취소구분", "객수", "메뉴명", "대분류명", "수량", "총매출", "할인", "순매출", "부가세", "결제", "매출시간", "영수증"]
    return pd.DataFrame([
        ["2026-09-01", 12, 1, 1, "정상", 2, "우육면", "면", 1, 16000, 0, 14545, 1455, "신용카드", "12:01:00", "09011-0001"],
        ["2026-09-01", 13, 1, 2, "정상", 3, "탄탄면", "면", 2, 28000, 2000, 23636, 2364, "현금", "13:05:00", "09011-0002"],
        ["2026-09-01", 13, 1, 2, "정상", 3, "우육면", "면", 1, 16000, 0, 14545, 1455, "현금", "13:05:00", "09011-0002"],
        ["2026-09-01", 14, 1, 3, "주문취소", 1, "우육면", "면", -1, -16000, 0, -14545, -1455, "신용카드", "14:00:00", "09011-0003"],
    ], columns=cols)


class Aggregates(unittest.TestCase):
    def setUp(self):
        self.t = sa.aggregate_month(receipt_rows())

    def test_daily_counts_guests_once_per_receipt_and_skips_cancelled_orders(self):
        d = self.t["일자별"].iloc[0]
        self.assertEqual((d["순매출"], d["객수"], d["영수증수"]), (14545 + 23636 + 14545, 5, 2))        # 주문취소는 매출·객수에 넣지 않는다
        self.assertEqual(d["할인"], 2000)

    def test_hourly_menu_payment_and_cancellations(self):
        h = self.t["시간대별"].set_index("시")
        self.assertEqual((h.loc[13, "순매출"], h.loc[13, "객수"], h.loc[13, "영수증수"]), (23636 + 14545, 3, 1))
        m = self.t["메뉴별"].set_index("메뉴명")
        self.assertEqual((m.loc["우육면", "수량"], m.loc["우육면", "순매출"]), (2, 14545 * 2))
        p = self.t["결제별"].set_index("결제")["순매출"]
        self.assertEqual((p["신용카드"], p["현금"]), (14545, 38181))
        c = self.t["취소"].iloc[0]
        self.assertEqual((c["유형"], c["금액"], c["영수증번호"]), ("주문취소", 14545, "09011-0003"))

    def test_pay_group_keeps_the_first_method_of_a_combined_payment(self):
        self.assertEqual([sa.pay_group(x) for x in ("신용카드", "신용카드, 상품권-롯데상품권", "현금", "상품권-롯데포인트", "결제없음")],
                         ["신용카드", "신용카드", "현금", "상품권·기타", "상품권·기타"])


@unittest.skipUnless(HAS, "집계 표가 없음 (python -m prep.sales_aggregates)")
class RealSales(unittest.TestCase):
    def test_period_and_business_days(self):
        self.assertEqual((sd.first_date(), sd.last_date()), (date(2024, 1, 2), date(2026, 10, 29)))
        self.assertEqual(len(sd.daily(date(2024, 1, 1), date(2026, 9, 30))), 965)

    def test_daily_matches_pos_and_receipts_within_a_tiny_gap(self):
        agg = pd.read_csv(sa.OUT / "일자별.csv")
        pos = sd.daily(date(2024, 1, 1), date(2026, 9, 30))
        gap = abs(pos["sales"].sum() - agg["순매출"].sum()) / pos["sales"].sum()
        self.assertLess(gap, 0.001)                                           # 영수증 집계와 POS 일자별은 0.1% 안쪽으로 같다

    def test_known_day(self):
        d = sd.day_sales(date(2025, 12, 31))
        self.assertEqual(d["sales"], 6815929)                                 # 12/31 순매출은 POS 값 (수불부 요약은 7,430,202)

    def test_closed_or_unknown_days_are_empty_not_invented(self):
        self.assertIsNone(sd.day_sales(date(2026, 2, 17)))                   # 설날: 휴점
        self.assertIsNone(sd.day_sales(date(2030, 1, 1)))
        self.assertTrue(sd.daily(date(2030, 1, 1), date(2030, 1, 31)).empty)
        self.assertTrue(sd.hourly(date(2030, 1, 1)).empty)
        self.assertEqual(int(sd.payment_share(date(2030, 1, 1), date(2030, 1, 31))["금액"].sum()), 0)
        self.assertTrue(sd.menu_table(date(2030, 1, 1), date(2030, 1, 31)).empty)
        self.assertTrue(sd.receipts(date(2030, 1, 1)).empty)

    def test_anchor_and_latest_day(self):
        self.assertEqual(sd.anchor(date(2026, 10, 31)), date(2026, 10, 29))
        self.assertEqual(sd.anchor(date(2026, 3, 1)), date(2026, 3, 1))
        self.assertEqual(sd.latest_day(date(2026, 2, 17)), date(2026, 2, 15))   # 설 전날(2/16)·설날(2/17) 휴점 → 2/15(일)

    def test_menu_and_payment_totals_follow_daily_sales(self):
        a, b = date(2026, 9, 1), date(2026, 9, 30)
        sales = int(sd.daily(a, b)["sales"].sum())
        for got in (int(sd.menu_table(a, b)["매출"].sum()), int(sd.payment_share(a, b)["금액"].sum()), int(sd.hourly(date(2026, 9, 30))["sales"].sum() > 0)):
            self.assertTrue(got > 0)
        self.assertLess(abs(int(sd.menu_table(a, b)["매출"].sum()) - sales) / sales, 0.001)
        self.assertLess(abs(int(sd.payment_share(a, b)["금액"].sum()) - sales) / sales, 0.001)
        self.assertAlmostEqual(float(sd.payment_share(a, b)["비중(%)"].sum()), 100, delta=0.2)

    def test_menu_table_has_top_menus_then_other_last(self):
        t = sd.menu_table(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(list(t["메뉴"][:-1]), sorted(t["메뉴"][:-1], key=lambda m: -int(t.set_index("메뉴").loc[m, "매출"])))
        self.assertEqual(t["메뉴"].iloc[-1], "기타")
        self.assertLessEqual(len(t), sd.MENU_KEEP + 1)

    def test_monthly_and_series(self):
        m = sd.monthly(date(2026, 9, 30), 12)
        self.assertEqual((len(m), m["month"].iloc[-1]), (12, "2026-09"))
        s = sd.menu_series(date(2026, 9, 30), "month", 3)
        self.assertEqual(list(s.index), ["2026-07", "2026-08", "2026-09"])
        self.assertEqual(len(sd.menu_series(date(2026, 9, 30), "day", 5)), 5)
        self.assertFalse(sd.menu_series(date(2026, 9, 30), "hour", 0).empty)

    def test_cancellations_have_only_known_columns(self):
        c = sd.cancellations(date(2026, 9, 30), 90)
        self.assertEqual(list(c.columns), ["일시", "영수증번호", "유형", "금액"])        # 사유·처리자는 원본에 없어 만들지 않는다
        self.assertTrue(set(c["유형"]) <= {"매출취소", "주문취소", "메뉴취소"})

    def test_settlement_by_payment_uses_the_monthly_report(self):
        s = sd.settlement_by_payment("2026-09")
        self.assertEqual(len(s), 6)
        self.assertTrue(sd.settlement_by_payment("2030-01").empty)

    def test_receipts_come_from_the_month_source(self):
        r = sd.receipts(date(2026, 9, 30))
        self.assertGreater(len(r), 10)
        lines = sd.receipt_lines(date(2026, 9, 30), r.iloc[0]["영수증번호"])
        self.assertEqual(int(lines["금액"].sum()), int(r.iloc[0]["금액"]))


if __name__ == "__main__":
    unittest.main()
