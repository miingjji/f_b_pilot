"""앱을 FB_MASTER=real 로 띄우고 화면 주소(path)마다 스크린샷·제목·예외 수를 출력한다.

    source fb_agent/.e2e-env/env.sh && source .venv/bin/activate
    python .claude/skills/run-app/scripts/shot.py <출력폴더> sales-daily sales-hourly pay-card ...
주소는 fb_agent/menu.py 의 첫 번째 값(예: sales-daily). 서버는 끝나면 종료한다.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4] / "fb_agent"
out, paths, port = Path(sys.argv[1]), sys.argv[2:], int(os.environ.get("PORT", 8811))
out.mkdir(parents=True, exist_ok=True)
srv = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.port", str(port),
                        "--browser.gatherUsageStats", "false"], cwd=ROOT, env={**os.environ, "FB_MASTER": os.environ.get("FB_MASTER", "real")},
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(120):
        try:
            if urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2).read() == b"ok":
                break
        except Exception:
            time.sleep(0.5)
    with sync_playwright() as p:
        pg = p.chromium.launch().new_context(viewport={"width": 1600, "height": 1100}).new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for path in paths:
            pg.goto(f"http://localhost:{port}/{path}")
            pg.wait_for_selector("h1", timeout=40000)
            pg.wait_for_timeout(5000)
            pg.screenshot(path=str(out / f"{path}.png"), full_page=True)
            print(path, "|", pg.locator("h1").first.inner_text(), "| 예외:", pg.locator('[data-testid="stException"]').count())
        print("JS 에러:", errs)
finally:
    srv.terminate()
