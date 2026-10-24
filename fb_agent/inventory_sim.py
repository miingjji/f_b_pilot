"""재고·입고 순환 시뮬레이션 (Streamlit 비의존).

  python inventory_sim.py --backtest            과거 월말 실사에서 출발해 다음 달들의 월말 재고를 예측하고 실제 실사와 비교
  python inventory_sim.py --forecast YYYY-MM    마지막 월말 실사에서 출발해 그 달의 일별 재고·입고·발주를 예측해 data/forecast/ 에 저장

실사재고를 더 올리지 않아도 마지막 월말 실사(출발 재고)에서 날마다 이어서 굴린다:
    재고(오늘) = 재고(어제) − 소비(오늘) + 입고(오늘)
    소비   = 품목별 '매출 1원당 소비량' × 그날 예측 매출.  소비량 = (기초 + 입고 − 기말) 항등식으로 월별 실적을 구해 최근 몇 달의 합 ÷ 매출 합.
    입고   = 순환: 시뮬레이션한 재고가 발주점 아래로 내려가면 그 품목의 입고 요일에 평소 입고 단위만큼 들어온다 (입고가 재고에 영향을 주고, 그 재고가 다음 입고를 부른다).
수량 단위는 수불부의 실사재고 수량(규격 단위)이다.
"""
import argparse
import glob
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

LEDGER = Path(__file__).resolve().parent / "data" / "cleaned" / "수불부"


