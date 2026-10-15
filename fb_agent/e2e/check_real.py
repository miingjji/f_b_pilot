"""실제 데이터 기반 마스터(FB_MASTER=real)로 앱을 띄워 화면을 점검하고 스크린샷을 저장한다.

    python e2e/check_real.py [--out docs/screenshots] [--port 8798]

사전 조건: data/real/items.csv (python -m prep.app_master). 환경은 e2e/README.md 참고.
"""
import argparse
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SB = '[data-testid="stSidebar"]'
failures = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def wait_server(port, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2).read() == b"ok":
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("서버가 시작되지 않았습니다.")


def open_page(br, url, path="", width=1600, height=1000):
    pg = br.new_context(viewport={"width": width, "height": height}).new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url + path)
    pg.wait_for_selector("h1", timeout=40000)
    pg.wait_for_timeout(3500)
    return pg, errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--port", type=int, default=8798)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    url = f"http://localhost:{a.port}"
    srv = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.port", str(a.port),
                            "--browser.gatherUsageStats", "false"], cwd=ROOT, env={**os.environ, "FB_MASTER": "real"},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_server(a.port)
        with sync_playwright() as p:
            br = p.chromium.launch()

            pg, errs = open_page(br, url)
            check(pg.get_by_text("실제 데이터 기반 · 품목 903개").count() >= 1, "사이드바에 데이터 종류 표시 (실제 데이터 기반 · 품목 903개)")
            check(pg.locator('[data-testid="stSelectbox"] input').first.input_value() == "수원점", "매장 선택이 수원점(실제 재고의 매장)")
            pg.screenshot(path=out / "real_01_home.png")
            check(not errs, "홈: JS 에러 없음")
            pg.context.close()

            pg, errs = open_page(br, url, "/po-auto")
            check(pg.get_by_text("나머지").count() >= 1, "자동 발주 추천: 카드 8개 초과분은 안내로 표시")
            check(pg.get_by_role("button", name=re.compile(r"전체 구매청구 만들기")).count() == 1, "일괄 구매청구 버튼")
            pg.get_by_role("button", name=re.compile(r"전체 구매청구 만들기")).click()
            pg.wait_for_timeout(2500)
            pg.screenshot(path=out / "real_02_po_auto.png", full_page=False)
            pg.goto(url + "/po-request-detail")
            pg.wait_for_selector("h1", timeout=40000)
            pg.wait_for_timeout(2500)
            pg.context.close()

            pg, errs = open_page(br, url, "/stock-input")
            check(pg.get_by_text("903개 표시 / 전체 903개").count() == 1, "재고 입력: 903개 표시")
            pg.locator('[data-testid="stButtonGroup"]').get_by_text("저장품", exact=True).click()
            pg.wait_for_timeout(2500)
            check(pg.get_by_text(re.compile(r"개 표시 / 전체 903개")).count() == 1 and pg.get_by_text("903개 표시").count() == 0, "분류 '저장품' 필터가 적용됨")
            pg.screenshot(path=out / "real_03_stock_input.png")
            pg.context.close()

            pg, errs = open_page(br, url, "/set-items")
            check(pg.get_by_text("903개 / 전체 903개").count() == 1, "품목 마스터: 903개")
            check(pg.get_by_text("가상 값").count() >= 1, "품목 마스터: 가상 값 안내")
            pg.screenshot(path=out / "real_04_item_master.png")
            pg.context.close()

            pg, errs = open_page(br, url, "/ai-chat-order")
            pg.get_by_text("지금 발주해야 할 품목은?").first.click()
            pg.wait_for_timeout(4000)
            check(pg.get_by_text("가장 급한 8개만 보여드려요").count() == 1, "에이전트: 긴급 품목이 많아도 8개만 나열하고 총 개수 안내")
            pg.screenshot(path=out / "real_05_agent.png")
            pg.context.close()

            pg, errs = open_page(br, url, "/po-leadtime")
            pg.screenshot(path=out / "real_06_leadtime.png", full_page=False)
            check(not errs, "리드타임 화면: JS 에러 없음")
            pg.context.close()

            pg, errs = open_page(br, url, "/sales-monthly")
            check(pg.get_by_text("실제 매출입니다").count() == 1, "매출요약: 실제 매출 안내")
            check(pg.get_by_text("12개월 합계").count() == 1, "매출요약: 오늘 기준 12개월 합계 표시 (2026년 가상 데이터로 채워짐)")
            pg.screenshot(path=out / "real_07_sales_monthly.png")
            check(not errs, "매출요약: JS 에러 없음")
            pg.context.close()

            pg, errs = open_page(br, url, "/menu-status")
            check(pg.get_by_text("샤오롱바오샘플러").count() >= 1, "메뉴 판매현황: 실제 메뉴명 표시")
            check(pg.get_by_text("짜장면").count() == 0, "메뉴 판매현황: 샘플 메뉴(짜장면) 없음")
            pg.screenshot(path=out / "real_08_menu_status.png")
            pg.context.close()

            pg, errs = open_page(br, url, "/settle-receipts")
            check(pg.get_by_text("영수증").count() >= 1 and not errs, "영수증 목록 화면 표시")
            pg.screenshot(path=out / "real_09_receipts.png")
            pg.context.close()
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
    print(f"\n{'모두 통과' if not failures else f'실패 {len(failures)}건'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
