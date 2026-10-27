---
target: 재고 실사 입력 화면 /stock-input
total_score: 16
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 5
target_identity: "url:http://localhost:8501/stock-input"
timestamp: 2026-10-27T03-28-01Z
slug: localhost-stock-input
---
Method: dual-agent (A: design review · B: detector + browser)

# 재고 실사 입력 화면 (/stock-input, Operate) — 2026-10-27

Design Health Score 16/40 (Poor). 1 시스템 상태 2 · 2 실세계 일치 2 · 3 사용자 통제 2 · 4 일관성 2 · 5 오류 예방 1 · 6 기억보다 인식 1 · 7 유연성 1 · 8 미니멀 2 · 9 오류 복구 2 · 10 도움말 2.

Design specificity: 아무 Streamlit 대시보드에나 쓸 수 있는 화면. 실사 입력을 위한 상호작용(환산 결과, 진행률, 이상값, 동선)이 없다.

Detector: 데스크톱 오버레이 13(저대비 12, 중첩 카드 1), 휴대폰 9(저대비 9). 캡션 rgb(107,122,148) 대비 4.34/3.98 < 4.5. 중첩 카드·0×0 오버레이는 거짓 양성 의심. 사용자에게 보이는 [Human] 오버레이 없음.

Priority issues
- [P1] 입력 표에 환산 결과·환산 기준(1PK=?)이 없음 → clarify, typeset
- [P1] 이상값 경고·전회 대비 급변·미입력 표시 없음(-3·9999999 통과) → harden
- [P1] 진행률·미저장 경고·저장 후 다음 행동 없음 → layout, onboard
- [P1] 휴대폰에서 BOX·PK·낱개 열이 화면 밖, 행 35px, 첫 행이 y≈1270 → adapt
- [P1] KPI(811개 기준)와 표(174개 기준) 불일치 (직접 확인)
- [P2] KPI 상태 색 위치 기준(긴급=파랑, 양호=주황), 정보 위계(7줄 배너), lang=en, 캡션 대비, 소수점 불일치
- [P2] 파트·동선 묶음은 데이터 없음 → 정렬·사용자 지정 순서로 대체

Personas: 월말 인벤 파트 직원(태블릿), 마감 후 관리자(PC), 피곤한 반복 입력자(휴대폰).