def month_end(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def add_month(ym: str, n: int) -> str:
    i = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{i // 12}-{i % 12 + 1:02d}"


def _key(t: pd.DataFrame) -> pd.Series:
    """품목 키: RMS 코드, 없으면 매장 코드."""
    return t["품목코드_RMS"].where(t["품목코드_RMS"] != "없음", t["품목코드_매장"])


@dataclass
class Ledger:
    counts: pd.DataFrame     # 월말 실사 수량 (행=품목 키, 열=월 'YYYY-MM')
    receipts: pd.DataFrame   # 월 입고 수량 (같은 모양, 없으면 0)
    daily: dict              # {키: [(입고일, 수량), ...]}
    meta: pd.DataFrame       # 품목 키별 품명·규격·거래처·계정·단가
    months: list

    @property
    def consumption(self) -> pd.DataFrame:
        """월 소비량 = 전월 기말 + 당월 입고 − 당월 기말 (첫 달은 알 수 없다)."""
        ms = self.months
        return pd.DataFrame({m: self.counts[a] + self.receipts[m] - self.counts[m] for a, m in zip(ms[:-1], ms[1:])})


def load_ledger(upto: str | None = None, root: Path | None = None) -> Ledger:
    """월별 정제본(실사재고·입고내역)을 읽는다. upto='YYYY-MM' 이면 그 달까지만 (백테스트에서 미래 자료가 새지 않게)."""
    root = root or LEDGER
    cnt, rec, daily, metas, months = [], [], {}, [], []
    for d in sorted(glob.glob(str(root / "20*" / "20*"))):
        m = Path(d).name
        if upto and m > upto:
            continue
        if not (Path(d) / "실사재고_정제.csv").exists() or not (Path(d) / "입고내역_정제.csv").exists():
            continue
        months.append(m)
        c = pd.read_csv(Path(d) / "실사재고_정제.csv", dtype={"품목코드_RMS": str, "품목코드_매장": str}).copy()
        c["key"] = _key(c)
        cnt.append(c.groupby("key")["재고실사_수량"].sum().rename(m))
        r = pd.read_csv(Path(d) / "입고내역_정제.csv", dtype={"품목코드_RMS": str, "품목코드_매장": str}).copy()
        r["key"] = _key(r)
        rec.append(r.groupby("key")["당월합계_수량"].sum().rename(m))
        y, mo = int(m[:4]), int(m[5:7])
        days = [f"{i}일_수량" for i in range(1, month_end(m).day + 1) if f"{i}일_수량" in r.columns]
        q = r.groupby("key")[days].sum()
        for k, day, v in zip(*np.nonzero(q.to_numpy() > 0), q.to_numpy()[q.to_numpy() > 0]):
            daily.setdefault(q.index[k], []).append((date(y, mo, int(days[day][:-4])), float(v)))
        metas.append(r.groupby("key").agg(품명=("품명", "last"), 규격=("규격", "last"), 거래처=("거래처명", "last"), 계정=("계정명", "last"), 단가=("단가", "last")))
        metas.append(c.groupby("key").agg(품명=("품명", "last"), 규격=("규격", "last"), 거래처=("거래처명", "last"), 계정=("계정명", "last")).assign(단가=np.nan))
    counts = pd.concat(cnt, axis=1)
    receipts = pd.concat(rec, axis=1)
    idx = counts.index.union(receipts.index)
    counts, receipts = counts.reindex(idx), receipts.reindex(idx).reindex(columns=counts.columns).fillna(0.0)
    meta = pd.concat(metas).groupby(level=0).last()
    meta["단가"] = pd.to_numeric(meta["단가"], errors="coerce")
    return Ledger(counts, receipts, daily, meta, months)


# ── 매출 계획 (소비의 바탕) ───────────────────────────────
class SalesPlan:
    """origin 다음 날부터의 일 매출 예측. origin 까지의 POS 매출만 보고, 휴점은 달력을 따른다 (미확정 월요일은 휴점 확률만큼 줄인다)."""

    def __init__(self, origin: date, hist: pd.Series | None = None):
        import sales_forecast as sf
        import store_calendar as sc
        self.sf, self.sc, self.origin = sf, sc, origin
        self.hist = sf.load_history() if hist is None else hist
        self._c = {}

    def day(self, d: date) -> float:
        if self.sc.is_closed(d):
            return 0.0
        if d not in self._c:
            h = max(1, (d - self.origin).days)
            p = self.sf.forecast(self.hist, d, horizon=h)
            p = p if p else float(self.hist[self.hist.index <= self.origin].tail(28).mean())
            self._c[d] = p * (1 - self.sc.monday_closure_rate()) if self.sc.status(d)[0] == "미확정" else p
        return self._c[d]

    def monthly_actual(self, upto: str) -> pd.Series:
        """월별 실제 매출(영업일 합), upto 월까지."""
        h = self.hist[[f"{d:%Y-%m}" <= upto for d in self.hist.index]]
        return h.groupby([f"{d:%Y-%m}" for d in h.index]).sum()


# ── 품목별 모수 (모두 origin 까지의 수불부에서) ─────────────
@dataclass
class Params:
    k_rate: int = 3          # 소비 속도를 보는 최근 개월 수 (백테스트: 짧을수록 좋았다. 소비는 최근 달이 가장 닮는다)
    k_event: int = 3         # 입고 습관(요일·단위)을 보는 최근 개월 수
    k_level: int = 12        # 평소 재고 수준을 보는 최근 개월 수 (길게 봐야 입고 주기 한 바퀴가 다 들어간다)
    level: str = "median"    # 평소 재고 수준: 월말 실사의 중앙값 | 평균
    day_share: float = 0.1   # 이 비율 이상의 입고가 있었던 요일을 입고 요일로 본다 (너무 좁히면 입고가 막혀 재고가 줄어든다)
    round_at: float = 0.5    # lumps="round" 에서 평소 입고 단위의 이만큼 모자라면 한 단위를 들여온다 (0.5 = 반올림)
    lumps: str = "cont"      # 입고 크기: cont(평소 수준까지 필요한 만큼) | round(평소 입고 단위의 배수로 반올림) | min1(부족하면 최소 1단위, 과잉 입고라 쓰지 않음)


def fit_items(L: Ledger, origin: str, plan: SalesPlan, p: Params) -> pd.DataFrame:
    """품목별 소비 속도(매출 1원당), 평소 재고 수준, 입고 단위·요일. 행=품목 키."""
    ms = L.months[: L.months.index(origin) + 1]
    sales = plan.monthly_actual(origin)
    cons = L.consumption[[m for m in ms[1:]]]
    hm = ms[-p.k_rate:]
    hm = [m for m in hm if m in cons.columns]
    rate = cons[hm].clip(lower=0).sum(axis=1) / float(sales.reindex(hm).sum())
    lvl_m = ms[-p.k_level:]
    level = L.counts[lvl_m].median(axis=1) if p.level == "median" else L.counts[lvl_m].mean(axis=1)
    start = month_end(add_month(origin, -p.k_event)) + timedelta(days=1)
    rows = {}
    for k, ev in L.daily.items():
        ev = [(d, q) for d, q in ev if start <= d <= month_end(origin)]
        if not ev:
            continue
        w = np.zeros(7)
        for d, _ in ev:
            w[d.weekday()] += 1
        w = w / w.sum()
        days = w >= p.day_share
        rows[k] = dict(Q=float(np.median([q for _, q in ev])), n_ev=len(ev), **{f"w{i}": bool(days[i]) for i in range(7)})
    ev = pd.DataFrame.from_dict(rows, orient="index", columns=["Q", "n_ev"] + [f"w{i}" for i in range(7)])
    out = pd.DataFrame({"rate": rate, "level": level}).join(ev, how="left")
    out["start"] = L.counts[origin]
    return out


# ── 구매청구(발주)와 수불부의 단위 연결 · 이미 발주한 입고 ─────
def po_factors(L: Ledger, book, origin: str) -> dict:
    """구매청구 발주수량 ÷ 수불부 입고수량 비율 {품목 키: 비율}. 도착 월로 맞추고, 비율이 달마다 흔들리는 품목(변동 20% 초과)은 뺀다.
    95% 가량 품목은 1 이다 (발주단위 = 규격 단위)."""
    o = book.orders[[d <= month_end(origin) for d in book.orders["도착"]]]
    q = o.groupby(["품목코드_RMS", [f"{d:%Y-%m}" for d in o["도착"]]])["수량"].sum().unstack()
    out = {}
    for k in q.index:
        if k not in L.receipts.index:
            continue
        ms = [m for m in q.columns if m in L.receipts.columns and m <= origin and q.loc[k, m] > 0 and L.receipts.loc[k, m] > 0]
        if len(ms) < 2:
            continue
        r = np.array([q.loc[k, m] / L.receipts.loc[k, m] for m in ms])
        if np.std(r) / np.median(r) < 0.2:
            out[k] = float(np.median(r))
    return out


def pipeline(book, factors: dict, origin_day: date) -> pd.DataFrame:
    """origin 일까지 이미 발주했는데 아직 안 들어온 입고 (도착일 > origin). 열: key, date, qty (수불부 단위)."""
    o = book.orders[(book.orders["청구일자"] <= origin_day) & (book.orders["도착"] > origin_day)]
    rows = [(k, d, q / factors[k]) for k, d, q in zip(o["품목코드_RMS"], o["도착"], o["수량"]) if k in factors]
    return pd.DataFrame(rows, columns=["key", "date", "qty"])


# ── 순환 시뮬레이션 ───────────────────────────────────────
@dataclass
class Result:
    stock: pd.DataFrame      # 일별 말 재고 (행=날짜, 열=품목)
    receipts: pd.DataFrame   # 일별 입고 (시뮬레이션이 정한 입고)
    cons: pd.DataFrame       # 일별 예상 소비
    sim_keys: list           # 시뮬레이션한 품목 (나머지는 출발 재고 그대로)


def simulate(f: pd.DataFrame, plan: SalesPlan, origin_day: date, end: date, lumps: str = "round", scheduled: pd.DataFrame | None = None, round_at: float = 0.5) -> Result:
    """origin_day(월말 실사일) 다음 날부터 end 까지 하루씩. 입고 요일에 재고가 평소 수준보다 모자라면 평소 입고 단위의 배수로 채운다 (순환)."""
    act = f[(f["rate"] > 0) & f["Q"].notna() & f["start"].notna()]
    keys = list(act.index)
    S = act["start"].to_numpy(float).copy()
    rate, Q = act["rate"].to_numpy(float), act["Q"].to_numpy(float)
    level = act["level"].fillna(act["start"]).to_numpy(float)
    W = act[[f"w{i}" for i in range(7)]].to_numpy(bool)
    nxt_gap = np.full((len(keys), 7), 7.0)
    for i in range(7):
        for j in range(7, 0, -1):
            nxt_gap[:, i] = np.where(W[:, (i + j) % 7], j, nxt_gap[:, i])
    n_days = (end - origin_day).days
    sch = np.zeros((n_days + 8, len(keys)))                 # 이미 발주해 도착일이 정해진 입고 (행 = origin 다음 날부터의 날짜)
    if scheduled is not None and len(scheduled):
        pos = {k: i for i, k in enumerate(keys)}
        for k, dd, q in zip(scheduled["key"], scheduled["date"], scheduled["qty"]):
            i, j = pos.get(k), (dd - origin_day).days - 1
            if i is not None and 0 <= j < n_days + 8:
                sch[j, i] += q
    days, st, rc, cs = [], [], [], []
    d = origin_day + timedelta(days=1)
    while d <= end:
        sales = plan.day(d)
        c = rate * sales
        S = S - c
        j0 = (d - origin_day).days - 1
        S = S + sch[j0]
        r = sch[j0].copy()
        r_in = np.zeros(len(keys))
        if not plan.sc.is_closed(d):
            ahead = np.cumsum([plan.day(d + timedelta(days=j)) for j in range(1, 8)])          # j일 뒤까지의 예상 매출
            use = rate * ahead[nxt_gap[:, d.weekday()].astype(int) - 1]                         # 다음 입고 요일까지 쓸 소비
            coming = np.cumsum(sch[j0 + 1: j0 + 8], axis=0)                                    # 앞으로 도착할 (이미 발주한) 입고
            got = coming[nxt_gap[:, d.weekday()].astype(int) - 1, np.arange(len(keys))]
            proj = S - use + got                                                                # 다음 입고 직전의 재고
            short = np.maximum(level - use / 2 - proj, 0.0)                                      # 입고 사이 평균 재고가 평소 수준이 되도록 모자란 양
            if lumps == "cont":
                amt = short
            elif lumps == "min1":
                amt = np.where(proj < np.maximum(level - Q / 2, 0.0), np.maximum(1.0, np.round(short / Q)) * Q, 0.0)
            else:
                amt = np.floor(short / Q + (1.0 - round_at)) * Q
            r_in = np.where(W[:, d.weekday()], amt, 0.0)
        S = np.maximum(S + r_in, 0.0)
        r = r + r_in
        days.append(d); st.append(S.copy()); rc.append(r); cs.append(c)
        d += timedelta(days=1)
    mk = lambda a: pd.DataFrame(np.array(a), index=days, columns=keys)
    return Result(mk(st), mk(rc), mk(cs), keys)


# ── 백테스트 ─────────────────────────────────────────────
def run_origin(L: Ledger, origin: str, months: int, p: Params, hist: pd.Series | None = None, book=None):
    """origin 월말 실사에서 출발해 months 개월 뒤 말일까지 굴린다. (모수 표, 시뮬레이션 결과, 계획) — book 이 있으면 이미 발주한 입고(도착 전)를 넣는다."""
    plan = SalesPlan(month_end(origin), hist)
    f = fit_items(L, origin, plan, p)
    sched = pipeline(book, po_factors(L, book, origin), month_end(origin)) if book is not None else None
    return f, simulate(f, plan, month_end(origin), month_end(add_month(origin, months)), p.lumps, sched, p.round_at), plan


def month_table(f: pd.DataFrame, res: Result, origin: str, months: int) -> pd.DataFrame:
    """품목×월 예측표 (긴 형식): 출발재고, 월말 재고, 월 입고, 월 소비. 시뮬레이션하지 않은(휴면) 품목은 출발 재고 그대로·입고 0."""
    rows = []
    start = f["start"].dropna()
    for h in range(1, months + 1):
        m = add_month(origin, h)
        days = [d for d in res.stock.index if f"{d:%Y-%m}" == m]
        t = pd.DataFrame({"예상월말재고": start})
        t["예상입고"], t["예상소비"] = 0.0, 0.0
        t["시뮬레이션"] = False
        k = res.sim_keys
        t.loc[k, "예상월말재고"] = res.stock.loc[days[-1], k]
        t.loc[k, "예상입고"] = res.receipts.loc[days, k].sum()
        t.loc[k, "예상소비"] = res.cons.loc[days, k].sum()
        t.loc[k, "시뮬레이션"] = True
        t["월"] = m
        rows.append(t.rename_axis("key").reset_index())
    return pd.concat(rows, ignore_index=True)


def score(pred: pd.Series, actual: pd.Series, price: pd.Series) -> dict:
    ok = pred.notna() & actual.notna()
    pred, actual = pred[ok], actual[ok]
    w = price.reindex(pred.index).fillna(price.median())
    e = (pred - actual).abs()
    return {"n": int(ok.sum()), "WAPE_금액": float((e * w).sum() / (actual * w).sum()), "WAPE_수량": float(e.sum() / actual.sum()),
            "±30% 이내": float((e <= 0.3 * actual.abs() + 0.5).mean()), "편향_금액": float(((pred - actual) * w).sum() / (actual * w).sum())}


def backtest(L: Ledger, origins: list[str], horizon: int, p: Params, hist=None, book=None) -> pd.DataFrame:
    """각 origin 에서 출발한 예측을 실제 실사·입고와 견주고, 같은 품목의 단순 기준선과 함께 낸다.
    대상은 시뮬레이션한 품목(소비·입고가 있는 품목). 재고 기준선 = 출발 재고 그대로, 입고 기준선 = 최근 3개월 월평균 입고."""
    rows, price = [], L.meta["단가"]
    for o in origins:
        f, res, _ = run_origin(L, o, horizon, p, hist, book)
        mt = month_table(f, res, o, horizon).set_index(["월", "key"])
        k = res.sim_keys
        i = L.months.index(o)
        base_rec = L.receipts[L.months[i - 2: i + 1]].mean(axis=1)
        for h in range(1, horizon + 1):
            m = add_month(o, h)
            if m not in L.counts.columns:
                continue
            x = mt.loc[m].loc[k]
            for what, pred, actual in (("월말 재고", x["예상월말재고"], L.counts[m]), ("월 입고", x["예상입고"], L.receipts[m]),
                                      ("월 소비", x["예상소비"], L.consumption[m].clip(lower=0))):
                rows.append({"origin": o, "h": h, "대상": what, "방법": "시뮬레이션", **score(pred, actual.reindex(k), price)})
            rows.append({"origin": o, "h": h, "대상": "월말 재고", "방법": "출발재고 그대로", **score(L.counts[o].reindex(k), L.counts[m].reindex(k), price)})
            rows.append({"origin": o, "h": h, "대상": "월 입고", "방법": "최근3개월 평균", **score(base_rec.reindex(k), L.receipts[m].reindex(k), price)})
    return pd.DataFrame(rows)


# ── 예측 저장 (동결) · 나중에 실제와 비교 ─────────────────
FORECAST_DIR = Path(__file__).resolve().parent / "data" / "forecast"


def forecast(origin: str | None = None, months: int = 3, p: Params | None = None, out_dir: Path | None = None, force: bool = False) -> Path:
    """가장 최근 월말 실사(origin)에서 출발해 months 개월 뒤까지 예측해 data/forecast/<origin>_출발/ 에 저장한다.
    저장한 예측은 동결한다: 이후 수불부가 들어와도 다시 쓰지 않는다 (force=True 가 아니면 덮어쓰기를 거부). 비교는 verify() 로."""
    import json
    import datetime as dt
    import reorder_engine as re
    p = p or Params()
    L = load_ledger(upto=origin)                                  # origin 이후 달이 있어도 쓰지 않는다
    origin = origin or L.months[-1]
    out = (out_dir or FORECAST_DIR) / f"{origin}_출발"
    if out.exists() and not force:
        raise FileExistsError(f"{out} 에 이미 동결된 예측이 있습니다. 덮어쓰려면 force=True (검증이 의미를 잃습니다).")
    book = re.load_book()
    f, res, plan = run_origin(L, origin, months, p, None, book)
    mt = month_table(f, res, origin, months)
    meta = L.meta
    mt = mt.join(meta[["품명", "규격", "거래처", "계정"]], on="key")
    mt["출발재고"] = mt["key"].map(f["start"])
    first_out = {}
    for k in res.sim_keys:
        z = res.stock.index[(res.stock[k] <= 1e-9).to_numpy()]
        first_out[k] = z[0] if len(z) else None
    mt["재고소진_예상일"] = mt["key"].map(first_out)
    daily = res.stock.stack().rename("예상재고").to_frame()
    daily["예상입고"], daily["예상소비"] = res.receipts.stack(), res.cons.stack()
    daily = daily.rename_axis(["일자", "key"]).reset_index().join(meta[["품명", "규격", "거래처", "계정"]], on="key")
    out.mkdir(parents=True, exist_ok=True)
    cols = ["월", "key", "품명", "규격", "거래처", "계정", "시뮬레이션", "출발재고", "예상월말재고", "예상입고", "예상소비", "재고소진_예상일"]
    mt[cols].to_csv(out / "월별_예측.csv", index=False, encoding="utf-8-sig")
    daily[["일자", "key", "품명", "규격", "거래처", "계정", "예상재고", "예상입고", "예상소비"]].to_csv(out / "일별_예측.csv", index=False, encoding="utf-8-sig")
    (out / "예측_정보.json").write_text(json.dumps({
        "생성시각": dt.datetime.now().isoformat(timespec="seconds"), "출발": origin, "출발일": str(month_end(origin)), "예측개월": months,
        "사용한_수불부": f"{L.months[0]} ~ {L.months[-1]}", "매출_자료_마지막날": str(plan.hist.index.max()), "품목수": int(f["start"].notna().sum()), "시뮬레이션_품목수": len(res.sim_keys),
        "모수": p.__dict__, "방법": "소비=매출 1원당 소비량×예측 매출, 입고=평소 수준을 지키는 재고 순환 정책(입고 요일에 필요한 만큼), 이미 발주한 입고 반영"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def verify(month: str, origin: str | None = None, out_dir: Path | None = None, L: Ledger | None = None) -> pd.DataFrame:
    """동결한 예측과 실제 수불부(month 달)를 견준다. 월말 재고·월 입고·월 소비의 오차를 시뮬레이션 품목 / 전체 품목으로 나눠 낸다."""
    L = L or load_ledger()
    if month not in L.counts.columns:
        raise FileNotFoundError(f"{month} 수불부가 아직 없습니다 (정제본 data/cleaned/수불부/{month[:4]}/{month}/).")
    origin = origin or add_month(month, -1)
    d = (out_dir or FORECAST_DIR) / f"{origin}_출발"
    if not d.exists():
        raise FileNotFoundError(f"{d} 에 동결된 예측이 없습니다.")
    mt = pd.read_csv(d / "월별_예측.csv", dtype={"key": str})
    mt = mt[mt["월"] == month].set_index("key")
    price = L.meta["단가"]
    sim = mt.index[mt["시뮬레이션"]]
    rows = []
    for grp, idx in (("시뮬레이션 품목", sim), ("전체 품목", mt.index)):
        for what, pred, actual in (("월말 재고", mt["예상월말재고"], L.counts[month]), ("월 입고", mt["예상입고"], L.receipts[month]),
                                  ("월 소비", mt["예상소비"], L.consumption[month].clip(lower=0))):
            rows.append({"범위": grp, "대상": what, "방법": "시뮬레이션", **score(pred.reindex(idx), actual.reindex(idx), price)})
        rows.append({"범위": grp, "대상": "월말 재고", "방법": "출발재고 그대로", **score(mt["출발재고"].reindex(idx), L.counts[month].reindex(idx), price)})
    R = pd.DataFrame(rows)
    item = mt.join(pd.DataFrame({"실제월말재고": L.counts[month], "실제입고": L.receipts[month], "실제소비": L.consumption[month].clip(lower=0)}), how="left")
    item["재고오차"] = item["예상월말재고"] - item["실제월말재고"]
    item.reset_index().to_csv(d / f"검증_{month}_품목별.csv", index=False, encoding="utf-8-sig")
    R.to_csv(d / f"검증_{month}_요약.csv", index=False, encoding="utf-8-sig")
    return R


# ── 발주일 예측: 예상 입고에서 거꾸로 ─────────────────────
def order_date_for(arrival: date, weekdays: set, leads: dict, is_closed, next_open) -> date | None:
    """입고일에 들어오게 하려면 언제 발주해야 하나. 업체 발주 요일이고 영업일이며, 요일별 리드타임을 더한 입고일(영업일로 밀림)이 입고일과 같은 가장 늦은 날.
    그런 날이 없으면 입고일 안에 들어오는 가장 늦은 발주일. 2주 안에 없으면 None."""
    d, best = arrival - timedelta(days=1), None
    for _ in range(14):
        if d.weekday() in weekdays and not is_closed(d):
            arr = next_open(d + timedelta(days=leads[d.weekday()]))
            if arr == arrival:
                return d
            if arr < arrival:
                return best or d
        d -= timedelta(days=1)
    return best


def orders_from_receipts(receipts: pd.DataFrame, scheduled: pd.DataFrame | None, factors: dict, origin_day: date, order_day_fn) -> pd.DataFrame:
    """일별 예상 입고(수불부 단위) → 발주 목록. 이미 발주한 입고(scheduled)는 빼고, 출발일 이후에 발주해야 하는 것만 남긴다.
    order_day_fn(품목 키, 입고일) → 발주일 또는 None. 열: 품목코드, 발주일, 입고예정일, 수량_수불부, 수량_발주단위."""
    r = receipts.copy()
    for k, d, q in (zip(scheduled["key"], scheduled["date"], scheduled["qty"]) if scheduled is not None and len(scheduled) else []):
        if k in r.columns and d in r.index:
            r.loc[d, k] = max(0.0, r.loc[d, k] - q)
    rows = []
    for k in r.columns:
        if k not in factors:
            continue
        for d, q in r[k].items():
            if q > 1e-9:
                od = order_day_fn(k, d)
                if od is not None and od > origin_day:
                    rows.append({"품목코드": k, "발주일": od, "입고예정일": d, "수량_수불부": float(q), "수량_발주단위": float(q) * factors[k]})
    return pd.DataFrame(rows, columns=["품목코드", "발주일", "입고예정일", "수량_수불부", "수량_발주단위"])


def order_plan(origin: str | None = None, months: int = 3, out_dir: Path | None = None, force: bool = False) -> Path:
    """동결한 예측과 같은 출발·같은 자료로, 입고를 평소 입고 단위의 덩어리로 들여오는 시뮬레이션(lumps=round)을 돌려 발주일을 만든다
    (연속 입고는 날마다 조금씩 들어와 실제 발주보다 훨씬 잦다). 구매청구 이력이 있는 품목만(발주 요일·리드타임·단위를 알 수 있다).
    data/forecast/<origin>_출발/발주일_예측.csv 에 쓰고, 이미 있으면 거부한다(동결)."""
    import reorder_engine as re
    import store_calendar as sc
    L = load_ledger(upto=origin)
    origin = origin or L.months[-1]
    out = (out_dir or FORECAST_DIR) / f"{origin}_출발"
    target = out / "발주일_예측.csv"
    if target.exists() and not force:
        raise FileExistsError(f"{target} 가 이미 있습니다 (동결). 덮어쓰려면 force=True.")
    book = re.load_book()
    e = re.Engine(book=book, model=None, counts={})
    f, res, _ = run_origin(L, origin, months, Params(lumps="round"), None, book)
    od = month_end(origin)
    fac = po_factors(L, book, origin)
    sched = pipeline(book, fac, od)
    sup = {k[0]: g["거래처"].iloc[-1] for k, g in book.by_item.items()}
    unit = {k[0]: g["발주단위"].iloc[-1] for k, g in book.by_item.items()}

    def day_fn(key, arrival):
        sch = e.schedule(sup[key], arrival - timedelta(days=1)) if key in sup else None
        if sch is None:
            return None
        return order_date_for(arrival, sch[0], sch[1], sc.is_closed, e.next_open)

    t = orders_from_receipts(res.receipts, sched, fac, od, day_fn)
    t["거래처"], t["발주단위"] = t["품목코드"].map(sup), t["품목코드"].map(unit)
    t = t.join(L.meta[["품명", "규격"]], on="품목코드").sort_values(["발주일", "거래처", "품명"])
    out.mkdir(parents=True, exist_ok=True)
    t[["발주일", "입고예정일", "품목코드", "품명", "규격", "거래처", "수량_발주단위", "발주단위", "수량_수불부"]].to_csv(target, index=False, encoding="utf-8-sig")
    return target


def verify_orders(month: str, origin: str | None = None, out_dir: Path | None = None, book=None, tol: int = 1) -> pd.DataFrame:
    """동결한 발주일 예측과 그 달의 실제 구매청구를 견준다 (품목별 발주일이 같은 날 / ±tol 일 안에 맞았나). 구매청구 자료가 그 달을 덮어야 한다."""
    import reorder_engine as re
    origin = origin or add_month(month, -1)
    d = (out_dir or FORECAST_DIR) / f"{origin}_출발" / "발주일_예측.csv"
    if not d.exists():
        raise FileNotFoundError(f"{d} 가 없습니다.")
    book = book or re.load_book()
    plan = pd.read_csv(d, dtype={"품목코드": str})
    plan["발주일"] = pd.to_datetime(plan["발주일"]).dt.date
    plan = plan[[f"{x:%Y-%m}" == month for x in plan["발주일"]]]
    if book.orders["청구일자"].max() < month_end(month):
        raise FileNotFoundError(f"구매청구 자료가 {book.orders['청구일자'].max()}까지라 {month} 전체를 비교할 수 없습니다.")
    act = {(k[0], dd) for k, g in book.by_item.items() for dd in g["청구일자"] if f"{dd:%Y-%m}" == month and k[0] in set(plan["품목코드"])}
    pred = set(zip(plan["품목코드"], plan["발주일"]))
    near = lambda a, S, n: any(x[0] == a[0] and abs((a[1] - x[1]).days) <= n for x in S)
    rows = []
    for n in (0, tol):
        p, r = sum(near(x, act, n) for x in pred) / max(1, len(pred)), sum(near(x, pred, n) for x in act) / max(1, len(act))
        rows.append({"허용 오차(일)": n, "예측 발주": len(pred), "실제 발주": len(act), "정밀도": p, "재현율": r, "F1": 2 * p * r / max(1e-9, p + r)})
    R = pd.DataFrame(rows)
    R.to_csv(d.with_name(f"검증_{month}_발주일.csv"), index=False, encoding="utf-8-sig")
    return R


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backtest", action="store_true", help="과거 월말 실사에서 출발해 1~3개월 뒤를 예측하고 실제와 비교")
    ap.add_argument("--forecast", nargs="?", const="", metavar="출발월", help="최근 월말 실사(또는 지정한 달)에서 출발한 예측을 동결 저장")
    ap.add_argument("--months", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", metavar="YYYY-MM", help="동결한 예측과 그 달 실제 수불부를 비교")
    ap.add_argument("--orders", nargs="?", const="", metavar="출발월", help="동결한 예측과 같은 출발에서 발주일 예측을 만들어 저장")
    ap.add_argument("--verify-orders", metavar="YYYY-MM", help="동결한 발주일 예측과 그 달 실제 구매청구를 비교")
    a = ap.parse_args(argv)
    pd.set_option("display.width", 200)
    if a.backtest:
        import reorder_engine as re
        L = load_ledger()
        origins = [m for m in L.months if "2025-07" <= m <= add_month(L.months[-1], -1)]
        B = backtest(L, origins, 3, Params(), None, re.load_book())
        print(B.groupby(["대상", "방법", "h"])[["WAPE_금액", "WAPE_수량", "±30% 이내", "편향_금액"]].mean().round(3).to_string())
        return 0
    if a.forecast is not None:
        out = forecast(a.forecast or None, a.months, force=a.force)
        print(f"저장: {out}")
        return 0
    if a.verify:
        print(verify(a.verify).round(3).to_string(index=False))
        return 0
    if a.orders is not None:
        print(f"저장: {order_plan(a.orders or None, a.months, force=a.force)}")
        return 0
    if a.verify_orders:
        print(verify_orders(a.verify_orders).round(3).to_string(index=False))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
