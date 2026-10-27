---
name: F&B Pilot 네이비
description: 미스트색 바탕에 차콜 글자와 네이비 포인트, 가장 진한 네이비 사이드바, 그림자 대신 가는 선으로 그린 현장 입력용 장부.
colors:
  navy-deep: "#0B1F3A"
  navy: "#1F3B5C"
  slate: "#A7B1BE"
  mist: "#E6E9EF"
  charcoal: "#2B2F36"
  card-surface: "#F5F6F9"
  navy-tint: "#CED4DD"
  table-header: "#CED4DC"
  ink-muted: "#566071"
  rule: "#C3CAD4"
  sidebar-shade: "#1E3A60"
  input-surface: "#D6DBE3"
  alert-red: "#B3261E"
  alert-orange: "#8F4F00"
typography:
  display:
    fontFamily: "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
    fontSize: "1.9rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
    fontSize: "1.45rem"
    fontWeight: 650
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
    fontSize: "1.15rem"
    fontWeight: 650
    letterSpacing: "-0.015em"
  metric:
    fontFamily: "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
    fontSize: "15px"
    fontWeight: 400
  label:
    fontFamily: "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
    fontSize: "0.87rem"
    fontWeight: 600
rounded:
  sm: "6px"
  md: "8px"
spacing:
  xs: "0.25rem"
  sm: "0.45rem"
  md: "1.25rem"
  lg: "3rem"
components:
  button-primary:
    backgroundColor: "{colors.navy}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sm}"
    typography: "{typography.label}"
  button-secondary:
    backgroundColor: "{colors.card-surface}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.sm}"
  card:
    backgroundColor: "{colors.card-surface}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.md}"
    padding: "0.85rem 1.1rem"
  filter-bar:
    backgroundColor: "{colors.card-surface}"
    rounded: "{rounded.md}"
    padding: "1rem 1.25rem"
  tab-selected:
    backgroundColor: "{colors.navy-tint}"
    textColor: "{colors.navy}"
    rounded: "{rounded.sm}"
    padding: "0.55rem 1rem"
  sidebar:
    backgroundColor: "{colors.navy-deep}"
    textColor: "{colors.mist}"
  sidebar-menu-selected:
    backgroundColor: "{colors.mist}"
    textColor: "{colors.navy-deep}"
    rounded: "{rounded.sm}"
  badge-problem:
    textColor: "{colors.alert-orange}"
  badge-error:
    textColor: "{colors.alert-red}"
---

# Design System: F&B Pilot 네이비

## Overview

**Creative North Star: "장부 (The Ledger)"**

미스트색 바탕 위에 차콜 글자로 칸을 채워 가는 장부다. 모든 면은 그림자가 아니라 가는 선(1px)으로 구분하고, 색은 아껴서 의미가 있는 곳에만 쓴다. 모드는 Operate: 창고·주방에서 서서 수십 개 품목을 반복 입력하는 현장 도구이므로 화려함보다 읽기 쉬움, 틀리지 않음, 덜 지침이 우선이다.

