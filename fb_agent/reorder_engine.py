"""발주 추천 엔진 v0 (Streamlit 비의존).

  python reorder_engine.py [--date YYYY-MM-DD]        그날의 추천 (기본: 오늘)
  python reorder_engine.py --eval                     2025 하반기로 학습 → 2026-01~09 로 검증한 평가표
  python reorder_engine.py --fit 시작 끝              그 기간으로 발주 확률 모델을 학습해 data/model/발주확률.json 에 저장

재고(실사·폐기·로스)가 아직 없다. 그래서 '언제'는 품목의 주문 습관으로, '얼마나'는 평소 주문량으로 맞추고, 재고가 들어오면 recommend(on_hand=...) 로 실제 재고를 쓴다.
(재생 평가에서 확인한 것: 수요×소비율로 수량을 새로 계산하면 오차 43%, 재고를 추정해 시점을 정하면 F1 58% 로 둘 다 단순 기준선보다 나빴다.
 주문은 '1팩·2팩' 같은 습관적인 단위라 평소 주문량이 가장 좋은 기준이고, 매출은 그 위에서 조금만 조정한다.)

시점   발주 확률 = 로지스틱(마지막 주문 후 경과일 ÷ 평소 주기, 주기, 주문 횟수, 품목의 요일 습관, 예상 매출 규모).
       확률 ≥ 임계값이면 '발주'. 업체 발주 요일·영업일이 아니면 '발주일 아님'. 모델 파일이 없으면 '경과일 ≥ 평소 주기' 규칙으로 대신한다.
수량   평소 주문량(최근 4회 중앙값) × 규모비^β.  규모비 = 앞으로 커버할 기간의 예측 매출 ÷ 평소 매출. 매출이 낮을 때 줄이고(β=0.25), 높을 때 조금 늘린다(β=0.5).
       반올림(올림은 오차가 더 컸다). 상한수량은 여유를 둔 값(25% 더).
시즌 품목  최근 12개월 중 4개월 이상 주문이 없던 품목. 비수기(작년 같은 달 주문 없음 + 최근 45일 주문 없음)는 추천하지 않고,
       작년 같은 달에 주문이 있었는데 아직 없으면 '시즌 시작 예상'으로 알린다.
재고 확인  주문 간격 중앙값이 14일보다 길어 재고 없이는 시점 판단이 불가능한 품목.
업체 발주 요일과 리드타임은 D 이전 청구에서 구한다 (최근 365일, 요일별 중앙값은 8건 이상일 때만).
"""
import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import sales_forecast as sf
import store_calendar as sc

DATA = Path(__file__).resolve().parent / "data" / "cleaned"
MODEL_PATH = Path(__file__).resolve().parent / "data" / "model" / "발주확률.json"
EVAL_PATH = MODEL_PATH.with_name("평가결과.json")      # --eval 이 남기는 검증 수치 (화면에 보여 준다)
REAL_STORE = "수원점"
K = ["품목코드_RMS", "품명", "규격"]
WEEK = "월화수목금토일"
MIN_ORDERS = 3          # 최근 365일에 이만큼은 주문해야 '정기 품목'
MAX_GAP = 21            # 커버 기간 상한(일)
LONG_GAP = 14           # 주문 간격 중앙값이 이보다 길면 재고 없이는 시점을 판단할 수 없다 → "재고 확인"
WINDOW, SEASON_WINDOW = 180, 90   # 평소 매출·소비 속도를 보는 기간(일)
SEASON_OFF_MONTHS = 4   # 최근 12개월 중 이 개월 이상 주문이 없으면 시즌 품목
SEASON_RECENT = 45      # 시즌 품목이 이 기간 안에 주문했으면 성수기로 본다
FEATURES = ["gapratio", "over", "dow", "lg", "ln", "since", "lscale"]


