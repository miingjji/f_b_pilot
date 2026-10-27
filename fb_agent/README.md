# F&B Pilot

F&B 매장 운영 도우미. 실사 재고로 발주 시점·수량을 추천하고, 매장 일정을 달력으로 보여주며, 우측의 F&B Agent에게 질문할 수 있습니다.

## 화면

| 영역 | 내용 |
|---|---|
| 좌측 | 아이콘 레일(홈·즐겨찾기·매출·구매/발주·인력/스케줄·설정/계정) + 서브 패널(메뉴 검색, 대/중/소 아코디언) |
| 헤더 | 제목·즐겨찾기·브레드크럼, 매장 선택, F&B Agent, 로그인/회원가입 |
| 중앙 | 요약 카드 + 월/일 달력 대시보드, 또는 선택한 소메뉴 화면 (매출분석, 발주·재고, 인력·스케줄 등 56개) |
| 우측 | F&B Agent 챗봇. 창이 넓으면 고정 패널, 좁으면 버튼으로 여는 서랍 |

레이아웃과 반응형 규칙은 [docs/LAYOUT.md](docs/LAYOUT.md), 화면 스크린샷은 저장소에 두지 않고 `python e2e/check_ui.py`로 `docs/screenshots/`에 새로 만든다.

## 실행

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

`data/real/`(실제 매장 데이터 기반 마스터, 품목 855개(2026-09 실사 기준)·거래처 45곳)이 저장소에 들어 있어서 **`streamlit run app.py`만 실행해도 실제 데이터 기반으로 뜹니다.**
앱이 보여 주는 값은 모두 실제 데이터이고, 근거가 없는 값은 `데이터 없음`으로 표시합니다 (가상 값을 만들지 않습니다).
`./run_real.sh`는 `data/real/`이 없으면 `python -m prep.app_master`로 만든 뒤 실행합니다.
 일소비량·발주 요일·리드타임·재고는 실제 근거가 있는 값만 채우고, 없으면 비워 앱에 `데이터 없음`으로 보입니다.
매출 화면은 수원점 실제 POS 데이터(2024-01~2026-09)만 씁니다 (`sales_data.py`, 집계는 `python -m prep.sales_aggregates`). 데이터가 끝난 뒤의 기준일은 마지막 영업일입니다. 출처는 `data/real/items.csv`의 `*_출처` 열에 있습니다 ([docs/DATA_CLEANING.md](docs/DATA_CLEANING.md)).

CLI로 한 품목만 계산: `python main.py 짜사이 "1pk 300g"`

## 품목 마스터

품목은 `data/items.csv`, 거래처는 `data/suppliers.csv`에서 읽습니다 (설정/계정 › 품목 마스터 화면에서 조회·다운로드).
필드와 편집 방법은 [docs/DATA.md](docs/DATA.md) 참고. 현재 28개 품목: 기존 식자재 4개 + 매장 소모품·위생용품 24개.

## 실사 재고 파일 업로드
엑셀(xlsx/xls/ods) · CSV/TSV · JSON · 마크다운 표 · 줄 단위 메모(`짜사이 1pk 300g`)를 읽습니다.
확장자가 아니라 내용으로 형식을 판별하고, 행별 오류를 보고합니다 (`importer.py`).
PDF·이미지는 지원하지 않습니다.

## 구조

```
app.py               진입점: 숨긴 st.navigation(소메뉴 56개) · 사이드바 · 헤더 · 본문/에이전트 배치
menu.py              메뉴 트리(레일→대→중→소), 검색(초성 포함), 브레드크럼 (Streamlit 비의존)
nav_ui.py            레일 + 서브 패널 + 아코디언, st.Page 등록
routing.py           소메뉴 id → 페이지 이동
views/               소메뉴별 화면: home · sales · purchase · hr · ai · settings
sales_data.py        실제 매출 조회 (일자·시간대·메뉴·결제·취소·영수증, 없으면 빈 표)
master.py            품목·거래처 마스터 CSV 로더/검증/내보내기
data/real/           items.csv(품목 마스터) · suppliers.csv(거래처) — prep.app_master 가 생성, 엑셀로 편집 가능
testdata/master/    테스트 전용 소형 마스터 (앱에서는 쓰지 않음)
calendar_data.py     일정 모델, 일정 합성, 달력 셀 크기 계산
insights.py          재고 요약 + 이상징후 판정
reorder.py           발주 추천 로직
converter.py         BOX/PK/EA/g 단위 환산 · 입력 파싱
importer.py          재고 파일 파서
agent.py             F&B Agent 응답 (규칙 기반)  ·  agent_context.py 현재 매장 컨텍스트
agent_panel.py       채팅 UI (고정 패널 / 서랍 / Q&A 화면 공용)
viewport.py          브라우저 폭 측정 컴포넌트
auth_ui.py           헤더 · 로그인 UI
state.py             세션 상태 (매장별 재고 포함)
```

## 테스트

```bash
python -m unittest        # 단위 테스트: 메뉴 구조, 매출 조회, 소메뉴 렌더링 등 (AppTest 포함)
python e2e/check_ui.py    # 실제 브라우저 점검 (e2e/README.md 참고)
```

## 알아둘 점
- **F&B Agent는 LLM이 아닙니다.** 앱 데이터에 키워드로 답하는 규칙 기반이며, LLM을 붙일 때는 `agent.answer()`만 교체하면 됩니다.
- **로그인은 데모입니다.** 이름·이메일만 받고 비밀번호는 받지 않습니다. `.streamlit/secrets.toml`에 `[auth]`(OIDC)를 설정하면 `st.login()`으로 자동 전환됩니다.
- **일정은 세션에만 저장됩니다.** 새로고침하면 비어 있는 일정으로 돌아갑니다 (일정을 만들어 넣지 않습니다).
- **매출·근태 화면:** 매출은 실제 POS 값입니다. 근태·인건비는 원본 데이터가 없어 `데이터 없음` 안내만 보여 줍니다. 회전율(좌석 수)·결제채널 수수료·취소 사유는 원본에 없어 제공하지 않습니다.
- 이동 중 위젯 상태 문제 등 설계 배경은 `docs/LAYOUT.md`에 정리했습니다.