팔레트는 사용자가 정한 5색(#0B1F3A, #1F3B5C, #A7B1BE, #E6E9EF, #2B2F36)을 섞어 만든다. 미스트와 차콜이 기본이고, 네이비 포인트는 사람이 누르거나 고른 것(행동·선택)에만 쓴다. 가장 진한 네이비는 제목과 사이드바 바탕이다. 5색에 없는 빨강·주황은 '문제가 있는 곳'에만 쓰며, 정상 상태에는 색을 입히지 않는다. 한글은 앱에 포함된 Pretendard Variable로 통일한다.

**Key Characteristics:**
- 미스트 바탕(#E6E9EF)과 한 단계 밝은 카드 면(#F5F6F9)의 톤 차이로 층을 만든다.
- 그림자 없음. 1px 선(#C3CAD4)과 6~8px 모서리.
- 네이비 포인트 = 행동·선택, 빨강·주황 = 문제, 정상 = 무채색.
- 사이드바는 가장 진한 네이비 바탕에 밝은 글자, 선택된 메뉴만 밝은 칸으로 뒤집힌다.
- 숫자는 자리 폭이 같은(tabular) 형태, 한글은 단어 단위 줄바꿈.
- 숫자 입력은 표(BOX · PK · 낱개)가 중심이고, 상태는 표 위 한 줄에 모은다.

## Colors

사용자 지정 5색(네이비 계열 넷과 차콜)을 섞은 차가운 무채 팔레트에 경고색 둘뿐인 절제된 구성.

### Primary
- **포인트 네이비** (navy, #1F3B5C): 주 버튼, 선택된 탭 글자·밑줄, 링크, 진행률 줄. 행동과 선택에만 쓴다. 흰 글자와 11.42:1.
- **네이비 연한 면** (navy-tint, #CED4DD): 선택된 탭 배경. 네이비 글자와 7.66:1.
- **가장 진한 네이비** (navy-deep, #0B1F3A): 제목(h1~h3), 지표 숫자, 표 머리 글자, 사이드바 바탕, 로고 글자 'F'. 행동 색이 아니라 구조 색이다.

### Secondary
- **경고 빨강** (alert-red, #B3261E): '긴급', '입력 오류' 같이 지금 고쳐야 하는 문제. 카드 면 위 6.05:1.
- **주의 주황** (alert-orange, #8F4F00): '발주 필요', '확인 필요' 같이 확인해야 하는 문제. 카드 면 위 5.91:1.

### Neutral
- **미스트** (mist, #E6E9EF): 앱 바탕. 사이드바 안에서는 글자색과 선택된 메뉴 칸. 로고 타일.
- **차콜** (charcoal, #2B2F36): 본문. 미스트 위 11.05:1.
- **카드 면** (card-surface, #F5F6F9): 지표 칸·필터 바·폼·펼침 상자·보조 버튼의 면.
- **입력 바탕** (input-surface, #D6DBE3): 입력 위젯 등 보조 바탕(테마 secondaryBackgroundColor).
- **표 머리** (table-header, #CED4DC): 표 머리 배경, 글자는 가장 진한 네이비.
- **보조 글자** (ink-muted, #566071): 캡션·지표 라벨·지표 아이콘. 미스트 위 5.22:1, 카드 면 위 5.88:1.
- **괘선** (rule, #C3CAD4): 모든 테두리와 표 선.
- **슬레이트** (slate, #A7B1BE): 사이드바 보조 글자·캡션·hover 테두리. 가장 진한 네이비 위 7.61:1.
- **사이드바 짙은 면** (sidebar-shade, #1E3A60): 사이드바 hover·보조 버튼 면.

사이드바 대비: 미스트/가장 진한 네이비 13.58:1, 슬레이트/가장 진한 네이비 7.61:1. 차트용 범주 색(config.toml chartCategoricalColors)과 네이비 단계 10색(chartSequentialColors)은 테마에 정의돼 있고 차트 전용이다.

### Named Rules
**The Quiet Normal Rule.** 정상 상태는 색을 입히지 않는다. 개수가 0인 상태 배지는 회색, 개수가 있을 때만 색을 띤다.

**The Navy Means Press Rule.** 포인트 네이비는 누르거나 고른 것(행동·선택)에만 쓴다. 상태 표시에 쓰지 않는다. 가장 진한 네이비는 제목·사이드바 같은 구조에만 쓴다.

## Typography

**Display / Body / Label Font:** Pretendard Variable (앱에 포함, static/fonts/PretendardVariable.woff2, weight 45~920), 대체 Apple SD Gothic Neo, Noto Sans KR, sans-serif
**Mono:** D2Coding (대체 Noto Sans Mono)

**Character:** 한 가족(Pretendard)의 굵기와 크기만으로 위계를 만든다. 기본 글자 15px로 현장 태블릿에서 읽히게 하고, 제목은 자간을 좁혀(-0.015 ~ -0.025em) 단단하게 한다.

### Hierarchy
- **Display** (700, 1.9rem, 1.2): 화면 제목(h1).
- **Headline** (650, 1.45rem): 구역 제목(h2).
- **Title** (650, 1.15rem): 소제목(h3).
- **Metric** (700, 1.75rem, -0.02em): 지표 칸의 큰 숫자.
- **Body** (400, 15px): 본문, 표 셀.
- **Label** (600, 0.87rem): 지표 라벨, 탭(600), 주 버튼(600).

### Named Rules
**The Tabular Rule.** 숫자는 항상 자리 폭이 같게(font-variant-numeric: tabular-nums) 해서 표의 열이 흔들리지 않게 한다. 한글은 word-break: keep-all.

## Layout

본문 컨테이너는 최대 1680px, 안쪽 여백 위아래 4rem·좌우 3rem. 최상위 블록 사이 간격은 1.25rem, 사이드바 안은 0.45rem(가로 0.4rem)로 촘촘하게. 지표 칸은 flex로 같은 폭, 같은 높이로 늘어난다. 재고 입력 화면의 위에서 아래 순서는 입력 방법 펼침 상자, 분류 pills · 검색 · 파일 불러오기(비율 5:4:2), 보기 선택 · 활동 없는 품목 스위치(5:4), 진행·상태·저장 줄(4:6:2), 입력 표, 캡션이다. 표의 '품목' 열은 150px로 고정(pinned)되어 가로로 밀려도 남는다.

## Elevation & Depth

그림자를 쓰지 않는다. 깊이는 미스트(#E6E9EF) 위에 한 단계 밝은 카드 면(#F5F6F9)을 1px 괘선으로 두르는 톤 차이로만 만든다. 사이드바는 가장 진한 네이비 면 자체가 경계이므로 선도 그림자도 없다(border-right 0).

### Named Rules
**The Flat Ledger Rule.** box-shadow는 none. 면을 나누려면 1px #C3CAD4 선이나 톤 차이를 쓴다.

## Shapes

모서리는 두 단계다. 버튼·탭 위쪽·입력 위젯은 6px, 카드·필터 바·폼·펼침 상자·표는 8px. 모두 1px 괘선 테두리. 로고 타일(32px 정사각)은 7px이며 미스트 타일 위에 네이비 'F'. 사이드바의 메뉴 묶음 펼침은 테두리 없이 투명하게 두어 상자 안에 상자가 겹치지 않게 한다.

## Components

### Buttons
- **Shape:** 6px 모서리, 그림자 없음.
- **Primary:** 포인트 네이비 바탕, 흰 글자, 굵기 600, 자간 -0.005em. 한 구역에 하나('이력에 저장').
- **Secondary:** 카드 면(#F5F6F9) 바탕 + 1px 괘선.
- **Tertiary (사이드바 메뉴):** 글자 미스트, hover 시 #1E3A60 면 + 흰 글자.

### Cards / Containers
- **지표 칸:** 카드 면, 1px 괘선, 8px, 안쪽 0.85rem 1.1rem. 라벨은 작은 보조 글자, 숫자는 가장 진한 네이비로 크게, 아이콘은 오른쪽 위에 한 가지 회색 선 아이콘.
- **필터 바·폼·펼침 상자:** 같은 면·선·모서리. 필터 바 안쪽 1rem 1.25rem.

### Inputs / Fields
- 테마의 6px 모서리, 괘선 테두리. 검색 칸은 돋보기 아이콘과 설명형 placeholder. 분류는 pills, 보기는 segmented control.

### Navigation
- **탭:** 굵기 600, 안쪽 0.55rem 1rem, 위쪽만 6px 모서리. 선택되면 네이비 글자 + 연한 네이비 면(#CED4DD) + 3px 네이비 밑줄.
- **사이드바:** 가장 진한 네이비(#0B1F3A) 바탕, 글자 미스트, 보조 글자 슬레이트. 선택된 메뉴는 미스트 칸에 가장 진한 네이비 글자(굵기 700).

### 재고 입력 표 (Signature)
표는 장부의 칸이다. 열은 품목(고정) · BOX · PK · 낱개(입력 가능, 좁은 숫자 칸, 0 이상) · 합계 · 확인 · 환산 기준(읽기 전용). 표 머리는 #CED4DC 바탕에 가장 진한 네이비 글자. '확인' 열은 문구로 상태를 말한다: '추정값'(손대지 않음), '입력함', '확인 필요 · 사유'(0 입력, 추정의 3배 이상 또는 1/3 이하, 소비 60일치 초과 등). 정상(추정값·입력함)은 평문, 문제만 '확인 필요'로 시작해 필터와 배지가 잡아낸다.

### 상태 줄 (Signature)
표 위 한 줄: 진행률 줄('직접 센 품목 n / N개', 네이비) · 상태 배지들 · '이력에 저장' 주 버튼. 배지는 긴급(빨강), 발주 필요(주황), 양호·데이터 없음(회색), 그리고 해당할 때만 '확인 필요 n'(주황)·'입력 오류 n'(빨강)이 오류 아이콘과 함께 나타난다. 개수가 0이면 회색. 저장 뒤에는 '… 에 저장했어요' 캡션과 다음 화면으로 가는 링크, 저장하지 않은 입력이 있으면 안내 캡션이 아래에 붙는다.

## Do's and Don'ts

### Do:
- **Do** 면 구분은 1px #C3CAD4 선과 미스트 대 카드 면 톤 차이로 한다.
- **Do** 포인트 네이비(#1F3B5C)는 누르는 것·고른 것에만, 빨강(#B3261E)·주황(#8F4F00)은 문제가 있는 곳에만 쓴다.
- **Do** 문제 상태는 색에만 의존하지 말고 문구('확인 필요 · 추정의 3배')와 아이콘으로 함께 말한다.
- **Do** 숫자 열은 tabular-nums로 맞추고, 캡션은 보조 글자(#566071)로 대비를 확보한다.
- **Do** 어두운 사이드바 안의 글자는 미스트(#E6E9EF) 또는 슬레이트(#A7B1BE)만 쓴다(각 13.58:1, 7.61:1).
- **Do** 모서리는 6px(버튼·입력) 또는 8px(카드·표) 중 하나를 쓴다.

### Don't:
- **Don't** box-shadow를 쓰지 않는다.
- **Don't** 정상 상태에 네이비·빨강·주황 배지나 바탕을 입히지 않는다.
- **Don't** 순검정(#000)이나 순백(#FFF) 바탕을 쓰지 않는다. 차콜과 미스트를 쓴다(주 버튼 위 글자만 예외로 흰색).
- **Don't** 지표마다 다른 색 칩을 붙이지 않는다. 아이콘은 한 가지 회색 선 아이콘.
- **Don't** 상자 안에 테두리 상자를 겹치지 않는다.