# ── 발주 확률 모델 (numpy 만 쓰는 로지스틱 회귀) ──────────────────────
def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    X1 = np.c_[np.ones(len(X)), X]
    w = np.zeros(X1.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X1 @ w))
        grad = X1.T @ (p - y) + l2 * np.r_[0, w[1:]]
        hess = (X1.T * (p * (1 - p))) @ X1 + l2 * np.eye(len(w))
        w -= np.linalg.solve(hess, grad)
    return w


def auc(y: np.ndarray, s: np.ndarray) -> float:
    ranks = pd.Series(s).rank(method="average").to_numpy()      # 동점은 평균 순위
    n1 = float(y.sum())
    n0 = len(y) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else float("nan")


def prf(y: np.ndarray, pred: np.ndarray) -> tuple[float, float, float]:
    tp = float(((pred == 1) & (y == 1)).sum())
    p = tp / max(1.0, float(pred.sum()))
    r = tp / max(1.0, float(y.sum()))
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


@dataclass
class TimingModel:
    w: np.ndarray
    mu: np.ndarray
    sd: np.ndarray
    th: float
    info: dict

    def prob(self, feat: dict) -> float:
        x = (np.array([feat[f] for f in FEATURES]) - self.mu) / self.sd
        return float(1 / (1 + np.exp(-(self.w[0] + x @ self.w[1:]))))

    @classmethod
    def fit(cls, rows: pd.DataFrame, info: dict | None = None) -> "TimingModel":
        """rows: 특성 열(FEATURES)과 실제발주(0/1). 임계값은 같은 학습 자료에서 F1 이 가장 큰 값."""
        X = rows[FEATURES].to_numpy(float)
        mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
        y = rows["실제발주"].to_numpy(float)
        w = fit_logistic((X - mu) / sd, y)
        p = 1 / (1 + np.exp(-(np.c_[np.ones(len(X)), (X - mu) / sd] @ w)))
        ths = np.arange(0.2, 0.8, 0.02)
        th = float(ths[int(np.argmax([prf(y, (p >= t).astype(int))[2] for t in ths]))])
        return cls(w, mu, sd, th, (info or {}) | {"n": int(len(rows)), "auc": auc(y, p)})

    def save(self, path: Path = MODEL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"features": FEATURES, "w": self.w.tolist(), "mu": self.mu.tolist(), "sd": self.sd.tolist(), "threshold": self.th, "info": self.info},
                                   ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "TimingModel | None":
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        assert d["features"] == FEATURES, "모델의 특성 목록이 코드와 다릅니다. --fit 으로 다시 학습하세요."
        return cls(np.array(d["w"]), np.array(d["mu"]), np.array(d["sd"]), d["threshold"], d["info"])


# ── 자료 ─────────────────────────────────────────────────
@dataclass
class Book:
    orders: pd.DataFrame      # 품목·청구일 단위 주문 (거래처, K, 단위, 청구일, 수량, 도착일)
    lines: pd.DataFrame       # 청구 품목행 (업체별 리드타임 계산용)
    daily: pd.Series          # 일자별 순매출 (휴점일 0 포함, index=date)
    by_item: dict


def load_book(years=(2025, 2026)) -> Book:
    r = pd.concat([pd.read_csv(DATA / str(y) / "구매청구_정제.csv", dtype={"품목코드_RMS": str}) for y in years], ignore_index=True)
    for c in ("청구일자", "납기일자"):
        r[c] = pd.to_datetime(r[c]).dt.date
    r["입고일"] = pd.to_datetime(r["입고일자"], errors="coerce").dt.date
    r["도착"] = r["입고일"].where(r["입고일"].notna(), r["납기일자"])
    lines = r[r["입고일"].notna()].assign(리드=lambda t: [(a - b).days for a, b in zip(t["입고일"], t["청구일자"])])[["거래처", "청구일자", "리드"]]
    o = r.groupby(["거래처"] + K + ["발주단위", "청구일자"], as_index=False).agg(수량=("발주수량", "sum"), 도착=("도착", "max"))
    daily = pd.concat([pd.read_csv(DATA / str(y) / "매출일자별_정제.csv") for y in years])
    daily = pd.Series(daily["순매출"].astype(float).values, index=[date.fromisoformat(x) for x in daily["매출일자"]]).sort_index()
    by_item = {k: g.sort_values("청구일자").reset_index(drop=True) for k, g in o.groupby(K)}
    return Book(o, lines, daily, by_item)


