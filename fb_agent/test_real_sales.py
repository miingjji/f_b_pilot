"""FB_MASTER=real 에서 매출 화면이 실제 매출(수원점 2025-12)을 쓰는지 검증. 환경변수는 import 시점에 정해지므로 별도 프로세스에서 실행한다."""
import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HAS_DATA = (ROOT / "data" / "cleaned" / "매출입력_정제.csv").exists() and (ROOT / "data" / "organized" / "일자별_매출.csv").exists()

PROBE = r"""
import json, sys
sys.path.insert(0, %(root)r)
from datetime import date
import pandas as pd
import sample_data as sd
import menu
from streamlit.testing.v1 import AppTest

st, end, first = "수원점", date(2025, 12, 31), date(2025, 12, 1)
org = pd.read_csv("data/organized/일자별_매출.csv")
d = sd.daily_sales(st, end, 31)
out = {"net_ok": bool((d["sales"].values == org["순매출"].values).all()), "cust_ok": bool((d["customers"].values == org["객수"].values).all()),
       "net_total": int(d["sales"].sum())}
mt = sd.menu_table(st, first, end)
out["menu_total"], out["menu_last"] = int(mt["매출"].sum()), mt.iloc[-1]["메뉴"]
ps = sd.payment_share(st, first, end)
out["pay_total"] = int(ps["금액"].sum())
day = date(2025, 12, 5)
rc = sd.receipts(st, day)
out["rcpt_total"] = int(rc["금액"].sum()); out["day_net"] = int(org[org["매출일자"] == "2025-12-05"]["순매출"].iloc[0])
out["line_total"] = int(sd.receipt_lines(st, day, rc["영수증번호"].iloc[0])["금액"].sum()); out["head_amount"] = int(rc["금액"].iloc[0])
out["hour_total"] = int(sd.hourly_sales(st, day)["sales"].sum())
out["series_day_total"] = int(sd.menu_series(st, end, "day", 31).to_numpy().sum())
out["series_hour_total"] = int(sd.menu_series(st, end, "hour", 11).to_numpy().sum())
out["end_net"] = int(org["순매출"].iloc[-1])
out["settle_net"] = int(sd.settlement(st, end, 31)["순매출"].sum())
out["cancel_types"] = sorted(sd.cancellations(st, end)["유형"].unique())
# 실제 데이터 밖 날짜와 다른 매장은 가상 값이지만 비어 있지 않아야 함
out["virtual_ok"] = all(int(sd.day_sales(s, date(2026, 3, 3))["sales"]) > 0 for s in ("수원점", "강남점", "홍대점"))
d26 = sd.daily_sales(st, date(2026, 10, 15), 300)
d26 = d26[d26["date"] >= "2026-01-01"]
wk = d26.groupby(d26["date"].dt.weekday)["sales"].mean()
out["sat_over_mon"] = float(wk[5] / wk[0])
out["real_sat_over_mon"] = float(sd.daily_sales(st, end, 31).groupby(lambda i: date(2025, 12, 1 + i).weekday())["sales"].median()[5]
                                  / sd.daily_sales(st, end, 31).groupby(lambda i: date(2025, 12, 1 + i).weekday())["sales"].median()[0])
out["days_2026"] = int(len(d26)); out["min_2026"] = int(d26["sales"].min())
out["holiday_lift"] = float(sd.day_sales(st, date(2026, 2, 17))["sales"] / sd.day_sales(st, date(2026, 2, 10))["sales"])   # 설날(화) vs 평소 화요일
out["deterministic"] = sd.day_sales(st, date(2026, 5, 5)) == sd.day_sales(st, date(2026, 5, 5))
out["hours_2026_total"] = int(sd.hourly_sales(st, date(2026, 3, 3))["sales"].sum()); out["day_2026"] = int(sd.day_sales(st, date(2026, 3, 3))["sales"])
out["virtual_menu_names"] = list(sd.menu_series("강남점", date(2026, 3, 3), "day", 3).columns)[:2]

SCRIPT = '''
import streamlit as st
from state import init_state
init_state()
import views
from menu import get_leaf
views.render(get_leaf({leaf!r}))
'''
leaves = [l.id for l in menu.all_leaves() if l.view.split(".")[0] in ("sales", "menu", "pay", "cancel", "settle")]
exc = {}
for l in leaves:
    at = AppTest.from_string(SCRIPT.format(leaf=l), default_timeout=120).run()
    if at.exception:
        exc[l] = [e.message[:120] for e in at.exception]
out["leaves"], out["exceptions"] = len(leaves), exc
print("JSON:" + json.dumps(out, ensure_ascii=False))
"""


@unittest.skipUnless(HAS_DATA, "data/cleaned·organized 가 없으면 건너뜀 (python -m prep, python -m prep.organize)")
class RealSales(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, "FB_MASTER": "real"}
        p = subprocess.run([sys.executable, "-c", PROBE % {"root": str(ROOT)}], capture_output=True, text=True, env=env, cwd=ROOT,
                           timeout=900)
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("JSON:")), None)
        if line is None:
            raise AssertionError(f"프로브 실패:\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
        cls.r = json.loads(line[5:])

    def test_daily_matches_organized_file(self):
        self.assertTrue(self.r["net_ok"] and self.r["cust_ok"])
        self.assertEqual(self.r["net_total"], 169_804_335)

    def test_every_view_of_the_month_adds_up_to_the_same_net_sales(self):
        t = self.r["net_total"]
        for k in ("menu_total", "pay_total", "series_day_total", "settle_net"):
            self.assertEqual(self.r[k], t, k)

    def test_receipts_and_hours_match_the_day(self):
        self.assertEqual(self.r["rcpt_total"], self.r["day_net"])
        self.assertEqual(self.r["hour_total"], self.r["day_net"])
        self.assertEqual(self.r["series_hour_total"], self.r["end_net"])      # 메뉴×시간 표도 마지막 날 순매출과 같다
        self.assertEqual(self.r["line_total"], self.r["head_amount"])

    def test_menu_table_puts_other_last_and_cancel_types_are_real(self):
        self.assertEqual(self.r["menu_last"], "기타")
        self.assertEqual(self.r["cancel_types"], ["매출취소", "메뉴취소", "주문취소"])

    def test_outside_real_period_is_virtual_with_real_menu_mix(self):
        self.assertTrue(self.r["virtual_ok"])
        self.assertNotIn("짜장면", self.r["virtual_menu_names"])

    def test_2026_is_filled_with_weekday_pattern_of_the_real_month(self):
        self.assertGreaterEqual(self.r["days_2026"], 200)
        self.assertGreater(self.r["min_2026"], 0)
        self.assertGreater(self.r["sat_over_mon"], 2)                                     # 토요일이 월요일보다 훨씬 큼 (실제 12월도 같은 패턴)
        self.assertGreater(self.r["real_sat_over_mon"], 2)
        self.assertGreater(self.r["holiday_lift"], 1.0)                                  # 설날이 평소 같은 요일보다 큼
        self.assertTrue(self.r["deterministic"])

    def test_virtual_hours_add_up_to_the_virtual_day(self):
        self.assertAlmostEqual(self.r["hours_2026_total"], self.r["day_2026"], delta=self.r["day_2026"] * 0.01)

    def test_all_sales_screens_render(self):
        self.assertGreaterEqual(self.r["leaves"], 20)
        self.assertEqual(self.r["exceptions"], {})


if __name__ == "__main__":
    unittest.main()
