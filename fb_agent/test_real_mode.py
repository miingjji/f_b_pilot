"""FB_MASTER=real 로 앱을 띄웠을 때의 동작 검증. 환경변수는 import 시점에 정해지므로 별도 프로세스에서 실행한다."""
import testenv  # noqa: F401  (FB_MASTER=sample 고정)
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HAS_REAL = (ROOT / "data" / "real" / "items.csv").exists()

PROBE = r"""
import json, sys
sys.path.insert(0, %(root)r)
from datetime import date
import data, menu
from streamlit.testing.v1 import AppTest

out = {"label": data.DATASET_LABEL, "items": len(data.ITEMS), "suppliers": len(data.SUPPLIERS), "stores": list(menu.STORES)}
SCRIPT = '''
import streamlit as st
from state import init_state
init_state()
import views
from menu import get_leaf
views.render(get_leaf({leaf!r}))
'''
def render(leaf):
    return AppTest.from_string(SCRIPT.format(leaf=leaf), default_timeout=120).run()

# 1) 시드 발주서가 현재 마스터의 품목이어야 함
from state import _seed_purchase_orders
seeds = _seed_purchase_orders(date.today())
out["seed_ok"] = not render("recv-by-po").exception
out["seeds"] = [(p["품목"] in data.ITEMS, data.ITEMS[p["품목"]].supplier.name == p["거래처"]) for p in seeds]

# 2) 화면 렌더링
leaves = ["home-dashboard", "po-auto", "po-engine", "stock-input", "stock-forecast", "stock-flow", "po-leadtime", "set-items", "set-suppliers",
          "ai-alerts", "ai-report", "recv-general", "po-request"]
exc = {l: [e.message[:120] for e in render(l).exception] for l in leaves}
out["exceptions"] = {k: v for k, v in exc.items() if v}

# 3) 자동 발주 추천: 카드는 8개까지, 나머지는 안내 + 일괄 청구 버튼
at = render("po-auto")
out["po_auto_captions"] = [c.value for c in at.caption if "나머지" in c.value]
out["po_auto_buttons"] = [b.label for b in at.button if "전체 구매청구" in b.label]
out["po_auto_cards"] = len([b for b in at.button if b.label == "구매청구 만들기"])


# 3-2) 발주 추천 (이력 기반): 자료가 있는 날 / 자료가 끝난 뒤 / 발주일이 아닌 날
ENGINE = '''
import streamlit as st
from datetime import date
from state import init_state
init_state()
st.session_state.cfg_today = date({y}, {m}, {d})
import views
from menu import get_leaf
views.render(get_leaf("po-engine"))
'''
def render_engine(y, m, d):
    return AppTest.from_string(ENGINE.format(y=y, m=m, d=d), default_timeout=300).run()
a1, a2, a3 = render_engine(2026, 10, 1), render_engine(2026, 10, 21), render_engine(2026, 10, 4)
btn = [b for b in a1.button if b.label.startswith("구매청구 만들기")]
n0 = len(a1.session_state["purchase_requests"])
made = a2_ = None
if btn:
    a1 = btn[0].click().run()
    made = len(a1.session_state["purchase_requests"]) - n0
    btn = [b for b in a1.button if b.label.startswith("구매청구 만들기")]
    a1 = btn[0].click().run()                                     # 한 번 더 누르면 이미 청구한 품목은 건너뛴다
    again = len(a1.session_state["purchase_requests"]) - n0 - made
    reqs = a1.session_state["purchase_requests"][n0:]
else:
    again, reqs = None, []
out["engine_req"] = {"button": len(btn), "made": made, "again": again, "items_in_master": all(r["품목"] in data.ITEMS for r in reqs),
                     "positive": all(r["수량(PK)"] > 0 for r in reqs), "memo": reqs[0]["메모"] if reqs else ""}
out["engine"] = {
    "exc": [e.message[:200] for at in (a1, a2, a3) for e in at.exception],
    "orders_rows": sum(len(d.value) for d in a1.dataframe),
    "sup_cards": len([b for b in a1.button if b.key and b.key.startswith("po_engine_req_")]),
    "kpis": [m.label for m in a1.metric],
    "warn_ok": len(a1.warning), "warn_stale": len(a2.warning), "sunday_success": len(a3.success),
    "download": [b.label for b in a1.get("download_button")] if hasattr(a1, "get") else [],
}

# 4) 에이전트 응답 길이, 달력 일정 묶기
ctx_at = AppTest.from_string('''
import streamlit as st
from collections import Counter
from state import init_state
init_state()
from agent_context import build_context
from agent import answer
ctx = build_context()
st.session_state["_ans"] = answer("지금 발주해야 할 품목은?", ctx)
st.session_state["_ans2"] = answer("재고 현황 요약", ctx)
st.session_state["_recs"] = len(ctx.recs)
ev = [e for evs in ctx.events.values() for e in evs if e.category == "order"]
per_day = Counter(e.day for e in ev)
st.session_state["_max_day"] = max(per_day.values()) if per_day else 0
st.session_state["_grouped"] = sum("개 품목" in e.title for e in ev)
''', default_timeout=120).run()
ss = ctx_at.session_state
out["answer_lines"] = ss["_ans"].count("\n- **")
out["answer_has_total"] = "외 " in ss["_ans"]
out["stock_lines"] = ss["_ans2"].count("\n- **")
out["recs"] = ss["_recs"]
out["max_events_per_day"] = ss["_max_day"]
out["grouped_events"] = ss["_grouped"]
print("JSON:" + json.dumps(out, ensure_ascii=False))
"""


