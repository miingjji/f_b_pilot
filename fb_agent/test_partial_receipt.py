"""구매발주서 입고: 발주보다 적게(또는 많이) 들어왔을 때의 처리 (receive_po)."""
import unittest
from datetime import date
from unittest import mock

from views import purchase


class State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class Base(unittest.TestCase):
    def setUp(self):
        item = next(iter(purchase.ITEMS))
        self.item = item
        self.ss = State(purchase_orders=[{"발주번호": "PO-0001", "거래처": "구드래", "품목": item, "수량(PK)": 3.0, "발주일": date(2026, 10, 27),
                                         "입고예정": date(2026, 10, 30), "입고수량(PK)": 0.0, "상태": "입고대기"}], receipts=[])
        self.stock = []
        patches = [mock.patch.object(purchase, "ss", self.ss), mock.patch.object(purchase, "add_stock", lambda i, p: self.stock.append((i, p))),
                   mock.patch.object(purchase, "get_today", lambda: date(2026, 10, 30))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def po(self):
        return self.ss.purchase_orders[0]


class PartialReceiptTest(Base):
    def test_full(self):
        purchase.receive_po("PO-0001", 3.0, None, "", "")
        self.assertEqual((self.po()["상태"], self.po()["입고수량(PK)"], self.stock), ("입고완료", 3.0, [(self.item, 3.0)]))

    def test_short_then_wait_then_rest(self):
        purchase.receive_po("PO-0001", 2.0, purchase.WAIT_REST, "거래처 수량 부족", "")
        self.assertEqual((self.po()["상태"], self.po()["입고수량(PK)"], purchase.po_remaining(self.po())), ("입고대기", 2.0, 1.0))
        self.assertIn("부족", self.ss.receipts[0]["비고"])
        purchase.receive_po("PO-0001", 1.0, None, "", "")                                   # 나머지 1PK 가 나중에 들어옴
        self.assertEqual((self.po()["상태"], self.po()["입고수량(PK)"], self.stock), ("입고완료", 3.0, [(self.item, 2.0), (self.item, 1.0)]))

    def test_short_then_close(self):
        purchase.receive_po("PO-0001", 2.0, purchase.CLOSE_REST, "오배송", "기사 확인")
        self.assertEqual((self.po()["상태"], self.stock), ("부분입고", [(self.item, 2.0)]))
        self.assertIn("오배송", self.ss.receipts[0]["비고"])
        purchase.receive_po("PO-0001", 1.0, None, "", "")                                   # 마감된 발주서는 다시 처리되지 않는다
        self.assertEqual(len(self.stock), 1)

    def test_over(self):
        purchase.receive_po("PO-0001", 4.0, None, "", "")
        self.assertEqual((self.po()["상태"], self.stock), ("입고완료", [(self.item, 4.0)]))
        self.assertIn("초과", self.ss.receipts[0]["비고"])


class ReturnTest(Base):
    """초과 입고분 반품: 등록은 회수 대기, 재고는 회수 완료 때 차감."""

    def setUp(self):
        super().setUp()
        self.ss.returns = []
        purchase.receive_po("PO-0001", 4.0, None, "", "")                                   # 3 발주 → 4 입고 (초과 1)
        self.stock.clear()
        self.rc = self.ss.receipts[0]["입고번호"]

    def test_over_needs_return_until_completed(self):
        po = self.po()
        self.assertEqual((purchase.po_over(po), purchase.po_over_left(po), purchase.po_tone(po)), (1.0, 1.0, "over"))
        self.assertIsNone(purchase.create_return(self.rc, 1.0, "초과입고", "", "PO-0001"))
        self.assertEqual((self.ss.returns[0]["상태"], self.stock, purchase.po_over_left(po), purchase.po_tone(po)), ("회수대기", [], 0.0, "over"))   # 아직 재고 그대로
        self.assertIn("회수 대기", purchase.po_gap_label(po))
        with mock.patch.object(purchase.st, "toast"):
            purchase.complete_return("RT-0001")
        self.assertEqual((self.ss.returns[0]["상태"], self.stock, purchase.po_tone(po)), ("회수완료", [(self.item, -1.0)], ""))
        self.assertIn("회수 완료", purchase.po_gap_label(po))

    def test_cancel_keeps_stock_and_frees_quantity(self):
        purchase.create_return(self.rc, 1.0, "초과입고", "", "PO-0001")
        with mock.patch.object(purchase.st, "toast"):
            purchase.cancel_return("RT-0001")
            purchase.complete_return("RT-0001")                                             # 취소한 건은 완료 처리되지 않는다
        self.assertEqual((self.ss.returns[0]["상태"], self.stock, purchase.po_over_left(self.po())), ("취소", [], 1.0))

    def test_cannot_return_more_than_received_in_total(self):
        self.assertIsNone(purchase.create_return(self.rc, 3.0, "품질 불량"))
        self.assertIsNotNone(purchase.create_return(self.rc, 2.0, "품질 불량"))            # 입고 4 중 3은 이미 반품 등록 → 1만 가능
        self.assertIsNone(purchase.create_return(self.rc, 1.0, "품질 불량"))
        self.assertIsNotNone(purchase.create_return(self.rc, 0.5, "품질 불량"))


if __name__ == "__main__":
    unittest.main()
