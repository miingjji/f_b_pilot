"""실제 브라우저(Playwright)로 화면을 점검하고 스크린샷을 저장하는 e2e 스크립트.

    python e2e/check_ui.py [--out docs/screenshots] [--port 8799] [--skip-all-leaves]

서버를 직접 띄웠다 종료한다. 설치/환경은 e2e/README.md 참고.
"""
import argparse
import csv
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from menu import DEFAULT_LEAF, RAILS, STORES, all_leaves, breadcrumb  # noqa: E402

SB = '[data-testid="stSidebar"]'
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
N_ITEMS = sum(1 for _ in csv.DictReader(open(ROOT / "data" / "real" / "items.csv", encoding="utf-8-sig")))   # 품목 마스터 개수
failures = []


def check(cond: bool, msg: str):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def wait_server(port: int, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2).read() == b"ok":
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("서버가 시작되지 않았습니다.")


def login(page):
    """처음 접속하면 로그인 화면이 나온다. 아이디·비밀번호를 비워 두고 로그인 버튼만 눌러 들어간다 (주소는 그대로라 같은 화면이 열린다)."""
    page.get_by_role("button", name="로그인").first.wait_for(timeout=30000)
    page.get_by_role("button", name="로그인").first.click()


def open_app(browser, url, width, height, path="", wait="h1:not(:has-text('로그인'))", settle=3500, **ctx):
    page = browser.new_context(viewport={"width": width, "height": height}, **ctx).new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(url + path)
    login(page)
    page.wait_for_selector(wait, timeout=30000)
    page.wait_for_timeout(settle)   # 폭 측정 후 재실행까지 대기
    return page, errs


def rail_button(page, icon_name: str):
    return page.locator(f"{SB} button", has_text=icon_name).first


def leaf_button(page, title: str):
    return page.locator(f"{SB} button", has_text=title).first


def day_grid_buttons(page):
    """달력 격자의 날짜 버튼 (이름이 숫자인 버튼, 오늘은 '15 오늘')."""
    out = []
    for n in range(1, 32):
        loc = page.get_by_role("button", name=re.compile(rf"^{n}(\s+오늘)?$"))
        if loc.count():
            bb = loc.first.bounding_box()
            if bb:
                out.append((n, bb["x"], bb["y"]))
    return out


