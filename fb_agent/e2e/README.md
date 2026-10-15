# e2e 화면 점검

실제 브라우저(Playwright + Chromium)로 화면을 열어 동작을 검증하고 스크린샷을 `docs/screenshots/`에 저장합니다.

## 설치

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
```

시스템 라이브러리(libnss3 등)나 한글 폰트가 없는 환경(WSL 최소 설치, 컨테이너 등)에서 root 권한이 없다면:

```bash
bash e2e/setup_sandbox_libs.sh
source .e2e-env/env.sh
```

## 실행

```bash
python e2e/check_ui.py            # 서버를 직접 띄우고 점검 후 종료
python e2e/check_ui.py --out /tmp/shots --port 8800
```

## 점검 항목

| 항목 | 내용 |
|---|---|
| 1920px | 에이전트가 우측에 고정, 달력 정상 |
| 1440px | 서랍 모드(고정 안 됨), 달력 7열 표시, 주마다 행 높이가 다름 |
| 서랍 | 버튼으로 열림, 서랍 안에서 질문 → 답변 |
| 창 크기 변경 | 600px로 좁히면 일정 목록, 다시 넓히면 격자 (창 폭 측정이 실제로 동작하는지 확인) |
| 일정 추가 | 다이얼로그 제출 후 달력 반영 |
| 휴대폰 UA | 정상 렌더링 |
| 재고 페이지 | "우선 처리" 섹션 표시 |
| 전체 | JS 에러 없음 |

## 참고

- `streamlit.testing.v1.AppTest`는 `st.dialog` 안의 폼 제출과 커스텀 컴포넌트(JS)를 지원하지 않습니다.
  그래서 이 두 가지는 단위 테스트가 아니라 이 e2e로만 검증됩니다.
