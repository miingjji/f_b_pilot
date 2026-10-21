"""prep.lead_consumption_2026: 리드타임 표와 소비율 표의 계산 규칙."""
import unittest

import pandas as pd

from prep.lead_consumption_2026 import consumption, lead_by_supplier, lead_by_weekday, received_orders


def req(rows):
    cols = ["거래처", "청구일자", "청구번호", "납기일자", "입고일자", "처리상태"]
    return pd.DataFrame(rows, columns=cols)


class LeadTime(unittest.TestCase):
    def setUp(self):
        self.req = req([
            ["A", "2026-01-05", "1", "2026-01-07", "2026-01-07", "입고"],      # 월 청구, 리드 2
            ["A", "2026-01-05", "1", "2026-01-07", "2026-01-07", "입고"],      # 같은 청구의 다른 품목행 → 한 건
            ["A", "2026-01-09", "2", "2026-01-10", "2026-01-12", "입고"],      # 금 청구, 리드 3, 납기 2일 지연
            ["A", "2026-01-10", "3", "2026-01-11", "미입고", "미입고"],         # 제외
            ["B", "2026-01-06", "4", "2026-01-07", "2026-01-07", "입고"],
        ])
        self.o = received_orders(self.req)

    def test_counts_orders_not_lines_and_skips_unreceived(self):
        self.assertEqual(self.o.groupby("거래처").size().to_dict(), {"A": 2, "B": 1})

    def test_supplier_table(self):
        s = lead_by_supplier(self.o, self.req[self.req["처리상태"] == "입고"].groupby("거래처").size()).set_index("거래처")
        self.assertEqual(s.loc["A", "리드타임_최대"], 3)
        self.assertEqual(s.loc["A", "품목행수"], 3)
        self.assertEqual(s.loc["A", "납기준수율(%)"], 50.0)
        self.assertEqual(s.loc["A", "권장_리드타임_일"], 3)                  # p90 올림
        self.assertEqual(s.loc["A", "주_발주요일"], "월금")

    def test_weekday_table(self):
        w = lead_by_weekday(self.o).set_index(["거래처", "청구요일"])
        self.assertEqual(w.loc[("A", "금요일"), "중앙값"], 3)


class Consumption(unittest.TestCase):
    def test_rate_is_receipts_per_million_of_net_sales(self):
        daily = pd.DataFrame({"매출일자": ["2026-01-01", "2026-01-02", "2026-02-01"], "순매출": [1_000_000, 1_000_000, 2_000_000]})
        k = dict(품목코드_RMS="X", 품명="대파", 규격="1kg", 입고단위="팩", 거래처명="A")
        rcv = pd.DataFrame([{**k, "입고일자": "2026-01-02", "입고수량": 4.0, "입고금액": 100, "입고유형": "입고"},
                            {**k, "입고일자": "2026-02-01", "입고수량": 4.0, "입고금액": 100, "입고유형": "입고"},
                            {**k, "입고일자": "2026-02-01", "입고수량": -1.0, "입고금액": -25, "입고유형": "반품"}])          # 반품은 뺀다
        c = consumption(rcv, daily).iloc[0]
        self.assertEqual(c["총입고수량"], 8.0)
        self.assertAlmostEqual(c["소비율_전체(100만원당)"], 2.0)             # 8 ÷ 4(백만원)
        self.assertAlmostEqual(c["소비율_2026-01"], 2.0)                    # 4 ÷ 2
        self.assertAlmostEqual(c["소비율_2026-02"], 2.0)                    # 4 ÷ 2
        self.assertAlmostEqual(c["소비율_월별_변동계수"], 0.0)
        self.assertEqual(c["신뢰도"], "낮음")


if __name__ == "__main__":
    unittest.main()