@unittest.skipUnless(HAS_REAL, "data/real 이 없으면 건너뜀 (python -m prep.app_master 로 생성)")
class RealMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, "FB_MASTER": "real"}
        p = subprocess.run([sys.executable, "-c", PROBE % {"root": str(ROOT)}], capture_output=True, text=True, env=env, cwd=ROOT,
                           timeout=600)
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("JSON:")), None)
        if line is None:
            raise AssertionError(f"프로브 실패:\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
        cls.r = json.loads(line[5:])

    def test_real_master_is_active(self):
        self.assertEqual((self.r["items"], self.r["suppliers"]), (855, 45))
        self.assertIn("실제 데이터", self.r["label"])
        self.assertEqual(self.r["stores"][0], "수원점")                        # 실제 재고의 매장이 첫 번째

    def test_seed_orders_use_real_items(self):
        self.assertTrue(self.r["seed_ok"])
        self.assertTrue(len(self.r["seeds"]) == 3 and all(a and b for a, b in self.r["seeds"]), self.r["seeds"])

    def test_screens_render_without_exceptions(self):
        self.assertEqual(self.r["exceptions"], {})

    def test_po_auto_caps_cards_and_offers_bulk_request(self):
        self.assertLessEqual(self.r["po_auto_cards"], 8)
        self.assertEqual(len(self.r["po_auto_captions"]), 1)
        self.assertEqual(len(self.r["po_auto_buttons"]), 1)

    def test_po_engine_screen(self):
        r = self.r["engine"]
        self.assertEqual(r["exc"], [])
        self.assertGreaterEqual(r["orders_rows"], 10)                                  # 2026-10-01(목) 에는 실제 추천이 여러 건
        self.assertGreaterEqual(r["sup_cards"], 2)                                     # 거래처마다 카드와 '이 업체 청구' 버튼
        self.assertEqual(r["kpis"], ["발주 추천", "거래처", "시즌 시작 예상", "재고 확인 필요"])
        self.assertEqual(r["warn_ok"], 0)                                              # 자료 끝 3일 안이면 경고 없음
        self.assertEqual(r["warn_stale"], 1)                                           # 자료가 끝난 뒤(10-21)에는 경고
        self.assertEqual(r["sunday_success"], 1)                                       # 일요일은 발주일이 아니라는 안내
        self.assertEqual(len(r["download"]), 1)

    def test_po_engine_can_make_purchase_requests_once(self):
        r = self.r["engine_req"]
        self.assertEqual(r["button"], 1)
        self.assertGreaterEqual(r["made"], 10)                                         # 추천 대부분이 마스터에 있어 청구가 만들어진다
        self.assertEqual(r["again"], 0)                                                # 같은 품목은 두 번 청구하지 않는다
        self.assertTrue(r["items_in_master"] and r["positive"])
        self.assertIn("이력 기반 발주 추천", r["memo"])

    def test_agent_answers_are_short_even_with_hundreds_of_items(self):
        self.assertEqual(self.r["recs"], 855)
        self.assertLessEqual(self.r["answer_lines"], 8)
        self.assertTrue(self.r["answer_has_total"])
        self.assertLessEqual(self.r["stock_lines"], 8)

    def test_calendar_groups_busy_days(self):
        self.assertGreater(self.r["grouped_events"], 0)
        self.assertLessEqual(self.r["max_events_per_day"], 15)                  # 묶기 전에는 하루 35건


class ModeSelection(unittest.TestCase):
    """FB_MASTER 가 없으면 data/real 이 있을 때만 실제 모드, 값이 있으면 그대로 따른다."""

    @staticmethod
    def mode(**env) -> str:
        base = {k: v for k, v in os.environ.items() if k != "FB_MASTER"}
        p = subprocess.run([sys.executable, "-c", "import config; print(config.MASTER_MODE)"], capture_output=True, text=True,
                           env={**base, **env}, cwd=ROOT, timeout=120)
        return p.stdout.strip()

    @unittest.skipUnless(HAS_REAL, "data/real 이 없으면 건너뜀")
    def test_auto_picks_real_when_data_exists(self):
        self.assertEqual(self.mode(), "real")

    def test_explicit_sample_always_wins(self):
        self.assertEqual(self.mode(FB_MASTER="sample"), "sample")

    def test_auto_falls_back_to_sample_without_real_data(self):
        # data/real 이 없는 저장소를 흉내: config 가 보는 경로를 존재하지 않는 곳으로 바꿔 확인
        code = ("import config, pathlib; config.REAL_ITEMS = pathlib.Path('/nonexistent/items.csv'); "
                "print(config._mode())")
        base = {k: v for k, v in os.environ.items() if k != "FB_MASTER"}
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=base, cwd=ROOT, timeout=120)
        self.assertEqual(p.stdout.strip(), "sample")


if __name__ == "__main__":
    unittest.main()
