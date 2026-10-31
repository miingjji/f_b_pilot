"""버린 방법 두 가지를 같은 평가 틀로 다시 잰다: ① 수요×소비율로 발주 수량 계산, ② 추정 재고로 발주 시점 판단.

    cd fb_agent
    FB_MASTER=real python experiments/discarded_methods.py            # 2026-01 ~ 09, 약 5분

엔진의 재생 평가(reorder_engine.replay)와 같은 행·같은 기간(2026-01~09)에서 비교한다. 모든 값은 그 발주일 이전 정보만 쓴다.
  ① 수량 = 수요 × 소비율 = (평소 매출 1원당 주문량) × (다음 입고 전까지 예측 매출). 엔진의 '재고를 아는 경우' 소비 예상과 같은 식이다.
     오차는 실제 발주한 건의 수량 WAPE (엔진 평가와 같은 기준). 비교: 현재 엔진(같은 요일 최근 3회 중앙값), 직전 4회.
  ② 시점 = 월말 실사 + 그 뒤 입고 − 예상 소비로 추정한 재고가 다음 입고 전 예상 소비보다 적으면 '발주'.
     추정은 월말 실사 뒤 STALE_DAYS(14일) 안에서만 가능해서, 추정이 있는 판단에서만 현재 엔진(발주 확률)과 같은 행으로 견준다.
이 값은 재고 자료가 월말 실사뿐이라는 이 프로젝트의 한계 아래서 잰 것이다. 정의에 따라 값이 달라진다(① 은 아래 두 가지).
기대 결과: ① 실제 발주 5,271건 수요×소비율(입고 전 소비) 104.5% / (커버 기간) 40.3% / 현재 엔진 26.0% / 직전 4회 32.3%.
          ② 추정 재고가 있는 판단 3,189건(전체 10,662건 중) 추정 재고로 판단 F1 47.9%(정밀도 66.4%, 재현율 37.5%), 현재 엔진 F1 79.7%.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import reorder_engine as RE

START, END = date(2026, 1, 1), date(2026, 9, 30)


def window_rate(e: RE.Engine, key: tuple, D: date, season: str):
    """엔진이 recommend_item 안에서 구하는 소비 속도(매출 1원당 주문량)와 다음 입고일. 구할 수 없으면 None."""
    g = e.b.by_item[key]
    past = g[(g["청구일자"] < D) & (g["청구일자"] >= D - timedelta(days=365))]
    supplier = past["거래처"].mode().iloc[0]
    W = RE.SEASON_WINDOW if season else RE.WINDOW
    win = past[past["청구일자"] >= D - timedelta(days=W)]
    S_win = sum(e.day_sales(D, D - timedelta(days=k)) for k in range(1, W + 1))
    if len(win) < 2 or S_win <= 0:
        return None
    _, A2 = e.next_order_day(supplier, D)
    return float(win["수량"].sum()) / S_win, A2


def prf(y: np.ndarray, p: np.ndarray) -> tuple[float, float, float]:
    return RE.prf(y, p)


def main() -> int:
    e = RE.Engine()
    R = RE.replay(e, START, END)
    reg = R[R["상태"].isin(["발주", "보류"])].copy()
    need, est, cover = [], [], []
    for r in reg.to_dict("records"):
        key, D = r["_key"], r["날짜"]
        got = window_rate(e, key, D, r["시즌"])
        if got is None:
            need.append(np.nan); est.append(np.nan); cover.append(np.nan); continue
        rate, A2 = got
        end = A2 if A2 else r["입고예정일"] + timedelta(days=int(r["커버일수"]))
        need.append(rate * e.sales(D, D, end))
        cover.append(rate * e.sales(D, r["입고예정일"], r["입고예정일"] + timedelta(days=int(r["커버일수"]))))
        v = e.stock_estimate(key, D, rate)
        est.append(np.nan if v is None else v)
    reg["need"], reg["est"], reg["cover"] = need, est, cover

    # ① 수량
    step = np.where(reg["단위"].isin(["킬로그램", "kg"]), 0.1, 1.0)
    reg["수요×소비율"] = np.maximum(step, np.round(reg["need"] / step) * step)                       # 다음 입고 전까지의 예상 소비
    reg["수요×소비율(커버기간)"] = np.maximum(step, np.round(reg["cover"] / step) * step)              # 입고일부터 평소 주문 주기만큼의 예상 매출 × 소비율
    h = reg[reg["실제발주"]].dropna(subset=["실제수량", "수요×소비율", "수요×소비율(커버기간)"])
    wape = lambda c: float((h["실제수량"] - h[c]).abs().sum() / h["실제수량"].sum() * 100)
    print(f"① 발주 수량 (실제 발주 {len(h):,}건, {START}~{END}): 수요×소비율(입고 전 소비) {wape('수요×소비율'):.1f}% | 수요×소비율(커버 기간) {wape('수요×소비율(커버기간)'):.1f}% | 현재 엔진 {wape('권장수량'):.1f}% | 직전 4회 {wape('직전4회수량'):.1f}%")

    # ② 시점
    s = reg.dropna(subset=["est", "need"])
    y = s["실제발주"].to_numpy(int)
    ps = (s["est"] < s["need"]).to_numpy(int)
    pe = (s["상태"] == "발주").to_numpy(int)
    for name, p in (("추정 재고로 판단", ps), ("현재 엔진(발주 확률)", pe)):
        pr, rc, f1 = prf(y, p)
        print(f"② 발주 시점, 재고 추정이 있는 판단 {len(s):,}건(전체 {len(reg):,}건 중, 실제 발주 비율 {y.mean() * 100:.0f}%): {name:14s} 정밀도 {pr * 100:4.1f}%  재현율 {rc * 100:4.1f}%  F1 {f1 * 100:4.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
