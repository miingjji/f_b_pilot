---
name: F&B Pilot 장부
description: 따뜻한 종이색 위에 먹색 글자와 깊은 녹색 포인트, 그림자 대신 가는 선으로 그린 현장 입력용 장부.
colors:
  ledger-green: "#1F5F4A"
  paper: "#F5F2EA"
  paper-card: "#FFFDF8"
  paper-shade: "#ECE7DB"
  paper-sidebar: "#EFEADE"
  paper-sidebar-shade: "#E7E1D2"
  table-header: "#E9E3D3"
  green-tint: "#E4EEE8"
  ink: "#1B2A22"
  ink-table-header: "#2B3A31"
  ink-muted: "#56645B"
  ink-icon: "#66746B"
  rule: "#DDD6C6"
  alert-red: "#B3261E"
  alert-orange: "#9A5600"
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
    backgroundColor: "{colors.ledger-green}"
    textColor: "{colors.paper-card}"
    rounded: "{rounded.sm}"
    typography: "{typography.label}"
  button-secondary:
    backgroundColor: "{colors.paper-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
  card:
    backgroundColor: "{colors.paper-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.85rem 1.1rem"
  filter-bar:
    backgroundColor: "{colors.paper-card}"
    rounded: "{rounded.md}"
    padding: "1rem 1.25rem"
  tab-selected:
    backgroundColor: "{colors.green-tint}"
    textColor: "{colors.ledger-green}"
    rounded: "{rounded.sm}"
    padding: "0.55rem 1rem"
  badge-problem:
    textColor: "{colors.alert-orange}"
  badge-error:
    textColor: "{colors.alert-red}"
---

# Design System: F&B Pilot 장부

## Overview

**Creative North Star: "장부 (The Ledger)"**

종이색 바탕 위에 먹색 글자로 칸을 채워 가는 장부다. 모든 면은 그림자가 아니라 가는 선(1px)으로 구분하고, 색은 아껴서 의미가 있는 곳에만 쓴다. 모드는 Operate: 창고·주방에서 서서 수십 개 품목을 반복 입력하는 현장 도구이므로 화려함보다 읽기 쉬움, 틀리지 않음, 덜 지침이 우선이다.

색은 세 겹으로 나뉜다. 종이와 먹색이 기본이고, 깊은 녹색은 사람이 누르거나 고른 것(행동·선택)에만 쓴다. 빨강·주황은 '문제가 있는 곳'에만 쓰며, 정상 상태에는 색을 입히지 않는다. 한글은 앱에 포함된 Pretendard Variable로 통일한다.

