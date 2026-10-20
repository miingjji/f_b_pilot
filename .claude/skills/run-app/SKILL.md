---
name: run-app
description: F&B Pilot(Streamlit 앱, fb_agent/)을 실제 데이터 모드로 띄워 화면을 열고 스크린샷으로 확인할 때 쓴다. "앱 실행", "화면 확인", "스크린샷", "실행해서 보여줘" 요청에 사용.
---

# F&B Pilot 실행·화면 확인

앱은 `fb_agent/`의 Streamlit 앱이다. 작업 폴더는 `~/workspaces/f_b_pilot` (Windows 쪽 `/mnt/c/.../f_b_pilot`은 빈 폴더).
화면은 URL 주소로 바로 열린다 (`/sales-daily` 등). 주소 목록은 `fb_agent/menu.py` 각 항목의 첫 값.

## 사람이 직접 볼 때
```bash
cd ~/workspaces/f_b_pilot/fb_agent && source ../.venv/bin/activate
bash run_real.sh          # FB_MASTER=real. data/real 이 없으면 먼저 만든다. 브라우저: http://localhost:8501
```
`FB_MASTER` 를 빼면 샘플 데이터 모드다 (매출 화면이 가상 값).

## 에이전트가 화면을 확인할 때 (헤드리스 Chromium)
1. **처음 한 번** — Chromium 시스템 라이브러리(libnspr4)와 한글 폰트가 없으면 `libnspr4.so: cannot open shared object file` 로 실행이 안 된다. root 없이 프로젝트 안에만 푼다:
   ```bash
   cd ~/workspaces/f_b_pilot/fb_agent && bash e2e/setup_sandbox_libs.sh    # .e2e-env/ 생성 (apt-get download + dpkg -x, 시스템 설치 아님)
   ```
2. 매번:
   ```bash
   cd ~/workspaces/f_b_pilot/fb_agent && source .e2e-env/env.sh && source ../.venv/bin/activate
   python ../.claude/skills/run-app/scripts/shot.py <출력폴더> sales-daily sales-hourly pay-card
   ```
   화면마다 `주소 | 제목 | 예외: 0` 과 `JS 에러: []` 를 출력하고 `<출력폴더>/<주소>.png` 를 저장한다. **PNG를 Read로 열어 눈으로 확인한다** (빈 화면·깨진 문구·취소선 등).
3. 전체 점검은 프로젝트 e2e: `python e2e/check_real.py` (실제 모드), `python e2e/check_ui.py` — 자세한 항목은 `fb_agent/e2e/README.md`.

## 발주 추천 화면 (이력 기반)
- 주소 `/po-engine` (구매/발주 > 발주관리 > 발주 추천 (이력 기반)). 수원점(실제 청구·입고 이력이 있는 매장)만 제공하고, 다른 매장은 안내 문구가 나온다.
- 화면 확인: `python ../.claude/skills/run-app/scripts/shot.py <출력폴더> po-engine`. 기준일 기본값은 앱의 '오늘'이라, 자료(9/30)보다 3일 넘게 뒤면 경고가 뜬다.
- 자료를 갱신한 뒤: `python -m prep.data_2026 --year 2026` → `python reorder_engine.py --fit 2025-07-01 <자료 마지막 날>` (모델 재학습) → `python reorder_engine.py --eval` (검증 수치 갱신, 약 8분).

## 주의
- 테스트는 `pytest`가 아니라 unittest: `FB_MASTER=real python -m unittest test_real_sales test_real_mode`, 전체는 `python -m unittest discover -p "test_*.py"` (약 75초, 284개).
- 안내 문구(`views/common.py` `sales_notice`)는 마크다운이라 `~`를 `\~`로 써야 한다 (한 쌍이면 취소선이 된다).
- 2026-01~09 매출은 일자별 합계·월별 정산만 실제이고 메뉴·영수증은 추정값이다. 데이터 정제: `python -m prep.data_2026`, `python -m prep.settlement_2026`.
- 포트가 겹치면 `PORT=8812 python .../shot.py ...`.
