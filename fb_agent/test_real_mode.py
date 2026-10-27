"""실제 마스터(data/real)로 앱을 띄웠을 때의 동작 검증. 환경변수는 import 시점에 정해지므로 별도 프로세스에서 실행한다."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HAS_REAL = (ROOT / "data" / "real" / "items.csv").exists()
if HAS_REAL:
    import csv
    with open(ROOT / "data" / "real" / "items.csv", encoding="utf-8-sig") as f:
        CSV_ITEMS = sum(1 for _ in csv.DictReader(f))
    with open(ROOT / "data" / "real" / "suppliers.csv", encoding="utf-8-sig") as f:
        CSV_SUPPLIERS = sum(1 for _ in csv.DictReader(f))

PROBE = r"""
import json, re, sys
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

# 1) 가상 시드가 없어야 함 (발주서·입고·일정이 비어 있다)
out["seed_ok"] = not render("recv-by-po").exception

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


# 3-1) 시뮬레이션 재고: 마지막 월말 실사(9/30) 이후 날짜에만 쓰고 안내한다
SIM = '''
import streamlit as st
from datetime import date
from state import init_state
init_state()
st.session_state.cfg_today = date({y}, {m}, {d})
import views
from menu import get_leaf
views.render(get_leaf({leaf!r}))
'''
def render_at(leaf, y, m, d):
    return AppTest.from_string(SIM.format(leaf=leaf, y=y, m=m, d=d), default_timeout=120).run()
