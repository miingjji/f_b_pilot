"""업체별 실측 리드타임과 품목별 소비율(입고량 ÷ 매출) 표를 만든다:  python -m prep.lead_consumption_2026 [--src data/cleaned/2026]

입력은 python -m prep.data_2026 이 만든 구매청구_정제.csv·입고_정제.csv·매출일자별_정제.csv.
  리드타임_업체별.csv   업체마다 청구→입고 일수 분포, 납기 준수율, 주로 발주하는 요일, 권장 리드타임
  리드타임_업체요일별.csv  업체 × 청구 요일별 리드타임 (주말이 끼면 길어지는지)
  소비율_품목별.csv     품목(+입고단위)마다 순매출 100만 원당 입고량. 월별 값과 변동계수, 신뢰도 포함
  리드타임_소비율_점검결과.csv  합계·건수 점검

소비율은 '소비'가 아니라 '입고'로 구한 값이다 (2026년에는 재고 실측이 없다). 재고가 크게 변하지 않는 긴 기간에서만 소비의 근사로 쓴다.
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from prep.blocks import make_check

WEEKDAY = "월화수목금토일"
MIN_ORDERS = {"높음": 30, "보통": 10}          # 업체 신뢰도: 청구 건수 기준
MIN_RECEIPTS = {"높음": 12, "보통": 5}          # 품목 신뢰도: 입고 횟수 기준
PER = 1_000_000                                # 소비율 = 순매출 100만 원당 입고량


def grade(n: int, cuts: dict) -> str:
    return "높음" if n >= cuts["높음"] else "보통" if n >= cuts["보통"] else "낮음"


def received_orders(req: pd.DataFrame) -> pd.DataFrame:
    """입고된 청구를 (청구일자, 청구번호, 입고일자) 한 줄씩으로. 미입고·입고수량0 은 리드타임을 알 수 없어 뺀다."""
    r = req.copy()
    r["입고일"] = pd.to_datetime(r["입고일자"], errors="coerce")
    r = r[r["입고일"].notna() & (r["처리상태"] == "입고")]
    r["청구일"] = pd.to_datetime(r["청구일자"])
    r["납기"] = pd.to_datetime(r["납기일자"])
    o = r.drop_duplicates(["거래처", "청구일자", "청구번호", "입고일자"]).copy()
    o["리드타임"] = (o["입고일"] - o["청구일"]).dt.days
    o["납기일수"] = (o["납기"] - o["청구일"]).dt.days
    o["납기차"] = (o["입고일"] - o["납기"]).dt.days
    o["청구요일"] = o["청구일"].dt.dayofweek
    return o


def lead_by_supplier(o: pd.DataFrame, lines: pd.Series) -> pd.DataFrame:
    rows = []
    for s, g in o.groupby("거래처"):
        lt = g["리드타임"]
        wd = g["청구요일"].value_counts(normalize=True).sort_index()
        mode = lt.mode().iloc[0]
        rows.append({
            "거래처": s, "청구건수": len(g), "품목행수": int(lines.get(s, 0)), "신뢰도": grade(len(g), MIN_ORDERS),
            "리드타임_중앙값": float(lt.median()), "리드타임_평균": round(float(lt.mean()), 2), "리드타임_최빈": int(mode),
            "리드타임_p75": float(lt.quantile(.75)), "리드타임_p90": float(lt.quantile(.9)), "리드타임_최대": int(lt.max()),
            "납기설정일수_중앙값": float(g["납기일수"].median()),
            "납기준수율(%)": round(float((g["납기차"] <= 0).mean() * 100), 1),
            "납기_1일이상_지연율(%)": round(float((g["납기차"] >= 1).mean() * 100), 1),
            "주_발주요일": "".join(WEEKDAY[d] for d, v in wd.items() if v >= 0.1),
            "요일분포(%)": " ".join(f"{WEEKDAY[d]}{v * 100:.0f}" for d, v in wd.items()),
            "권장_리드타임_일": int(math.ceil(lt.quantile(.9))),
        })
    return pd.DataFrame(rows).sort_values("청구건수", ascending=False).reset_index(drop=True)


def lead_by_weekday(o: pd.DataFrame) -> pd.DataFrame:
    g = o.groupby(["거래처", "청구요일"])["리드타임"].agg(청구건수="size", 중앙값="median", p90=lambda s: s.quantile(.9), 최대="max").reset_index()
    g["청구요일"] = g["청구요일"].map(lambda d: WEEKDAY[d] + "요일")
    return g.sort_values(["거래처", "청구건수"], ascending=[True, False]).reset_index(drop=True)


def consumption(rcv: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """품목(품목코드+입고단위)별 월별·전체 소비율. 입고유형이 '입고'인 행만 쓴다 (반품·수량0 제외)."""
    d = daily.copy()
    d["월"] = d["매출일자"].str[:7]
    sales = d.groupby("월")["순매출"].sum()
    r = rcv[rcv["입고유형"] == "입고"].copy()
    r["월"] = r["입고일자"].str[:7]
    r = r[r["월"].isin(sales.index)]
    key = ["품목코드_RMS", "품명", "규격", "입고단위"]
    months = list(sales.index)
    qty = r.pivot_table(index=key, columns="월", values="입고수량", aggfunc="sum", fill_value=0.0).reindex(columns=months, fill_value=0.0)
    rate = qty.div(sales / PER, axis=1)                                      # 월별: 입고수량 ÷ (월 순매출 ÷ 100만)
    rcpt = r.groupby(key + ["입고일자"]).size().reset_index().groupby(key).size()
    days = r.groupby(key)["입고일자"].apply(lambda s: sorted(pd.to_datetime(s.unique())))
    gap = days.map(lambda ds: float(np.median(np.diff(ds)) / np.timedelta64(1, "D")) if len(ds) > 1 else np.nan)
    sup = r.groupby(key)["거래처명"].agg(lambda s: s.value_counts().index[0])
    money = r.groupby(key)["입고금액"].sum()
    out = pd.DataFrame({"거래처": sup, "입고횟수": rcpt, "입고월수": (qty > 0).sum(axis=1), "총입고수량": qty.sum(axis=1), "총입고금액": money,
                        "입고간격_중앙값_일": gap})
    out["소비율_전체(100만원당)"] = out["총입고수량"] / (sales.sum() / PER)
    out["소비율_월평균(100만원당)"] = rate.mean(axis=1)
    out["소비율_월별_변동계수"] = rate.std(axis=1, ddof=0) / rate.mean(axis=1)
    out["최근3개월_소비율"] = qty.iloc[:, -3:].sum(axis=1) / (sales.iloc[-3:].sum() / PER)
    out["최근3개월_대비_전체"] = out["최근3개월_소비율"] / out["소비율_전체(100만원당)"]
    out["신뢰도"] = [grade(n, MIN_RECEIPTS) for n in out["입고횟수"]]
    out = pd.concat([out, rate.add_prefix("소비율_").round(4)], axis=1).reset_index()
    num = out.select_dtypes("float").columns
    out[num] = out[num].round(4)
    return out.sort_values("총입고금액", ascending=False).reset_index(drop=True)


def main(argv=None) -> int:
    base = Path(__file__).resolve().parent.parent / "data" / "cleaned" / "2026"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=str(base))
    a = ap.parse_args(argv)
    src = Path(a.src)
    req = pd.read_csv(src / "구매청구_정제.csv", dtype={"품목코드_RMS": str})
    rcv = pd.read_csv(src / "입고_정제.csv", dtype={"품목코드_RMS": str})
    daily = pd.read_csv(src / "매출일자별_정제.csv")

    o = received_orders(req)
    lines = req[(req["처리상태"] == "입고") & pd.to_datetime(req["입고일자"], errors="coerce").notna()].groupby("거래처").size()
    sup, wd = lead_by_supplier(o, lines), lead_by_weekday(o)
    con = consumption(rcv, daily)
    sup.to_csv(src / "리드타임_업체별.csv", index=False, encoding="utf-8-sig")
    wd.to_csv(src / "리드타임_업체요일별.csv", index=False, encoding="utf-8-sig")
    con.to_csv(src / "소비율_품목별.csv", index=False, encoding="utf-8-sig")

    rr = rcv[rcv["입고유형"] == "입고"]
    checks = [
        make_check("입고된 청구 품목행 = 업체별 품목행수 합", int(lines.sum()), int(sup["품목행수"].sum())),
        make_check("미입고·입고수량0 행은 리드타임에서 제외 (제외된 행 수)", int(len(req) - lines.sum()), int((req["처리상태"] != "입고").sum() + ((req["처리상태"] == "입고") & pd.to_datetime(req["입고일자"], errors="coerce").isna()).sum()), note=True),
        make_check("리드타임 음수 건수", 0, int((o["리드타임"] < 0).sum())),
        make_check("총입고수량 합 = 입고 파일(입고유형=입고, 매출 기간 내)", float(rr[rr["입고일자"].str[:7].isin(daily["매출일자"].str[:7])]["입고수량"].sum()), float(con["총입고수량"].sum())),
        make_check("총입고금액 합 = 입고 파일", int(rr[rr["입고일자"].str[:7].isin(daily["매출일자"].str[:7])]["입고금액"].sum()), int(con["총입고금액"].sum())),
        make_check("품목 수 = 입고 파일의 (품목코드, 입고단위) 조합 수", int(rr.drop_duplicates(["품목코드_RMS", "품명", "규격", "입고단위"]).shape[0]), len(con)),
        make_check("입고일 ≠ 납기일인 청구 (참고)", 0, int((o["납기차"] != 0).sum()), note=True),
    ]
    pd.DataFrame(checks).to_csv(src / "리드타임_소비율_점검결과.csv", index=False, encoding="utf-8-sig")
    print(f"리드타임: 업체 {len(sup)}곳 · 청구 {len(o):,}건 | 소비율: 품목 {len(con)}개 | 점검 {sum(c['ok'] for c in checks)}/{len(checks)} 통과")
    for c in checks:
        print(("  ✓ " if c["ok"] else ("  ⚠ 참고 " if c["참고"] else "  ✗ ")) + f"{c['항목']}: 기대 {c['기대']} / 실제 {c['실제']}")
    return 1 if [c for c in checks if not c["ok"] and not c["참고"]] else 0


if __name__ == "__main__":
    sys.exit(main())
