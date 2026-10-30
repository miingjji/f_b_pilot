"""'일자기준 메뉴매출조회' 하루치 파일들을 한 표로 정제한다:  python -m prep.menu_sales_daily [--src 폴더] [--out 폴더] [--first 2026-10-01] [--last 2026-10-29]

파일 하나 = 하루(조회기간 시작=끝). 메뉴 행(메뉴코드 8자리) + 소계 행 + 합계 행으로 되어 있다.
기존 영수증 기반 메뉴 집계(data/cleaned/매출/메뉴별.csv)와 같은 의미다 — 단가 0 행(세트 구성품·옵션)도 들어 있고 취소는 순수량으로 합쳐져 있다.
조회기간이 하루가 아닌 파일은 쓰지 않고 이름을 알린다. 메뉴 행 합이 합계 행과 다르면 오류로 멈춘다. 원본은 수정하지 않는다.
"""
import argparse
import re
from pathlib import Path

import pandas as pd

from prep.data_2026 import number, read_rows
from prep.md_tables import _unescape

SRC = Path(__file__).resolve().parent.parent / "data" / "source" / "2026" / "일자기준_메뉴매출_26.10"
OUT = Path(__file__).resolve().parent.parent / "data" / "cleaned" / "2026"
PERIOD = re.compile(r"조회기간:\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
MONEY = ["단가", "매출수량", "총매출", "실매출", "순매출", "부가세", "할인"]
RENAME = {"매출수량": "수량", "대분류": "대분류명", "중분류": "중분류명", "소분류": "소분류명"}


def parse_day(path):
    """(날짜 또는 None, 메뉴 행 표, 합계 행 dict). 조회기간이 하루가 아니면 날짜 None."""
    text = Path(path).read_text(encoding="utf-8")
    m = PERIOD.search(text)
    if not m or m.group(1) != m.group(2):
        return None, None, None
    rows = read_rows(path)
    hdr = next(i for i, r in enumerate(rows) if r and r[0] == "No.")
    cols = rows[hdr]
    menu = [r for r in rows[hdr + 1:] if len(r) == len(cols) and r[5] and re.fullmatch(r"\d{8}", r[5])]
    t = pd.DataFrame(menu, columns=cols)
    t[["대분류", "중분류", "소분류"]] = t[["대분류", "중분류", "소분류"]].ffill()      # 병합 셀: 같은 분류가 이어지는 행은 칸이 비어 있다
    for c in MONEY:
        t[c] = number(t[c])
    t["메뉴명"] = t["메뉴명"].map(_unescape)
    total = next(r for r in rows[hdr + 1:] if "합계" in r[:3])           # 첫 칸(No.)이 비어 있다
    cells = [c for c in total[total.index("합계") + 1:] if c is not None]
    nums = [number(pd.Series([c])).iloc[0] for c in cells[:6]]
    return m.group(1), t, dict(zip(["수량", "총매출", "실매출", "순매출", "부가세", "할인"], nums))


def clean(src: Path, first: str | None = None, last: str | None = None):
    """폴더의 하루치 파일 -> (메뉴별 표, 일 합계 표, 안내 목록)."""
    tables, totals, notes = [], [], []
    for path in sorted(Path(src).glob("*.md")):
        day, t, total = parse_day(path)
        if day is None:
            notes.append(f"조회기간이 하루가 아니라 제외: {path.name}")
            continue
        if (first and day < first) or (last and day > last):
            notes.append(f"범위 밖이라 제외: {day} ({path.name})")
            continue
        for k, c in {"수량": "매출수량", "총매출": "총매출", "실매출": "실매출", "순매출": "순매출", "부가세": "부가세", "할인": "할인"}.items():
            if abs(float(t[c].sum()) - total[k]) > 0.5:
                raise ValueError(f"{day}: 메뉴 행의 {c} 합 {t[c].sum():,.0f} ≠ 합계 행 {total[k]:,.0f} ({path.name})")
        t = t.rename(columns=RENAME)
        t.insert(0, "날짜", day)
        tables.append(t[["날짜", "대분류명", "중분류명", "소분류명", "메뉴코드", "메뉴명", "단가", "수량", "총매출", "실매출", "순매출", "부가세", "할인"]])
        totals.append({"날짜": day, **total})
    if not tables:
        raise ValueError("하루치 파일을 하나도 읽지 못했습니다.")
    menu = pd.concat(tables, ignore_index=True)
    daily = pd.DataFrame(totals)
    if daily["날짜"].duplicated().any():
        raise ValueError(f"같은 날짜 파일이 둘 이상입니다: {sorted(daily.loc[daily['날짜'].duplicated(), '날짜'])}")
    days = pd.date_range(daily["날짜"].min(), daily["날짜"].max())
    missing = [f"{d:%Y-%m-%d}({'월화수목금토일'[d.weekday()]})" for d in days if f"{d:%Y-%m-%d}" not in set(daily["날짜"])]
    if missing:
        notes.append("파일이 없는 날: " + ", ".join(missing))
    return menu.sort_values(["날짜", "메뉴코드"]).reset_index(drop=True), daily.sort_values("날짜").reset_index(drop=True), notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--first", default=None)
    ap.add_argument("--last", default=None)
    a = ap.parse_args(argv)
    menu, daily, notes = clean(Path(a.src), a.first, a.last)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    menu.to_csv(out / "메뉴매출_일자기준_정제.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(out / "메뉴매출_일자기준_일합계.csv", index=False, encoding="utf-8-sig")
    print(f"{daily['날짜'].min()} ~ {daily['날짜'].max()}: {len(daily)}일, 메뉴 행 {len(menu):,}개, 수량 {int(menu['수량'].sum()):,}, 순매출 {int(menu['순매출'].sum()):,}")
    for n in notes:
        print("  ·", n)
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
