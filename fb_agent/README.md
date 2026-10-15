# F&B Pilot

F&B 매장 운영 도우미. 실사 재고로 발주 시점·수량을 추천하고, 매장 일정을 달력으로 보여주며, 우측의 F&B Agent에게 질문할 수 있습니다.

## 화면

| 영역 | 내용 |
|---|---|
| 좌측 사이드바 | 대시보드 · 매출/재고 관리 · 매장 모니터링 · 설정 |
| 중앙 | 월/일 달력 (직접 추가한 일정 + 재고 기반 발주·입고 + 매장 휴무) |
| 우측 | F&B Agent 챗봇. 창이 넓으면 고정 패널, 좁으면 버튼으로 여는 서랍 |
| 우측 상단 | 로그인 / 회원가입 / 프로필 |

스크린샷은 `docs/screenshots/` 참고.

### 반응형 동작
- 브라우저 폭을 작은 컴포넌트(`viewport.py`)가 측정해 Python에 알려줍니다.
- **에이전트 패널**: 창 폭 1760px 이상이면 우측 고정, 미만이면 서랍. 설정 페이지에서 고정/서랍을 강제할 수 있습니다.
- **달력 셀**: 폭에 맞춰 줄바꿈을 추정하고 주(행)마다 필요한 높이만 씁니다.
- **좁은 창/휴대폰(700px 미만)**: 7열 격자 대신 일정이 있는 날만 보여주는 목록.

## 실행

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

CLI로 한 품목만 계산: `python main.py 짜사이 "1pk 300g"`

## 실사 재고 파일 업로드
엑셀(xlsx/xls/ods) · CSV/TSV · JSON · 마크다운 표 · 줄 단위 메모(`짜사이 1pk 300g`)를 읽습니다.
확장자가 아니라 내용으로 형식을 판별하고, 행별 오류를 보고합니다 (`importer.py`).
PDF·이미지는 지원하지 않습니다.

## 구조

```
app.py               진입점: 사이드바 내비게이션 · 헤더 · 중앙/우측 배치
app_pages/           대시보드 · 재고 · 모니터링(스켈레톤) · 설정
calendar_data.py     일정 모델, 일정 합성, 달력 셀 크기 계산 (Streamlit 비의존)
reorder.py           발주 추천 로직
converter.py         BOX/PK/EA/g 단위 환산 · 입력 파싱
importer.py          재고 파일 파서
agent.py             F&B Agent 응답 (규칙 기반)
agent_panel.py       채팅 UI (고정 패널 / 서랍 공용)
viewport.py          브라우저 폭 측정 컴포넌트
auth_ui.py           헤더 · 로그인 UI
state.py             세션 공통 상태
```

## 테스트

```bash
python -m unittest        # 단위 테스트 (Streamlit 비의존 로직 + AppTest)
python e2e/check_ui.py    # 실제 브라우저 점검 (e2e/README.md 참고)
```

## 알아둘 점
- **F&B Agent는 LLM이 아닙니다.** 앱 데이터에 키워드로 답하는 규칙 기반이며, LLM을 붙일 때는 `agent.answer()`만 교체하면 됩니다.
- **로그인은 데모입니다.** 이름·이메일만 받고 비밀번호는 받지 않습니다. `.streamlit/secrets.toml`에 `[auth]`(OIDC)를 설정하면 `st.login()`으로 자동 전환됩니다.
- **일정은 세션에만 저장됩니다.** 새로고침하면 샘플 일정으로 돌아갑니다.
- 매장 모니터링 페이지는 스켈레톤입니다.
