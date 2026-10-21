"""월별 수불부와 POS 리포트를 대조한다:  python -m prep.ledger_reconcile

수불부 정제본(data/cleaned/수불부/<YYYY-MM>/)과 POS 정제본(data/cleaned/<연도>/)에서 월마다 같은 항목을 나란히 놓고,
data/cleaned/수불부/POS_대조_월별.csv 에 저장한다. 어느 쪽 값이 맞는지는 판단하지 않고 차이만 보여준다.

  - 수불 마감 항등식: 기초 + 입고 − 출고 = 기말
  - 이월: 전월 기말재고 = 당월 기초재고
  - 매출·객수: 수불요약 매출지표 vs POS 정산_월별 (순매출·객수)
  - 입고: 수불요약 입고_구매(원재료+저장품 계정) vs POS 입고_정제 (공급가 · 합계 둘 다)
"""
import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data" / "cleaned"
LEDGER = DATA / "수불부"


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def ledger_month(ym: str) -> dict:
    d = LEDGER / ym
    close = _read(d / "수불요약_수불마감_정제.csv").set_index("계정명")
    kpi = _read(d / "수불요약_매출지표_정제.csv").set_index("지표")["값"]
    loss = _read(d / "수불요약_로스요약_정제.csv").set_index("구분")
    total = close.loc["합계"]
    outflow = total[[c for c in close.columns if c.startswith("출고_")]].sum()
    return {
        "월": ym,
        "수불_기초재고": total["기초재고"], "수불_입고_구매": total["입고_구매"], "수불_출고": outflow, "수불_기말재고": total["기말재고"],
        "수불_원재료_입고": close.loc["원재료", "입고_구매"], "수불_폐기손실": total["출고_재고자산폐기손실"],
        "수불_매출": kpi["매출"], "수불_객수": kpi["객수"],
        "수불_로스금액": loss.loc["합계", "로스금액"], "수불_로스율": loss.loc["합계", "로스율"],
    }


def pos_months() -> pd.DataFrame:
    rows = []
    for year in sorted(p.name for p in DATA.iterdir() if p.is_dir() and p.name.isdigit()):
        sales = _read(DATA / year / "정산_월별_정제.csv")[["월", "순매출", "객수"]].rename(columns={"순매출": "POS_순매출", "객수": "POS_객수"})
        daily = _read(DATA / year / "매출일자별_정제.csv")
        daily["월"] = daily["매출일자"].str[:7]
        sales = sales.merge(daily.groupby("월", as_index=False)["순매출"].sum().rename(columns={"순매출": "POS_일자별_순매출"}), on="월")
        rec = _read(DATA / year / "입고_정제.csv")
        rec["월"] = rec["입고월"].astype(str).str[:4] + "-" + rec["입고월"].astype(str).str[4:]
        keep = rec[rec["입고유형"] != "수량0"]
        buy = keep.groupby("월", as_index=False).agg(POS_입고_공급가=("입고금액", "sum"), POS_입고_합계=("입고합계", "sum"))
        rows.append(sales.merge(buy, on="월", how="left"))
    return pd.concat(rows, ignore_index=True)


def main() -> int:
    months = sorted(p.name for p in LEDGER.iterdir() if p.is_dir())
    led = pd.DataFrame([ledger_month(m) for m in months])
    out = led.merge(pos_months(), on="월", how="left")
    out["수불_항등식_차이"] = out["수불_기초재고"] + out["수불_입고_구매"] - out["수불_출고"] - out["수불_기말재고"]
    out["이월_차이(전월기말-당월기초)"] = out["수불_기말재고"].shift(1) - out["수불_기초재고"]
    out["매출_차이(수불-POS)"] = out["수불_매출"] - out["POS_순매출"]
    out["객수_차이(수불-POS)"] = out["수불_객수"] - out["POS_객수"]
    out["입고_차이(수불-POS공급가)"] = out["수불_입고_구매"] - out["POS_입고_공급가"]
    out["입고_비율(수불/POS공급가)"] = out["수불_입고_구매"] / out["POS_입고_공급가"]
    path = LEDGER / "POS_대조_월별.csv"
    out.round(4).to_csv(path, index=False, encoding="utf-8-sig")
    print(f"저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
