"""실제 브라우저(Playwright)로 화면을 점검하고 스크린샷을 저장하는 e2e 스크립트.

    python e2e/check_ui.py [--out docs/screenshots] [--port 8799]

서버를 직접 띄웠다 종료한다. 설치/환경은 e2e/README.md 참고.
"""
import argparse
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
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


def open_app(browser, url, width, height, **ctx):
    page = browser.new_context(viewport={"width": width, "height": height}, **ctx).new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(url)
    page.wait_for_selector("text=대시보드", timeout=30000)
    page.wait_for_timeout(3500)   # 폭 측정 후 재실행까지 대기
    return page, errs


def day_buttons_y(page):
    """달력 격자의 일요일 열 날짜 버튼 y좌표 -> 주(행) 시작 위치."""
    boxes = []
    for n in range(1, 32):
        loc = page.get_by_role("button", name=str(n), exact=True)
        if loc.count():
            bb = loc.first.bounding_box()
            if bb:
                boxes.append((n, bb["x"], bb["y"]))
    return boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--port", type=int, default=8799)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    url = f"http://localhost:{a.port}"

    srv = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                            "--server.port", str(a.port), "--browser.gatherUsageStats", "false"],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_server(a.port)
        with sync_playwright() as p:
            br = p.chromium.launch()

            # 1) 넓은 화면(1920): 에이전트가 우측에 고정
            pg, errs = open_app(br, url, 1920, 1080)
            check(pg.get_by_role("heading", name="F&B Agent").count() == 1, "1920px: 에이전트 패널이 우측에 고정됨")
            pg.screenshot(path=out / "01_dashboard_dock_1920.png")
            check(not errs, "1920px: JS 에러 없음")
            pg.context.close()

            # 2) 1440px: 서랍 모드 → 달력이 넓고, 버튼으로 서랍 열림, 서랍 안에서 대화
            pg, errs = open_app(br, url, 1440, 900)
            check(pg.get_by_role("heading", name="F&B Agent").count() == 0, "1440px: 에이전트가 고정되지 않음(서랍 모드)")
            boxes = day_buttons_y(pg)
            cols = sorted({round(x) for _, x, _ in boxes})
            check(len(cols) == 7, f"1440px: 달력 7열이 모두 보임 (x 위치 {len(cols)}종)")
            rows = sorted({round(y) for _, _, y in boxes})
            gaps = [b - a for a, b in zip(rows, rows[1:])]
            check(len(set(gaps)) > 1, f"주마다 행 높이가 다름 (간격 {gaps})")
            pg.screenshot(path=out / "02_dashboard_drawer_mode_1440.png")
            pg.get_by_role("button", name="F&B Agent").first.click()
            pg.wait_for_timeout(1500)
            pg.get_by_text("지금 발주해야 할 품목은?").first.click()
            pg.wait_for_timeout(3500)
            check(pg.get_by_text("발주가 필요한 품목").count() >= 1, "서랍 안에서 추천 질문 → 답변 표시")
            pg.screenshot(path=out / "03_agent_drawer_1440.png")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(800)

            # 3) 창을 좁히면(데스크톱 UA) 목록 보기로 전환
            pg.set_viewport_size({"width": 600, "height": 900})
            pg.wait_for_timeout(3500)
            check(pg.get_by_role("button", name=re.compile(r"^\d+일 \(.\)")).count() >= 1
                  and len(day_buttons_y(pg)) == 0, "600px로 좁히면 일정 목록 보기로 전환 (격자 버튼 없음)")
            pg.screenshot(path=out / "04_narrow_window_600.png")
            pg.set_viewport_size({"width": 1440, "height": 900})
            pg.wait_for_timeout(3500)
            check(len({round(x) for _, x, _ in day_buttons_y(pg)}) == 7, "다시 넓히면 격자로 복귀")

            # 4) 일정 추가 다이얼로그
            pg.get_by_role("button", name="일정 추가").first.click()
            pg.wait_for_timeout(1000)
            pg.get_by_label("제목").fill("e2e 테스트 일정")
            pg.get_by_role("button", name="추가", exact=True).click()
            pg.wait_for_timeout(2500)
            check(pg.get_by_text("e2e 테스트 일정").count() >= 1, "일정 추가가 달력/상세에 반영됨")
            check(not errs, "1440px: JS 에러 없음")
            pg.context.close()

            # 5) 휴대폰
            pg, errs = open_app(br, url, 390, 844, user_agent=MOBILE_UA, is_mobile=True, device_scale_factor=2)
            pg.screenshot(path=out / "05_mobile_390.png", full_page=True)
            check(pg.get_by_role("button", name="일정 추가").count() == 1, "휴대폰: 화면이 정상 렌더링됨")
            pg.context.close()

            # 6) 다른 페이지
            pg, errs = open_app(br, url, 1440, 900)
            for name, f in [("매출/재고 관리", "06_inventory"), ("매장 모니터링", "07_monitoring"), ("설정", "08_settings")]:
                pg.get_by_role("link", name=name).click()
                pg.wait_for_timeout(2500)
                pg.screenshot(path=out / f"{f}.png", full_page=True)
            pg.get_by_role("link", name="매출/재고 관리").click()
            pg.wait_for_timeout(2000)
            pg.get_by_role("tab", name="전체 요약").click()
            pg.wait_for_timeout(2000)
            check(pg.get_by_text("우선 처리").count() >= 1, "재고: 우선 처리 섹션 표시")
            pg.screenshot(path=out / "09_inventory_all.png", full_page=True)
            check(not errs, "페이지 이동 중 JS 에러 없음")
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)

    print(f"\n{'모두 통과' if not failures else f'실패 {len(failures)}건'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
