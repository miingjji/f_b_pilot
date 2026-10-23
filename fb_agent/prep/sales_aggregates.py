"""월별 수불부 `매출입력` 시트(영수증 행 단위)를 집계해 매출 화면이 읽는 표를 만든다:  python -m prep.sales_aggregates

원본은 data/source/수불부/<연도>/<YYYY-MM>.md. 매출 기준은 정리 파일과 같다: 취소구분이 `정상`+`매출취소`인 행의 순매출 (판매및할인 시트와 일치하는 기준).
`주문취소`·`메뉴정정`은 매출로 잡지 않고 취소 내역 표에만 쓴다. 결과는 data/cleaned/매출/ 에 저장한다 (영수증 단위 원본은 수정하지 않는다).

  일자별.csv       날짜, 총매출, 할인, 순매출, 부가세, 객수, 영수증수
  시간대별.csv     날짜, 시, 순매출, 객수, 영수증수 (시 = 영수증 시각의 시)
  메뉴별.csv       날짜, 메뉴명, 대분류명, 수량, 순매출
  메뉴시간별.csv   날짜, 시, 메뉴명, 순매출 (메뉴명은 전 기간 순매출 상위 MENU_KEEP개, 나머지는 '기타')
  결제별.csv       날짜, 결제, 순매출 (복합 결제는 첫 결제수단으로 분류 — 금액이 나뉘어 있지 않음)
  취소.csv         날짜, 시각, 영수증번호, 유형, 금액
"""
import sys
from pathlib import Path

import pandas as pd

from prep import clean_sales
from prep.md_tables import read_sheets

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "cleaned" / "매출"
SALES_KINDS = ("정상", "매출취소")
CANCEL_KINDS = {"매출취소": "매출취소", "주문취소": "주문취소", "메뉴정정": "메뉴취소"}      # 원본 구분 -> 화면 유형
MENU_KEEP = 14


def pay_group(text: str) -> str:
    """'신용카드, 상품권-롯데상품권' 같은 복합 결제는 첫 결제수단으로 분류."""
    first = str(text).split(",")[0].strip()
    if first.startswith("신용카드"):
        return "신용카드"
    if first.startswith("현금"):
        return "현금"
    return "상품권·기타"      # 상품권·외상·결제없음


def month_rows(src: Path) -> pd.DataFrame:
    """한 달 파일의 매출입력 시트를 정제해 날짜·시·결제·영수증 열을 붙인다."""
    raw = read_sheets(src, only=clean_sales.SHEET)[clean_sales.SHEET]
    is_day = raw["매출일자"].astype("string").str.fullmatch(r"\d{4}-\d{2}-\d{2}").fillna(False)
    total = raw[~is_day & raw["매출일자"].astype("string").str.replace(" ", "").eq("합계")]       # 일부 달 파일 끝에 붙은 합계 행
    raw = raw[is_day]
    d, _report = clean_sales.clean_sales_detail(raw)
    if len(total):                                                                       # 합계 행과 영수증 행의 합이 같아야 한다
        for c in ("총매출", "순매출", "수량"):
            want, got = float(pd.to_numeric(total.iloc[0][c])), float(d.loc[d["취소구분"].isin(SALES_KINDS), c].sum())     # 정상+매출취소 기준
            if abs(want - got) > 1:
                raise ValueError(f"{src.stem}: 합계 행 {c} {want:,.0f} ≠ 영수증 행 합 {got:,.0f}")
    d["날짜"] = pd.to_datetime(d["매출일자"]).dt.strftime("%Y-%m-%d")
    d["시"] = d["매출시간"].astype(str).str[:2].astype(int)
    d["결제"] = d["결제수단"].map(pay_group)
    d["영수증"] = d["날짜"].str[5:].str.replace("-", "") + d["포스번호"].astype(str) + "-" + d["영수증번호"].astype(str).str.zfill(4)
    return d


def aggregate_month(d: pd.DataFrame) -> dict:
    s = d[d["취소구분"].isin(SALES_KINDS)]
    first = s.drop_duplicates(["날짜", "포스번호", "영수증번호"])               # 객수는 영수증 첫 행에 한 번만 센다
    daily = s.groupby("날짜").agg(총매출=("총매출", "sum"), 할인=("할인", "sum"), 순매출=("순매출", "sum"), 부가세=("부가세", "sum"))
    daily["객수"] = first.groupby("날짜")["객수"].sum()
    daily["영수증수"] = first.groupby("날짜").size()
    hourly = s.groupby(["날짜", "시"]).agg(순매출=("순매출", "sum")).join(
        first.groupby(["날짜", "시"]).agg(객수=("객수", "sum"), 영수증수=("영수증번호", "size")), how="left").fillna(0)
    menu = s.groupby(["날짜", "메뉴명", "대분류명"]).agg(수량=("수량", "sum"), 순매출=("순매출", "sum")).reset_index()
    pay = s.groupby(["날짜", "결제"]).agg(순매출=("순매출", "sum")).reset_index()
    c = d[d["취소구분"].isin(CANCEL_KINDS)]
    cancel = pd.DataFrame(columns=["날짜", "시각", "영수증번호", "유형", "금액"])
    if len(c):
        c = c.assign(유형=c["취소구분"].map(CANCEL_KINDS))
        cancel = c.groupby(["영수증", "유형"]).agg(날짜=("날짜", "first"), 시각=("매출시간", "min"), 금액=("순매출", lambda x: int(abs(x.sum())))).reset_index()
        cancel["시각"] = cancel["시각"].str[:5]
        cancel = cancel.rename(columns={"영수증": "영수증번호"})[["날짜", "시각", "영수증번호", "유형", "금액"]]
    menu_hour = s.groupby(["날짜", "시", "메뉴명"]).agg(순매출=("순매출", "sum")).reset_index()
    return {"일자별": daily.reset_index(), "시간대별": hourly.reset_index(), "메뉴별": menu, "메뉴시간별": menu_hour, "결제별": pay, "취소": cancel}


def build(src_dir: Path | None = None) -> tuple[dict, list]:
    src_dir = src_dir or DATA / "source" / "수불부"
    parts: dict[str, list] = {}
    months = []
    for f in sorted(src_dir.glob("20??/20??-??.md")):
        for name, df in aggregate_month(month_rows(f)).items():
            parts.setdefault(name, []).append(df)
        months.append(f.stem)
        print(f"  {f.stem} 집계")
    tables = {k: pd.concat(v, ignore_index=True) for k, v in parts.items()}
    keep = list(tables["메뉴별"].groupby("메뉴명")["순매출"].sum().sort_values(ascending=False).index[:MENU_KEEP])
    mh = tables["메뉴시간별"]
    mh["메뉴명"] = mh["메뉴명"].where(mh["메뉴명"].isin(keep), "기타")
    tables["메뉴시간별"] = mh.groupby(["날짜", "시", "메뉴명"], as_index=False)["순매출"].sum()
    return tables, months


def main(argv=None) -> int:
    tables, months = build()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")
        print(f"■ {name}: {len(df):,}행")
    d = tables["일자별"]
    print(f"{len(months)}개월, {d['날짜'].min()} ~ {d['날짜'].max()}, 영업일 {len(d)}일, 순매출 합 {int(d['순매출'].sum()):,}원\n저장 위치: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