note = lambda at: [i.value for i in at.markdown if "시뮬레이션" in i.value]   # 접힌 안내 안의 본문
s_after, s_before, s_input = render_at("po-auto", 2026, 10, 24), render_at("po-auto", 2026, 9, 15), render_at("stock-input", 2026, 10, 24)
rows_of = lambda at: max((len(d.value) for d in at.dataframe if "총재고" in d.value.columns), default=0)
inp = lambda at: [c.value for c in at.caption if "개 표시 / 전체" in c.value]
rows_default, hidden_caption, input_caption = rows_of(s_after), [c.value for c in s_after.caption if "활동 있는 품목" in c.value], inp(s_input)   # 스위치를 켜기 전 값
toggle_label = s_after.toggle[0].label
rows_all = rows_of(s_after.toggle[0].set_value(True).run())                       # 같은 AppTest 가 다시 실행된다 (이후 s_after 는 전체 품목 상태)
input_caption_all = inp(s_input.toggle[0].set_value(True).run())
out["sim"] = {"rows_default": rows_default, "rows_all": rows_all, "hidden_caption": hidden_caption, "toggle_label": toggle_label,
              "input_caption": input_caption, "input_caption_all": input_caption_all, "exc2": [],
              "after": note(s_after), "before": note(s_before), "input": [x.label for x in s_input.expander if "추정값" in x.label],
              "cols_after": sorted({c for d in s_after.dataframe for c in d.value.columns}),
              "closed_wd": list(s_after.session_state["cfg_closed_wd"]),
              "todo_after": next((int(re.search(r"\((\d+)개\)", h.value).group(1)) for h in s_after.subheader if h.value.startswith("우선 처리")), None),
              "todo_before": next((int(re.search(r"\((\d+)개\)", h.value).group(1)) for h in s_before.subheader if h.value.startswith("우선 처리")), None),
              "exc": [e.message[:200] for at in (s_after, s_before, s_input) for e in at.exception]}

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
    "plan_expander": [any("앞으로 2주 발주 예정" in x.label for x in at.expander) for at in (a1, a2)],
    "sim_caption": [any("시뮬레이션 재고를 참고로" in c.value for c in at.caption) for at in (a1, a2)],
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
        env = {k: v for k, v in os.environ.items() if k not in ("FB_MASTER", "FB_MASTER_DIR")}
        p = subprocess.run([sys.executable, "-c", PROBE % {"root": str(ROOT)}], capture_output=True, text=True, env=env, cwd=ROOT,
                           timeout=600)
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("JSON:")), None)
        if line is None:
            raise AssertionError(f"프로브 실패:\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
        cls.r = json.loads(line[5:])

    def test_real_master_is_active(self):
        self.assertEqual((self.r["items"], self.r["suppliers"]), (CSV_ITEMS, CSV_SUPPLIERS))
        self.assertIn("실제 데이터", self.r["label"])
        self.assertEqual(self.r["stores"][0], "수원점")                        # 실제 재고의 매장이 첫 번째

    def test_no_seeded_demo_records(self):
        self.assertTrue(self.r["seed_ok"])

    def test_screens_render_without_exceptions(self):
        self.assertEqual(self.r["exceptions"], {})

    def test_po_auto_caps_cards_and_offers_bulk_request(self):
        self.assertLessEqual(self.r["po_auto_cards"], 10)
        self.assertEqual(len(self.r["po_auto_captions"]), 1)
        self.assertEqual(len(self.r["po_auto_buttons"]), 1)

    def test_po_auto_uses_simulated_stock_after_the_last_count(self):
        r = self.r["sim"]
        self.assertEqual(r["exc"], [])
        self.assertEqual(len(r["after"]), 1)
        self.assertIn("9월 30일 월말 실사", r["after"][0])
        self.assertIn("10월 23일 마감", r["after"][0])                                    # 10-24 아침 재고 = 10-23 마감 재고
        self.assertEqual(r["closed_wd"], [])                                             # 일요일에도 영업 (일요일 휴무는 데모 기본값이었다)
        self.assertLessEqual(r["todo_after"], 20)                                         # 10-24 우선 처리: 실제 입고·오는 중인 주문을 반영한 값 (긴급 + 지금·곧 발주)
        self.assertIn("이미 오는 중인 입고", r["after"][0])                                  # 발주 판단에 더한 입고 예정을 안내
        self.assertIn("오는 중 입고", r["cols_after"])
        self.assertEqual(len(r["input"]), 1)                                              # 재고 입력 화면에는 접힌 안내의 제목으로
        self.assertEqual(r["before"], [])                                                 # 실사 전 날짜에는 안내 없음

    def test_item_lists_show_only_items_with_recent_activity_by_default(self):
        r = self.r["sim"]
        self.assertEqual(r["exc2"], [])
        self.assertEqual(r["toggle_label"], "활동 없는 품목도 보기")
        self.assertEqual(r["rows_all"], CSV_ITEMS)                                        # 스위치를 켜면 전체 품목
        self.assertTrue(100 <= r["rows_default"] <= 260, r["rows_default"])               # 기본은 활동 있는 품목(약 170개) + 발주가 필요한 품목
        self.assertEqual(len(r["hidden_caption"]), 1)
        self.assertIn(f"{r['rows_default']}개만", r["hidden_caption"][0])
        self.assertEqual(len(r["input_caption"]), 1)
        self.assertIn("보고 있어요", r["input_caption"][0])                               # 재고 입력도 같은 기본값
        self.assertTrue(r["input_caption_all"][0].endswith(f"전체 {CSV_ITEMS}개"))        # 켜면 811개 모두, 안내 문구도 없다

    def test_po_engine_screen(self):
        r = self.r["engine"]
        self.assertEqual(r["exc"], [])
        self.assertGreaterEqual(r["orders_rows"], 10)                                  # 2026-10-01(목) 에는 실제 추천이 여러 건
        self.assertGreaterEqual(r["sup_cards"], 2)                                     # 거래처마다 카드와 '이 업체 청구' 버튼
        self.assertEqual(r["kpis"], ["발주 추천", "거래처", "시즌 시작 예상", "재고 확인 필요"])
        self.assertEqual(r["plan_expander"], [True, True])                              # 발주일 예측(시뮬레이션)이 있는 날짜에는 '앞으로 2주 발주 예정'
        self.assertEqual(r["sim_caption"], [False, True])                                # 10-01 은 실사 후 14일 안(실사 추정), 10-21 은 시뮬레이션 재고를 참고로
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
        self.assertEqual(self.r["recs"], CSV_ITEMS)
        self.assertLessEqual(self.r["answer_lines"], 8)
        self.assertTrue(self.r["answer_has_total"])
        self.assertLessEqual(self.r["stock_lines"], 8)

    def test_calendar_groups_busy_days(self):
        self.assertGreater(self.r["grouped_events"], 0)
        self.assertLessEqual(self.r["max_events_per_day"], 15)                  # 묶기 전에는 하루 35건


class MasterSelection(unittest.TestCase):
    """마스터는 항상 data/real, 테스트만 FB_MASTER_DIR 로 바꾼다. 매장은 실제 매장 하나."""

    @staticmethod
    def probe(**env) -> str:
        base = {k: v for k, v in os.environ.items() if k not in ("FB_MASTER", "FB_MASTER_DIR")}
        p = subprocess.run([sys.executable, "-c", "import config; print(config.MASTER_DIR.name, config.TEST_MASTER, config.STORES)"],
                           capture_output=True, text=True, env={**base, **env}, cwd=ROOT, timeout=120)
        return p.stdout.strip()

    def test_default_is_real_master_with_one_store(self):
        self.assertEqual(self.probe(), "real False ('수원점',)")

    def test_test_directory_override(self):
        self.assertEqual(self.probe(FB_MASTER_DIR=str(ROOT / "testdata" / "master")), "master True ('수원점',)")


if __name__ == "__main__":
    unittest.main()