def first_metric(page) -> str:
    return page.locator('[data-testid="stMetricValue"]').first.inner_text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--skip-all-leaves", action="store_true", help="소메뉴 전체 방문 점검 생략(약 3분)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    url = f"http://localhost:{a.port}"

    srv = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                            "--server.port", str(a.port), "--browser.gatherUsageStats", "false"],
                           cwd=ROOT, env={k: v for k, v in os.environ.items() if k != "FB_MASTER_DIR"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_server(a.port)
        with sync_playwright() as p:
            br = p.chromium.launch()

            # 0) 로그인: 처음 접속하면 로그인 화면, 비워 두고 로그인하면 들어가고 주소는 유지, 로그아웃하면 다시 로그인 화면
            ctx = br.new_context(viewport={"width": 1440, "height": 860})
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(url + "/po-auto")
            pg.get_by_role("button", name="로그인").first.wait_for(timeout=30000)
            pg.wait_for_timeout(1500)
            check(pg.get_by_role("heading", name="로그인").count() == 1 and pg.get_by_label("아이디").count() == 1 and pg.get_by_label("비밀번호").count() == 1,
                  "처음 접속: 로그인 화면(제목·아이디·비밀번호)")
            check(pg.get_by_placeholder("메뉴 검색").count() == 0, "로그인 전에는 메뉴·본문이 보이지 않음")
            pg.screenshot(path=out / "00_login_1440.png")
            pg.get_by_role("button", name="로그인").first.click()
            pg.wait_for_selector("h1:has-text('자동 발주 추천')", timeout=30000)
            check(pg.url.rstrip("/").endswith("/po-auto"), "아이디·비밀번호 없이 로그인 → 열려던 화면(/po-auto)으로 들어감")
            pg.get_by_role("button", name=re.compile("데모 사용자")).click()
            pg.get_by_role("button", name="로그아웃").click()
            pg.get_by_role("button", name="로그인").first.wait_for(timeout=15000)
            check(pg.get_by_role("heading", name="로그인").count() == 1, "로그아웃 → 로그인 화면으로 돌아옴")
            check(not errs, "로그인: JS 에러 없음")
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(1500)
            check(pg.get_by_role("button", name="로그인").first.is_visible() and pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
                  "390px: 로그인 버튼이 보이고 가로 스크롤 없음")
            pg.screenshot(path=out / "00_login_390.png")
            ctx.close()

            # 1) 넓은 화면: 레일 6개 + 서브 패널 + 본문 + 우측 고정 에이전트
            pg, errs = open_app(br, url, 1920, 1080, wait="text=달력 대시보드")
            check(pg.get_by_role("heading", name="F&B Agent").count() == 1, "1920px: 에이전트가 우측에 고정됨")
            icons = [r.icon.strip(":").split("/")[1] for r in RAILS]
            check(all(rail_button(pg, i).count() for i in icons), f"좌측 아이콘 {len(icons)}개 표시 ({', '.join(icons)})")
            check(pg.get_by_placeholder("메뉴 검색").count() == 1, "서브 패널 상단에 메뉴 검색창")
            check(pg.locator('[data-testid="stSelectbox"]').count() >= 1, "헤더에 매장 선택 드롭다운")
            check(pg.get_by_role("button", name=re.compile("데모 사용자")).count() == 1 and pg.get_by_role("button", name="회원가입").count() == 0,
                  "헤더에 로그인한 사용자 메뉴(로그인·회원가입 버튼은 없음)")
            check(all(pg.get_by_text(t, exact=True).count() >= 1 for t in ("오늘 발주", "오늘 입고", "확인할 이상징후", "오늘 일정")), "홈: '오늘 할 일' 카드 4개")
            check(pg.locator('[data-testid="stMetricValue"]').count() >= 2, "요약 카드(매출·객수) 표시")
            pg.screenshot(path=out / "01_home_dock_1920.png")
            check(not errs, "홈: JS 에러 없음")

            # 2) 레일 → 아코디언(대/중/소) → 소메뉴 이동
            rail_button(pg, "payments").click()
            pg.wait_for_timeout(1500)
            check(pg.locator(f"{SB} summary", has_text="매출분석").count() >= 1, "매출 레일: 대메뉴(매출분석) 펼침")
            check(pg.locator(f"{SB} summary", has_text="매출요약").count() >= 1, "매출 레일: 중메뉴(매출요약) 표시")
            pg.locator(f"{SB} summary", has_text="매출요약").first.click()
            pg.wait_for_timeout(700)
            check(leaf_button(pg, "일자별").count() >= 1, "중메뉴 펼치면 소메뉴(일자별) 표시")
            pg.screenshot(path=out / "02_sales_accordion.png")
            leaf_button(pg, "일자별").click()
            pg.wait_for_url(re.compile(r"/sales-daily$"), timeout=15000)
            pg.wait_for_selector("h1:has-text('일자별')", timeout=15000)
            check(True, "소메뉴 클릭 → /sales-daily 로 전환, 제목 '일자별'")
            check(pg.get_by_text("매출분석 › 매출요약 › 일자별").count() >= 1, "브레드크럼 표시")
            pg.wait_for_timeout(1500)
            pg.screenshot(path=out / "03_sales_daily.png")

            # 3) 매장 선택: 실제 데이터가 있는 매장은 수원점 하나
            check(pg.locator('[data-testid="stSelectbox"] input').first.input_value() == "수원점", "매장 선택은 수원점")

            # 4) 메뉴 검색 (초성 포함)
            pg.get_by_placeholder("메뉴 검색").fill("시간대")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2000)
            check(pg.get_by_text("검색 결과 3건").count() == 1, "검색 '시간대' → 3건")
            pg.screenshot(path=out / "04_menu_search.png")
            pg.get_by_placeholder("메뉴 검색").fill("ㅇㅈㅂ")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2000)
            check(pg.get_by_text("검색 결과").count() >= 1 and pg.get_by_text("일치하는 메뉴가 없어요").count() == 0,
                  "초성 검색 'ㅇㅈㅂ' 동작")
            leaf_button(pg, "일자별").first.click()
            pg.wait_for_timeout(2500)
            check(pg.get_by_placeholder("메뉴 검색").input_value() == "", "이동하면 검색어가 지워짐")

            # 5) 즐겨찾기: 헤더 별 → 즐겨찾기 레일에 표시 → 다시 누르면 해제
            star = pg.locator('[data-testid="stMain"] button', has_text="star").first
            star.click()
            pg.wait_for_timeout(1500)
            rail_button(pg, "star").click()
            pg.wait_for_timeout(1500)
            check(pg.get_by_text("즐겨찾기가 없어요").count() == 0 and leaf_button(pg, "일자별").count() >= 1,
                  "즐겨찾기 추가 → 즐겨찾기 레일에 표시")
            pg.screenshot(path=out / "05_favorites.png")
            star.click()
            pg.wait_for_timeout(1500)
            check(pg.get_by_text("즐겨찾기가 없어요").count() == 1, "즐겨찾기 해제 → 목록이 비어 안내 표시")
            pg.context.close()

            # 6) 레일마다 대표 화면 스크린샷 + 홈 복귀
            pg, errs = open_app(br, url, 1920, 1080, path="/po-auto")
            pg.screenshot(path=out / "06_purchase_auto_order.png", full_page=True)
            pg.context.close()
            pg, errs = open_app(br, url, 1920, 1080, path="/hr-schedule")
            pg.screenshot(path=out / "07_hr_schedule.png", full_page=True)
            pg.context.close()
            pg, errs = open_app(br, url, 1920, 1080, path="/ai-alerts")
            pg.screenshot(path=out / "08_ai_alerts.png", full_page=True)
            pg.context.close()
            pg, errs = open_app(br, url, 1920, 1080, path="/ai-chat-order")
            check(pg.get_by_role("heading", name="F&B Agent").count() == 0, "Q&A 화면: 우측 패널은 숨기고 본문이 대화창")
            check(pg.get_by_placeholder("재고, 발주, 일정에 대해 물어보세요").count() == 1, "Q&A 화면: 대화 입력창 1개")
            pg.get_by_text("지금 발주해야 할 품목은?").first.click()
            pg.wait_for_timeout(3500)
            check(pg.get_by_text("발주가 필요한 품목").count() >= 1, "Q&A 화면에서 질문 → 답변")
            pg.screenshot(path=out / "09_ai_chat.png")
            pg.context.close()

            # 6-2) 품목 마스터 · 재고 입력 필터 · 발주 추천 · 품목별 리드타임 (실제 마스터)
            pg, errs = open_app(br, url, 1600, 1000, path="/set-items")
            check(pg.get_by_text(f"{N_ITEMS}개 / 전체 {N_ITEMS}개").count() == 1, f"품목 마스터: 전체 {N_ITEMS}개 표시")
            check(pg.get_by_role("button", name="CSV 내려받기").count() == 1 and pg.get_by_role("button", name="JSON 내려받기").count() == 1,
                  "품목 마스터: CSV/JSON 다운로드 버튼")
            pg.locator('[data-testid="stButtonGroup"]').get_by_text("소모품", exact=True).click()
            pg.wait_for_timeout(2000)
            n_sup = re.search(rf"(\d+)개 / 전체 {N_ITEMS}개", pg.locator("body").inner_text())
            check(bool(n_sup) and 0 < int(n_sup.group(1)) < N_ITEMS, f"품목 마스터: 대분류 '소모품' 필터 → {n_sup.group(1) if n_sup else '?'}개")
            pg.screenshot(path=out / "14_item_master.png", full_page=True)
            pg.context.close()

            pg, errs = open_app(br, url, 1600, 1000, path="/stock-input")
            shown = lambda: int(re.search(rf"(\d+)개 표시 / 전체 {N_ITEMS}개", pg.locator("body").inner_text()).group(1))
            n0 = shown()
            check(0 < n0 < N_ITEMS, f"재고 입력: 기본은 최근 45일 활동 품목만 ({n0}개 / 전체 {N_ITEMS}개)")
            pg.locator('[data-testid="stButtonGroup"]').get_by_text("저장품", exact=True).click()
            pg.wait_for_timeout(2000)
            n1 = shown()
            check(0 < n1 < n0, f"재고 입력: 분류 '저장품' → {n1}개")
            pg.get_by_placeholder("품목명 또는 코드").fill("쌀")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2000)
            check(0 < shown() < n1, f"재고 입력: 검색 '쌀' → {shown()}개")
            pg.screenshot(path=out / "15_stock_input_filtered.png", full_page=True)
            pg.context.close()

            pg, errs = open_app(br, url, 1600, 1000, path="/po-auto")
            check(pg.get_by_role("button", name=re.compile(r"전체 구매청구 만들기")).count() == 1, "자동 발주 추천: 우선 처리 품목 일괄 청구 버튼")
            check(pg.get_by_text("재고가 언제 떨어지는지").count() >= 1 and pg.get_by_text("발주 추천 (이력 기반)").count() >= 1, "자동 발주 추천: 역할 안내와 이력 기반 화면 링크")
            pg.screenshot(path=out / "16_po_auto.png", full_page=True)
            check(not errs, "발주 추천: JS 에러 없음")
            pg.context.close()

            pg, errs = open_app(br, url, 1600, 1000, path="/stock-flow")
            check(pg.get_by_text("업체", exact=True).count() >= 1 and pg.get_by_placeholder("품목명 · 품목코드 · 규격").count() == 1, "수불현황: 업체 선택과 품목 검색란")
            pg.get_by_placeholder("품목명 · 품목코드 · 규격").fill("쌀")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2500)
            check(pg.get_by_text(re.compile(r"\d+개 품목 중 \d+개를 보고 있어요")).count() == 1, "수불현황: 품목 검색 '쌀' → 표가 좁혀짐")
            pg.screenshot(path=out / "17_stock_flow_search.png")
            check(not errs, "수불현황: JS 에러 없음")
            pg.context.close()

            pg, errs = open_app(br, url, 1600, 1000, path="/ai-chat-leadtime")
            pg.get_by_placeholder("재고, 발주, 일정에 대해 물어보세요").fill("쌀 리드타임은?")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(3500)
            check(pg.get_by_text(re.compile(r"D\+\d")).count() >= 1, "에이전트: 품목별 리드타임 답변 (쌀 → D+N)")
            pg.context.close()

            # 7) 반응형
            pg, errs = open_app(br, url, 1440, 900, wait="text=달력 대시보드")
            check(pg.get_by_role("heading", name="F&B Agent").count() == 0, "1440px: 에이전트는 서랍 모드")
            check(len({round(x) for _, x, _ in day_grid_buttons(pg)}) == 7, "1440px: 달력 7열 표시")
            check(len({round(y) for _, _, y in day_grid_buttons(pg)}) == 1, "기본은 이번 주 한 줄만 표시")
            check(all(pg.get_by_text(t).count() >= 1 for t in ("입고 품목", "발주 품목", "매장 이슈")), "하단 3칸: 입고 / 발주 / 매장 이슈 패널")
            pg.get_by_role("button", name="달력 확대하기").click()
            pg.wait_for_timeout(2500)
            check(len({round(y) for _, _, y in day_grid_buttons(pg)}) >= 4, "'달력 확대하기'를 누르면 한 달 전체가 보임")
            pg.get_by_role("button", name="F&B Agent").first.click()
            pg.wait_for_timeout(1500)
            pg.get_by_text("지금 발주해야 할 품목은?").first.click()
            pg.wait_for_timeout(3500)
            check(pg.get_by_text("발주가 필요한 품목").count() >= 1, "서랍 안에서 질문 → 답변")
            pg.screenshot(path=out / "10_agent_drawer_1440.png")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(800)
            pg.set_viewport_size({"width": 600, "height": 900})
            pg.wait_for_timeout(3500)
            check(pg.get_by_role("button", name=re.compile(r"^\d+일 \(.\)")).count() >= 1 and len(day_grid_buttons(pg)) == 0,
                  "600px로 좁히면 일정 목록 보기로 전환")
            pg.screenshot(path=out / "11_narrow_600.png")
            pg.set_viewport_size({"width": 1440, "height": 900})
            pg.wait_for_timeout(3500)
            check(len({round(x) for _, x, _ in day_grid_buttons(pg)}) == 7, "다시 넓히면 격자로 복귀")
            check(not errs, "1440px: JS 에러 없음")
            pg.context.close()

            pg, errs = open_app(br, url, 390, 844, wait="h1", user_agent=MOBILE_UA, is_mobile=True, device_scale_factor=2)
            pg.screenshot(path=out / "12_mobile_390.png", full_page=True)
            toggle = pg.locator('[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] button').first
            if toggle.count():
                toggle.click()
                pg.wait_for_timeout(1500)
                pg.screenshot(path=out / "13_mobile_sidebar.png")
                check(pg.get_by_placeholder("메뉴 검색").count() == 1, "휴대폰: 사이드바를 열면 검색창과 메뉴 표시")
            else:
                check(False, "휴대폰: 사이드바 열기 버튼을 찾지 못함")
            pg.context.close()

            # 8) 모든 소메뉴를 URL로 직접 열어 예외 없이 그려지는지
            if not a.skip_all_leaves:
                pg = br.new_context(viewport={"width": 1600, "height": 1000}).new_page()
                bad = []
                for leaf in all_leaves():
                    pg.goto(url if leaf.id == DEFAULT_LEAF else f"{url}/{leaf.id}")      # 기본 화면(홈)의 주소는 '/' 라서 /home-dashboard 는 '페이지 없음' 대화상자가 뜬다
                    login(pg)                                  # 주소로 열 때마다 새 접속이라 로그인 화면부터 나온다
                    try:
                        pg.wait_for_selector(f"h1:has-text('{leaf.title}')", timeout=20000)
                    except Exception:
                        bad.append(f"{leaf.id}: 제목이 나타나지 않음")
                        continue
                    pg.wait_for_timeout(900)
                    if pg.locator('[data-testid="stException"]').count():
                        bad.append(f"{leaf.id}: 예외 표시")
                    elif pg.get_by_text("화면은 준비 중입니다").count():
                        bad.append(f"{leaf.id}: 준비 중 화면")
                check(not bad, f"소메뉴 {len(all_leaves())}개 모두 직접 열림" + ("" if not bad else f" — 실패: {bad}"))
                pg.context.close()
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)

    print(f"\n{'모두 통과' if not failures else f'실패 {len(failures)}건'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
