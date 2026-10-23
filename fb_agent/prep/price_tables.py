"""월별 단가표와 가격지수를 만든다:  python -m prep.price_tables

가격 변동을 수량 예측과 분리해서 보기 위한 표다 (판매가 인상은 수량 기준으로 보면 영향이 적고, 금액 비교에서만 보정이 필요하다).
  매입단가_월별.csv   품목(RMS 코드 + 입고단위)마다 월 입고단가(수량 가중 중앙값에 가까운 최빈값)와 입고수량. 원본: POS 입고_정제.csv
  메뉴단가_월별.csv   메뉴코드마다 월 판매 단가(최빈값)와 판매수량. 원본: 수불부 `매출입력` 시트 (정상 거래, 단가 > 0)
  가격변동_매입.csv / 가격변동_메뉴.csv   단가가 바뀐 달, 이전·이후 단가, 변동률, 다음 달에도 유지됐는지
  가격지수_월별.csv   매입·메뉴 연쇄 라스파이레스 지수 (직전 달에도 있던 품목만, 직전 달 수량 가중). 2024-01 = 100
결과는 data/cleaned/단가/ 에 저장한다. 원본은 수정하지 않는다.
"""
import sys
from pathlib import Path

import pandas as pd

from prep import clean_sales
from prep.md_tables import read_sheets

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "cleaned" / "단가"
CHANGE_MIN = 0.005          # 이 비율 이상 바뀌면 가격 변동으로 본다
BASE = "2024-01"


def _mode_price(g: pd.DataFrame, price: str, qty: str) -> float:
    """수량을 가중치로 한 최빈 단가 (같은 월에 단가가 둘 이상일 때 가장 많이 팔린 값)."""
    return float(g.groupby(price)[qty].sum().idxmax())


def purchase_prices() -> pd.DataFrame:
    parts = [pd.read_csv(f, encoding="utf-8-sig", dtype={"품목코드_RMS": str}) for f in sorted((DATA / "cleaned").glob("20*/입고_정제.csv"))]
    t = pd.concat(parts, ignore_index=True)
    t = t[(t["입고유형"] == "입고") & (t["입고단가"] > 0) & (t["입고수량"] > 0)].copy()
    t["월"] = t["입고일자"].str[:7]
    rows = []
    for (m, code, unit), g in t.groupby(["월", "품목코드_RMS", "입고단위"]):
        rows.append({"월": m, "품목코드_RMS": code, "입고단위": unit, "품명": g["품명"].iloc[-1], "규격": g["규격"].iloc[-1],
                     "입고단가": _mode_price(g, "입고단가", "입고수량"), "입고수량": float(g["입고수량"].sum())})
    return pd.DataFrame(rows).sort_values(["품목코드_RMS", "입고단위", "월"]).reset_index(drop=True)


def menu_prices() -> pd.DataFrame:
    rows = []
    for f in sorted((DATA / "source" / "수불부").glob("20*/20*.md")):
        ym = f.stem
        raw = read_sheets(f, only=clean_sales.SHEET)[clean_sales.SHEET]
        d = raw[["메뉴코드", "메뉴명", "단가", "수량", "취소구분"]].copy()
        d["단가"] = pd.to_numeric(d["단가"], errors="coerce")
        d["수량"] = pd.to_numeric(d["수량"], errors="coerce")
        d = d[d["취소구분"].fillna("정상").eq("정상") & d["메뉴코드"].notna() & (d["단가"] > 0) & (d["수량"] > 0)].copy()
        d["메뉴코드"] = d["메뉴코드"].astype(str).str.replace(r"\.0$", "", regex=True)
        for code, g in d.groupby("메뉴코드"):
            rows.append({"월": ym, "메뉴코드": code, "메뉴명": g["메뉴명"].iloc[-1], "판매단가": _mode_price(g, "단가", "수량"), "판매수량": float(g["수량"].sum())})
        print(f"  메뉴 단가 {ym}: {d['메뉴코드'].nunique()}개 메뉴")
    return pd.DataFrame(rows).sort_values(["메뉴코드", "월"]).reset_index(drop=True)


def changes(t: pd.DataFrame, key: list[str], price: str) -> pd.DataFrame:
    """연속으로 관측된 두 달 사이에 단가가 바뀐 경우. 다음 달 값이 새 단가와 같으면 '유지'로 표시."""
    out = []
    for k, g in t.groupby(key):
        g = g.sort_values("월").reset_index(drop=True)
        for i in range(1, len(g)):
            a, b = g.loc[i - 1, price], g.loc[i, price]
            if a > 0 and abs(b / a - 1) >= CHANGE_MIN:
                nxt = g.loc[i + 1, price] if i + 1 < len(g) else None
                out.append({**dict(zip(key, k if isinstance(k, tuple) else (k,))), "이름": g.loc[i, "품명" if "품명" in g else "메뉴명"],
                            "이전월": g.loc[i - 1, "월"], "변경월": g.loc[i, "월"], "이전단가": a, "이후단가": b, "변동률": round(b / a - 1, 4),
                            "다음달_유지": "마지막 달" if nxt is None else ("유지" if nxt == b else "되돌아감·재변경")})
    return pd.DataFrame(out)


def chained_index(t: pd.DataFrame, key: list[str], price: str, qty: str) -> pd.Series:
    """직전 달에도 있던 품목만으로 월간 변화율(직전 달 수량 가중)을 구해 이어 붙인다. BASE 달 = 100."""
    months = sorted(t["월"].unique())
    piv_p = t.pivot_table(index=key, columns="월", values=price)
    piv_q = t.pivot_table(index=key, columns="월", values=qty)
    idx = {months[0]: 100.0}
    for prev, cur in zip(months, months[1:]):
        both = piv_p[[prev, cur]].dropna().index
        w = piv_q.loc[both, prev]
        link = (piv_p.loc[both, cur] * w).sum() / (piv_p.loc[both, prev] * w).sum() if len(both) and w.sum() > 0 else 1.0
        idx[cur] = idx[prev] * link
    s = pd.Series(idx)
    return (s / s[BASE] * 100).round(2) if BASE in s.index else s.round(2)


def main(argv=None) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    buy = purchase_prices()
    buy.to_csv(OUT / "매입단가_월별.csv", index=False, encoding="utf-8-sig")
    print(f"매입단가: {len(buy):,}행, 품목 {buy[['품목코드_RMS', '입고단위']].drop_duplicates().shape[0]}개, {buy['월'].min()}~{buy['월'].max()}")
    menu = menu_prices()
    menu.to_csv(OUT / "메뉴단가_월별.csv", index=False, encoding="utf-8-sig")
    print(f"메뉴단가: {len(menu):,}행, 메뉴 {menu['메뉴코드'].nunique()}개, {menu['월'].min()}~{menu['월'].max()}")
    cb = changes(buy, ["품목코드_RMS", "입고단위"], "입고단가")
    cm = changes(menu, ["메뉴코드"], "판매단가")
    cb.to_csv(OUT / "가격변동_매입.csv", index=False, encoding="utf-8-sig")
    cm.to_csv(OUT / "가격변동_메뉴.csv", index=False, encoding="utf-8-sig")
    idx = pd.DataFrame({"매입지수": chained_index(buy, ["품목코드_RMS", "입고단위"], "입고단가", "입고수량"),
                        "메뉴지수": chained_index(menu, ["메뉴코드"], "판매단가", "판매수량")})
    idx.index.name = "월"
    idx.to_csv(OUT / "가격지수_월별.csv", encoding="utf-8-sig")
    print(f"가격 변동: 매입 {len(cb)}건, 메뉴 {len(cm)}건\n저장 위치: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
