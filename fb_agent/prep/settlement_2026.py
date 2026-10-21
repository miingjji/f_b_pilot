"""2026-01~09 월별 정산레포트(수원점)를 정제한다:  python -m prep.settlement_2026 [--year 2026|2025]

원본은 POS 정산레포트 엑셀을 마크다운 표로 옮긴 월별 파일(`정산레포트_YYYY-MM.md`)이다. 한 표에 여러 구역이 좌우로 나란히 있다.
쓰는 구역: 매출정산내역(영수증건수·매출·결제수단별 금액), 시간대별 판매내역(객수·실매출), 할인 상세내역.
결과: 정산_월별_정제.csv, 정산_시간대별_정제.csv, 정산_할인상세_정제.csv, 정산_점검결과.csv. 원본은 수정하지 않는다.
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from prep.blocks import make_check
from prep.data_2026 import number, read_rows

PERIOD = re.compile(r"조회기간 : (\d{4}-\d{2})-01 ~ (\d{4}-\d{2}-\d{2})")
BAND = re.compile(r"^(\d{2}):00:00 ~ (\d{2}):59:59$")
MONEY = ["영수증건수", "총매출", "할인", "실매출", "순매출", "부가세", "신용카드", "현금", "상품권", "외상", "포인트", "기타결제"]


def find(rows, text, col=0):
    return next(i for i, r in enumerate(rows) if len(r) > col and r[col] and text in r[col])


def clean_month(rows):
    month = next(PERIOD.search(r[0]).group(1) for r in rows if r[0] and PERIOD.search(r[0]))
    head = find(rows, "매출정산내역") + 1
    vals = dict(zip(rows[head], rows[head + 1]))
    m = {"월": month, **{k: int(number(pd.Series([vals[k]])).iloc[0]) for k in MONEY}}

    bands = []
    for r in rows:
        if len(r) > 9 and r[6] and BAND.match(r[6]):
            bands.append({"월": month, "시작시": int(BAND.match(r[6]).group(1)), "끝시": int(BAND.match(r[6]).group(2)),
                          "객수": int(number(pd.Series([r[7]])).iloc[0]), "실매출": int(number(pd.Series([r[8]])).iloc[0])})
    total = next(r for r in rows if len(r) > 8 and r[5] == "합계" and r[7])
    m["객수"] = int(number(pd.Series([total[7]])).iloc[0])
    m["시간대_실매출합"] = int(number(pd.Series([total[8]])).iloc[0])

    a, b = find(rows, "할인 상세내역") + 2, find(rows, "매출할인 합계")
    disc = [{"월": month, "할인구분": r[1], "할인건수": int(number(pd.Series([r[2]])).iloc[0]), "할인금액": int(number(pd.Series([r[3]])).iloc[0])}
            for r in rows[a:b] if r[0] and r[0].isdigit()]
    dtotal = rows[b]
    m["할인건수합"] = int(number(pd.Series([dtotal[2]])).iloc[0])
    m["할인상세합"] = sum(x["할인금액"] for x in disc)
    m["할인표_합계"] = int(number(pd.Series([dtotal[3]])).iloc[0])
    return m, bands, disc


def main(argv=None) -> int:
    data = Path(__file__).resolve().parent.parent / "data"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--src", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    a.src = a.src or str(data / "source" / str(a.year))
    a.out = a.out or str(data / "cleaned" / str(a.year))
    out = Path(a.out)
    months, bands, discs = [], [], []
    files = sorted(Path(a.src).glob("정산레포트_*.md"))
    for f in files:
        m, b, d = clean_month(read_rows(f))
        months.append(m), bands.extend(b), discs.extend(d)
    mt = pd.DataFrame(months)

    daily = pd.read_csv(out / "매출일자별_정제.csv")
    daily["월"] = daily["매출일자"].str[:7]
    dm = daily.groupby("월")[["총매출", "실매출", "순매출", "영수증수"]].sum()
    expected = sorted(daily["월"].unique())          # 일자별 매출 파일이 덮는 달
    checks = [make_check("정산레포트 파일 수 = 일자별 매출의 월 수", len(expected), len(files)),
              make_check(f"월 목록 = {expected[0]} ~ {expected[-1]}", len(expected), int((mt["월"].tolist() == expected) * len(expected)))]
    for c, d in (("총매출", "총매출"), ("실매출", "실매출"), ("순매출", "순매출"), ("영수증건수", "영수증수")):
        checks.append(make_check(f"월별 {c} = 일자별 매출 파일의 월 합계 (불일치 월 수)", 0, int((mt.set_index("월")[c] - dm[d]).abs().gt(1).sum()), note=(c == "순매출")))
    checks += [
        make_check("총매출 + 할인 = 실매출 (위반 월 수)", 0, int(((mt["총매출"] + mt["할인"] - mt["실매출"]).abs() > 0).sum())),
        make_check("결제수단 6종 합 = 실매출 (위반 월 수)", 0, int(((mt[["신용카드", "현금", "상품권", "외상", "포인트", "기타결제"]].sum(axis=1) - mt["실매출"]).abs() > 0).sum())),
        make_check("시간대 실매출 합 = 실매출 (위반 월 수)", 0, int((mt["시간대_실매출합"] != mt["실매출"]).sum())),
        make_check("시간대별 객수 합 = 합계 행 (위반 월 수)", 0, int((pd.DataFrame(bands).groupby("월")["객수"].sum() != mt.set_index("월")["객수"]).sum())),
        make_check("할인 상세 합 = 매출할인 합계 (위반 월 수)", 0, int((mt["할인상세합"] != mt["할인표_합계"]).sum())),
        make_check("정산 할인 = 할인표 합계 (위반 월 수)", 0, int((mt["할인"] != mt["할인표_합계"]).sum()), note=True),   # 4월 13,050원·5월 54,000원: 원본 할인표가 정산 할인보다 적다

    ]
    mt = mt.drop(columns=["시간대_실매출합", "할인건수합", "할인상세합", "할인표_합계"])
    mt.to_csv(out / "정산_월별_정제.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(bands).to_csv(out / "정산_시간대별_정제.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(discs).to_csv(out / "정산_할인상세_정제.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(checks).to_csv(out / "정산_점검결과.csv", index=False, encoding="utf-8-sig")
    bad = [c for c in checks if not c["ok"]]
    print(f"정산 월별 {len(mt)}행, 시간대 {len(bands)}행, 할인상세 {len(discs)}행 | 점검 {len(checks) - len(bad)}/{len(checks)} 통과")
    for c in checks:
        print(("  ✓ " if c["ok"] else ("  ⚠ 참고 " if c["참고"] else "  ✗ ")) + f"{c['항목']}: 기대 {c['기대']} / 실제 {c['실제']}")
    return 1 if [c for c in bad if not c["참고"]] else 0


if __name__ == "__main__":
    sys.exit(main())