**Key Characteristics:**
- 따뜻한 종이 바탕(#F5F2EA)과 한 단계 밝은 카드 면(#FFFDF8)의 톤 차이로 층을 만든다.
- 그림자 없음. 1px 선(#DDD6C6)과 6~8px 모서리.
- 녹색 = 행동·선택, 빨강·주황 = 문제, 정상 = 무채색.
- 숫자는 자리 폭이 같은(tabular) 형태, 한글은 단어 단위 줄바꿈.
- 숫자 입력은 표(BOX · PK · 낱개)가 중심이고, 상태는 표 위 한 줄에 모은다.

## Colors

종이와 먹의 무채색 위에 녹색 하나, 경고색 둘뿐인 절제된 팔레트.

### Primary
- **장부 녹색** (ledger-green, #1F5F4A): 주 버튼, 선택된 탭·메뉴, 링크, 진행률 줄, 로고 타일. 행동과 선택에만 쓴다.
- **녹색 연한 면** (green-tint, #E4EEE8): 선택된 탭 배경, 사이드바 메뉴 hover.

### Secondary
- **경고 빨강** (alert-red, #B3261E): '긴급', '입력 오류' 같이 지금 고쳐야 하는 문제.
- **주의 주황** (alert-orange, #9A5600): '발주 필요', '확인 필요' 같이 확인해야 하는 문제.

### Neutral
- **종이** (paper, #F5F2EA): 앱 바탕.
- **카드 종이** (paper-card, #FFFDF8): 지표 칸·필터 바·폼·펼침 상자·보조 버튼의 면.
- **짙은 종이** (paper-shade, #ECE7DB): 입력 위젯 등 보조 바탕. 사이드바는 한 겹 더 진한 #EFEADE / #E7E1D2.
- **표 머리 종이** (table-header, #E9E3D3): 표 머리 배경, 글자는 #2B3A31.
- **먹색** (ink, #1B2A22): 본문과 제목. 순검정이 아니라 녹색 기운이 도는 먹.
- **보조 먹** (ink-muted, #56645B): 캡션·지표 라벨. 아이콘은 #66746B.
- **괘선** (rule, #DDD6C6): 모든 테두리와 표 선.

차트용 범주 색(config.toml chartCategoricalColors)과 녹색 단계 8~10색은 테마에 정의돼 있고 차트 전용이다.

### Named Rules
**The Quiet Normal Rule.** 정상 상태는 색을 입히지 않는다. 개수가 0인 상태 배지는 회색, 개수가 있을 때만 색을 띤다.

**The Green Means Press Rule.** 녹색은 누르거나 고른 것에만 쓴다. 상태 표시에 녹색을 쓰지 않는다.

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

그림자를 쓰지 않는다. 깊이는 종이(#F5F2EA) 위에 한 단계 밝은 카드 면(#FFFDF8)을 1px 괘선으로 두르는 톤 차이로만 만든다. 사이드바도 box-shadow 없이 오른쪽 1px 선만 둔다.

### Named Rules
**The Flat Ledger Rule.** box-shadow는 none. 면을 나누려면 1px #DDD6C6 선이나 톤 차이를 쓴다.

## Shapes

모서리는 두 단계다. 버튼·탭 위쪽·입력 위젯은 6px, 카드·필터 바·폼·펼침 상자·표는 8px. 모두 1px 괘선 테두리. 로고 타일(32px 정사각)은 7px. 사이드바의 메뉴 묶음 펼침은 테두리 없이 투명하게 두어 상자 안에 상자가 겹치지 않게 한다.

## Components

### Buttons
- **Shape:** 6px 모서리, 그림자 없음.
- **Primary:** 장부 녹색 바탕, 밝은 글자, 굵기 600, 자간 -0.005em. 한 구역에 하나('이력에 저장').
- **Secondary:** 카드 종이(#FFFDF8) 바탕 + 1px 괘선.
- **Tertiary (사이드바 메뉴):** 글자 #34433A, hover 시 연한 녹색 면 + 녹색 글자.

### Cards / Containers
- **지표 칸:** 카드 종이 면, 1px 괘선, 8px, 안쪽 0.85rem 1.1rem. 라벨은 작은 보조 먹, 숫자는 크게, 아이콘은 오른쪽 위에 한 가지 회색 선 아이콘.
- **필터 바·폼·펼침 상자:** 같은 면·선·모서리. 필터 바 안쪽 1rem 1.25rem.

### Inputs / Fields
- 테마의 6px 모서리, 괘선 테두리. 검색 칸은 돋보기 아이콘과 설명형 placeholder. 분류는 pills, 보기는 segmented control.

### Navigation
- **탭:** 굵기 600, 안쪽 0.55rem 1rem, 위쪽만 6px 모서리. 선택되면 녹색 글자 + 연한 녹색 면 + 3px 녹색 밑줄.
- **사이드바:** 짙은 종이 바탕, 선택된 메뉴는 녹색.

### 재고 입력 표 (Signature)
표는 장부의 칸이다. 열은 품목(고정) · BOX · PK · 낱개(입력 가능, 좁은 숫자 칸, 0 이상) · 합계 · 확인 · 환산 기준(읽기 전용). 표 머리는 #E9E3D3 바탕. '확인' 열은 문구로 상태를 말한다: '추정값'(손대지 않음), '입력함', '확인 필요 · 사유'(0 입력, 추정의 3배 이상 또는 1/3 이하, 소비 60일치 초과 등). 정상(추정값·입력함)은 평문, 문제만 '확인 필요'로 시작해 필터와 배지가 잡아낸다.

### 상태 줄 (Signature)
표 위 한 줄: 진행률 줄('직접 센 품목 n / N개', 녹색) · 상태 배지들 · '이력에 저장' 주 버튼. 배지는 긴급(빨강), 발주 필요(주황), 양호·데이터 없음(회색), 그리고 해당할 때만 '확인 필요 n'(주황)·'입력 오류 n'(빨강)이 오류 아이콘과 함께 나타난다. 개수가 0이면 회색. 저장 뒤에는 '… 에 저장했어요' 캡션과 다음 화면으로 가는 링크, 저장하지 않은 입력이 있으면 안내 캡션이 아래에 붙는다.

## Do's and Don'ts

### Do:
- **Do** 면 구분은 1px #DDD6C6 선과 종이 대 카드 종이 톤 차이로 한다.
- **Do** 녹색(#1F5F4A)은 누르는 것·고른 것에만, 빨강(#B3261E)·주황(#9A5600)은 문제가 있는 곳에만 쓴다.
- **Do** 문제 상태는 색에만 의존하지 말고 문구('확인 필요 · 추정의 3배')와 아이콘으로 함께 말한다.
- **Do** 숫자 열은 tabular-nums로 맞추고, 캡션은 보조 먹(#56645B)으로 대비를 확보한다.
- **Do** 모서리는 6px(버튼·입력) 또는 8px(카드·표) 중 하나를 쓴다.

### Don't:
- **Don't** box-shadow를 쓰지 않는다.
- **Don't** 정상 상태에 녹색·빨강·주황 배지나 바탕을 입히지 않는다.
- **Don't** 순검정(#000)이나 순백(#FFF) 바탕을 쓰지 않는다. 먹색과 종이색을 쓴다.
- **Don't** 지표마다 다른 색 칩을 붙이지 않는다. 아이콘은 한 가지 회색 선 아이콘.
- **Don't** 상자 안에 테두리 상자를 겹치지 않는다.