def load_eval() -> dict | None:
    return json.loads(EVAL_PATH.read_text(encoding="utf-8")) if EVAL_PATH.exists() else None


_AUTO = object()


class Engine:
    def __init__(self, book: Book | None = None, hist: pd.Series | None = None, model=_AUTO, beta_down: float = 0.25, beta_up: float = 0.5):
        self.b = book or load_book()
        self.hist = sf.load_history() if hist is None else hist
        self.model = TimingModel.load() if model is _AUTO else model
        self.beta_down, self.beta_up = beta_down, beta_up      # 수량 탄력성: 규모비<1 / >1 일 때 (평소 주문량 × 규모비^β)
        self.last = max(self.b.daily.index)                    # 매출 자료의 마지막 날 (이후 날짜는 실제가 아니라 예측으로 채운다)
        self._fc, self._sched = {}, {}

    # ── 매출 ──────────────────────────────────────────────
    def fc(self, D: date, t: date) -> float:
        """D 에 알고 있는 정보로 t 일 매출 예측 (휴점은 0, 미확정 월요일은 휴점 확률만큼 줄임)."""
        if sc.is_closed(t):
            return 0.0
        key = (D, t)
        if key not in self._fc:
            p = sf.forecast(self.hist, t, horizon=max(1, (t - D).days + 1))
            p = p if p else float(self.hist[self.hist.index < D].tail(28).mean())
            self._fc[key] = p * (1 - sc.monday_closure_rate()) if sc.status(t)[0] == "미확정" else p
        return self._fc[key]

    def day_sales(self, D: date, d: date) -> float:
        """d 일 매출: D 전날까지이고 자료가 있으면 실제, 아니면 예측 (자료가 끝난 뒤의 날짜를 0원으로 보지 않는다)."""
        return self.b.daily.get(d, 0.0) if (d < D and d <= self.last) else self.fc(D, d)

    def sales(self, D: date, a: date, b: date) -> float:
        """[a, b) 매출."""
        return sum(self.day_sales(D, a + timedelta(days=i)) for i in range((b - a).days))

    # ── 업체 일정 ─────────────────────────────────────────
    def schedule(self, supplier: str, D: date):
        key = (supplier, D.toordinal() // 7)
        if key not in self._sched:
            ln = self.b.lines[(self.b.lines["거래처"] == supplier) & (self.b.lines["청구일자"] < D) & (self.b.lines["청구일자"] >= D - timedelta(days=365))]
            ld = ln.drop_duplicates(["청구일자"])
            if len(ld) < 5:
                self._sched[key] = None
            else:
                share = pd.Series([d.weekday() for d in ld["청구일자"]]).value_counts(normalize=True)
                days = {int(w) for w, v in share.items() if v >= 0.1}
                allm = float(ln["리드"].median())
                leads = {}
                for w in range(7):
                    x = ln[[d.weekday() == w for d in ln["청구일자"]]]["리드"]
                    leads[w] = int(np.ceil(x.median())) if len(x) >= 8 else int(np.ceil(allm))
                self._sched[key] = (days, leads)
        return self._sched[key]

    def next_open(self, d: date) -> date:
        while sc.is_closed(d):
            d += timedelta(days=1)
        return d

    def next_order_day(self, supplier: str, D: date):
        s = self.schedule(supplier, D)
        d = D + timedelta(days=1)
        for _ in range(21):
            if d.weekday() in s[0] and not sc.is_closed(d):
                return d, self.next_open(d + timedelta(days=s[1][d.weekday()]))
            d += timedelta(days=1)
        return None, None

    # ── 품목 추천 ─────────────────────────────────────────
    def season_state(self, g: pd.DataFrame, D: date) -> str:
        """'' (일반) | '성수기' | '비수기' | '시즌 시작 예상'. 최근 12개월 월별 주문 유무로 판단."""
        yr = g[(g["청구일자"] < D) & (g["청구일자"] >= D - timedelta(days=365))]
        months = {(d.year, d.month) for d in yr["청구일자"]}
        first = g["청구일자"].iloc[0]
        cur = [d for d in (D - timedelta(days=30 * k) for k in range(12)) if (d.year, d.month) >= (first.year, first.month)]   # 품목이 처음 주문된 달부터만 센다
        if sum((d.year, d.month) not in months for d in cur) < SEASON_OFF_MONTHS:
            return ""
        if ((g["청구일자"] < D) & (g["청구일자"] >= D - timedelta(days=SEASON_RECENT))).any():
            return "성수기"
        ly = g[(g["청구일자"] >= D - timedelta(days=365 + 20)) & (g["청구일자"] <= D - timedelta(days=365 - 20))]
        return "시즌 시작 예상" if len(ly) else "비수기"

    def recommend_item(self, key: tuple, D: date, on_hand: float | None = None) -> dict:
        g = self.b.by_item[key]
        past = g[(g["청구일자"] < D) & (g["청구일자"] >= D - timedelta(days=365))]
        supplier, unit = (past["거래처"].mode().iloc[0] if len(past) else g["거래처"].iloc[-1]), g["발주단위"].iloc[-1]
        out = dict(_key=key, 코드=key[0], 거래처=supplier, 품목=key[1], 규격=key[2], 단위=unit, 상태="", 시즌="", 확률=np.nan, 권장수량=np.nan, 상한수량=np.nan, 기준수량=np.nan, 규모비=np.nan,
                   입고예정일=None, 커버일수=np.nan, 직전발주=None, 사유="", **{f: np.nan for f in FEATURES})
        if len(past) < MIN_ORDERS:
            return out | dict(상태="불규칙", 사유=f"최근 1년 주문 {len(past)}회 (정기 {MIN_ORDERS}회 이상 필요)")
        season = self.season_state(g, D)
        out["시즌"] = season
        if season == "비수기":
            return out | dict(상태="비수기", 사유="작년 같은 시기에도 주문이 없던 시즌 품목 — 시즌 메뉴가 시작되면 알림")
        if season == "시즌 시작 예상":
            return out | dict(상태="시즌 시작 예상", 사유=f"작년 이맘때 주문이 있었던 시즌 품목 (최근 {SEASON_RECENT}일 주문 없음) — 시즌 메뉴 일정 확인")
        sch = self.schedule(supplier, D)
        if sch is None:
            return out | dict(상태="불규칙", 사유="업체 이력 부족")
        if D.weekday() not in sch[0] or sc.is_closed(D):
            return out | dict(상태="발주일 아님", 사유=f"{supplier} 발주 요일 아님" if D.weekday() not in sch[0] else "휴점")
        L = sch[1][D.weekday()]
        A = self.next_open(D + timedelta(days=L))
        n_day, A2 = self.next_order_day(supplier, D)
        W = SEASON_WINDOW if season else WINDOW
        win = past[past["청구일자"] >= D - timedelta(days=W)]
        if len(win) < 2:
            return out | dict(상태="불규칙", 사유="평소 매출 대비 주문을 구할 이력이 부족")
        S_win = sum(self.day_sales(D, D - timedelta(days=k)) for k in range(1, W + 1))
        if S_win <= 0:
            return out | dict(상태="불규칙", 사유="기준 기간 매출 없음")
        od = list(past["청구일자"])
        gaps = np.diff([x.toordinal() for x in od])
        mg = max(1.0, float(np.median(gaps)))
        arr_gaps = np.diff(sorted(x.toordinal() for x in win["도착"]))
        raw_gap = float(np.median(arr_gaps)) if len(arr_gaps) else 1.0
        gap = int(np.clip(round(W / len(win)), 1, MAX_GAP))               # 평균 주문 주기 = 커버 기간
        base = float(past["수량"].tail(4).median())                         # 평소 주문량
        f_cover = self.sales(D, A, A + timedelta(days=gap))
        scale = f_cover / (gap * S_win / W)                                  # 규모비 = 앞으로의 예측 매출 ÷ 평소 매출
        q = base * (scale ** (self.beta_down if scale < 1 else self.beta_up))
        hi = max(q, base * (scale ** self.beta_up)) * 1.25
        since = (min(D, self.last + timedelta(days=1)) - od[-1]).days      # 자료가 끝난 뒤 날짜는 '자료 마지막 날 다음 날' 기준 (모델이 본 적 없는 경과일로 외삽하지 않게)
        feat = dict(gapratio=min(4.0, since / mg), over=float(since >= mg - 0.5), dow=float(np.mean([x.weekday() == D.weekday() for x in od])),
                    lg=float(np.log(mg)), ln=float(np.log(len(od))), since=float(min(30, since)), lscale=float(np.log(max(0.2, scale))))
        if on_hand is not None:                                               # 실제 재고가 있으면 확률 대신 재고로 판단
            end = A2 if A2 else A + timedelta(days=gap)
            rate = float(win["수량"].sum()) / S_win
            need = rate * self.sales(D, D, end)
            p, due, why = np.nan, float(on_hand) < need, f"재고 {on_hand:g}{unit} < {end:%m-%d} 입고 전 예상 소비 {need:.1f}{unit}"
        elif self.model is not None:
            p = self.model.prob(feat)
            due, why = p >= self.model.th, f"발주 확률 {p * 100:.0f}% (임계 {self.model.th * 100:.0f}%) · 마지막 발주 {since}일 전 / 평소 주기 {mg:.0f}일"
        else:
            p, due, why = np.nan, since >= mg - 0.5, f"마지막 발주 {since}일 전 / 평소 주기 {mg:.0f}일 (확률 모델 없음)"
        step = 0.1 if unit in ("킬로그램", "kg") else 1.0
        rnd = lambda x: float(max(step, np.round(x / step) * step))
        up = lambda x: float(max(step, np.ceil(x / step - 1e-9) * step))
        last = past.iloc[-1]
        long_cycle = raw_gap > LONG_GAP
        out |= dict(상태="재고 확인" if long_cycle else ("발주" if due else "보류"), 확률=p, 권장수량=rnd(q), 상한수량=up(hi), 기준수량=base, 규모비=scale,
                    입고예정일=A, 커버일수=gap, 직전발주=f"{last['청구일자']:%m-%d} {last['수량']:g}", **feat,
                    사유=(f"주문 간격 중앙값 {raw_gap:.0f}일 — 재고 없이는 시점 판단 불가, 마지막 발주 {since}일 전" if long_cycle else why))
        return out

    def recommend(self, D: date, suppliers=None, on_hand: dict | None = None) -> pd.DataFrame:
        rows = []
        for key, g in self.b.by_item.items():
            if g["청구일자"].iloc[0] >= D:
                continue
            r = self.recommend_item(key, D, (on_hand or {}).get(key))
            if suppliers is None or r["거래처"] in suppliers:
                rows.append(r)
        return pd.DataFrame(rows)


# ── 재생 평가 ────────────────────────────────────────────
def replay(e: Engine, start: date, end: date) -> pd.DataFrame:
    """[start, end] 의 영업일마다 그날까지의 정보로 추천하고 실제 발주와 비교한 표.
    행 = (날짜, 품목) 중 정기 품목이 업체 발주일을 맞은 경우 (상태가 발주·보류·재고 확인). 특성·추천·실제 발주 여부·실제 수량·기준선 포함."""
    actual = {}
    for key, g in e.b.by_item.items():
        for d, q in zip(g["청구일자"], g["수량"]):
            actual[(d, key)] = actual.get((d, key), 0.0) + float(q)
    rows, D = [], start
    while D <= end:
        if not sc.is_closed(D):
            t = e.recommend(D)
            for r in t[t["상태"].isin(["발주", "보류", "재고 확인"])].to_dict("records"):
                r["날짜"], r["실제발주"] = D, (D, r["_key"]) in actual
                r["실제수량"] = actual.get((D, r["_key"]), np.nan)
                rows.append(r)
        D += timedelta(days=1)
    return pd.DataFrame(rows)


def evaluate(R: pd.DataFrame, title: str = "") -> dict:
    reg = R[R["상태"].isin(["발주", "보류"])]
    y = reg["실제발주"].to_numpy(int)
    out = {"n": len(reg), "재고확인": int((R["상태"] == "재고 확인").sum())}
    out["엔진"] = prf(y, (reg["상태"] == "발주").to_numpy(int))
    out["간격규칙"] = prf(y, reg["over"].to_numpy(int))
    out["전부"] = prf(y, np.ones(len(reg), int))
    out["auc"] = auc(y, reg["확률"].to_numpy(float)) if reg["확률"].notna().all() else float("nan")
    hit = reg[reg["실제발주"]].dropna(subset=["실제수량"])
    w = lambda c: float((hit["실제수량"] - c).abs().sum() / hit["실제수량"].sum() * 100)
    out["수량"] = {"n": len(hit), "엔진": w(hit["권장수량"]), "직전4회": w(hit["기준수량"])}
    if title:
        print(f"■ {title}: 정기 품목 판단 {out['n']:,}건 (재고 확인 {out['재고확인']:,}건 제외), 실제 발주 비율 {y.mean() * 100:.0f}%")
        for nm in ("엔진", "간격규칙", "전부"):
            p, r, f = out[nm]
            print(f"   시점 {nm:6s} 정밀도 {p * 100:4.1f}%  재현율 {r * 100:4.1f}%  F1 {f * 100:4.1f}%")
        print(f"   발주 확률 AUC {out['auc']:.3f}")
        print(f"   수량 (실제 발주 {out['수량']['n']:,}건): 엔진 WAPE {out['수량']['엔진']:.1f}%  | 평소 주문량 그대로 {out['수량']['직전4회']:.1f}%")
    return out


def season_report(e: Engine, start: date, end: date, step: int = 7) -> dict:
    """시즌 라벨이 맞는지: 비수기로 본 품목이 곧 주문했는가(오탐), 시즌 시작 예상으로 본 품목이 실제로 곧 시작했는가."""
    off = [0, 0]
    soon = [0, 0]
    D = start
    while D <= end:
        t = e.recommend(D)
        for lab, days, acc in (("비수기", 7, off), ("시즌 시작 예상", 14, soon)):
            for k in t[t["상태"] == lab]["_key"]:
                g = e.b.by_item[k]
                acc[0] += 1
                acc[1] += int(((g["청구일자"] >= D) & (g["청구일자"] < D + timedelta(days=days))).any())
        D += timedelta(days=step)
    print(f"■ 시즌 라벨 ({start}~{end}, {step}일 간격 점검)")
    print(f"   비수기 {off[0]}건 중 7일 안에 실제 주문한 것 {off[1]}건 ({off[1] / max(1, off[0]) * 100:.1f}%) — 낮을수록 좋다")
    print(f"   시즌 시작 예상 {soon[0]}건 중 14일 안에 실제 주문한 것 {soon[1]}건 ({soon[1] / max(1, soon[0]) * 100:.1f}%)")
    return {"비수기_건수": off[0], "비수기_오탐": off[1], "시즌시작예상_건수": soon[0], "시즌시작예상_적중": soon[1]}


def season_start_recall(e: Engine, start: date, end: date) -> dict:
    """시즌 품목이 45일 넘게 쉬다가 다시 주문을 시작한 날(시즌 시작)마다, 시작 전 30일 안에 '시즌 시작 예상'으로 알렸는지."""
    starts = []
    for k, g in e.b.by_item.items():
        od = list(g["청구일자"])
        for a, b in zip(od, od[1:]):
            if (b - a).days > 45 and start <= b <= end and len(g[g["청구일자"] < b]) >= MIN_ORDERS:
                starts.append((k, b))
    flagged, checked = 0, 0
    for k, b in starts:
        g = e.b.by_item[k]
        if e.season_state(g[g["청구일자"] < b], b - timedelta(days=1)) == "":
            continue                                      # 시즌 품목이 아니면(불규칙 품목) 제외
        checked += 1
        flagged += any(e.season_state(g[g["청구일자"] < b - timedelta(days=lead)], b - timedelta(days=lead)) == "시즌 시작 예상" for lead in range(7, 31, 7))
    print(f"   시즌 시작 {checked}건 중 시작 7~30일 전에 '시즌 시작 예상'으로 알린 것 {flagged}건 ({flagged / max(1, checked) * 100:.0f}%)")
    return {"시즌시작_건수": checked, "시즌시작_미리알림": flagged}


def fit_model(e: Engine, start: date, end: date) -> TimingModel:
    e.model = None
    R = replay(e, start, end)
    reg = R[R["상태"].isin(["발주", "보류"])].copy()
    reg["실제발주"] = reg["실제발주"].astype(float)
    return TimingModel.fit(reg, {"학습기간": f"{start}~{end}"})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--fit", nargs=2, metavar=("시작", "끝"))
    a = ap.parse_args()
    if a.eval:
        e = Engine(model=None)
        m = fit_model(e, date(2025, 7, 1), date(2025, 12, 31))
        print(f"학습(2025-07~12): 발주 확률 모델 AUC {m.info['auc']:.3f}, 임계값 {m.th:.2f}, 계수(표준화) {dict(zip(['절편'] + FEATURES, np.round(m.w, 2)))}\n")
        e.model = m
        ev = evaluate(replay(e, date(2026, 1, 1), date(2026, 9, 30)), "검증 2026-01~09 (학습에 쓰지 않은 기간)")
        print()
        sr = season_report(e, date(2026, 1, 5), date(2026, 9, 28))
        sr |= season_start_recall(e, date(2026, 1, 1), date(2026, 9, 30))
        EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVAL_PATH.write_text(json.dumps({
            "학습기간": "2025-07-01~2025-12-31", "검증기간": "2026-01-01~2026-09-30", "판단건수": ev["n"],
            "시점": {nm: dict(zip(("정밀도", "재현율", "F1"), map(float, ev[nm]))) for nm in ("엔진", "간격규칙", "전부")}, "AUC": ev["auc"],
            "수량": ev["수량"], "시즌": sr}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n저장: {EVAL_PATH}")
        return 0
    if a.fit:
        e = Engine(model=None)
        m = fit_model(e, date.fromisoformat(a.fit[0]), date.fromisoformat(a.fit[1]))
        m.save()
        print(f"저장: {MODEL_PATH}  (n={m.info['n']:,}, AUC {m.info['auc']:.3f}, 임계 {m.th:.2f})")
        return 0
    D = date.fromisoformat(a.date) if a.date else date.today()
    e = Engine()
    t = e.recommend(D)
    st = sc.status(D)
    print(f"{D} ({WEEK[D.weekday()]}) 휴점상태: {st[0]} {st[1]}" + ("" if e.model else "   ※ 발주 확률 모델 없음 — python reorder_engine.py --fit 시작 끝"))
    if D > e.last + timedelta(days=3):
        print(f"※ 매출·발주 자료가 {e.last}까지입니다. {(D - e.last).days}일 뒤 날짜라 최근 주문 이력이 빠져 있어 결과가 부정확합니다. 자료를 갱신하세요.")
    print(t["상태"].value_counts().to_string())
    cols = ["거래처", "품목", "규격", "단위", "시즌", "권장수량", "상한수량", "입고예정일", "직전발주", "사유"]
    print("\n■ 오늘 발주 추천")
    print(t[t["상태"] == "발주"][cols].to_string(index=False))
    for lab in ("시즌 시작 예상", "재고 확인"):
        x = t[t["상태"] == lab]
        if len(x):
            print(f"\n■ {lab} ({len(x)}건)")
            print(x[["거래처", "품목", "규격", "사유"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
