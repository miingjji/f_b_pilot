"""등록된 시트를 모두 정제한다:  python -m prep [--src data/f_b_menu_data.md] [--out data/cleaned/수불부/2025/2025-12] [--only 이름 ...]

시트마다 <이름>_정제.csv (표가 여러 개면 <이름>_<표>_정제.csv)와 <이름>_결측치_처리내역.csv 를 만들고,
시트 간 교차 점검 결과를 정제_점검결과.csv 에 남긴다. 원본 마크다운은 수정하지 않는다.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

from prep import clean_sales, sales_sheets, stock_sheets, summary_sheets, waste_sheet
from prep.blocks import make_check
from prep.md_tables import read_sheets


def _sales(raw):
    clean, report = clean_sales.clean_sales_detail(raw)
    money = [c for c in ("총매출", "할인", "실매출", "순매출", "부가세") if c in raw]
    checks = [make_check("행 수 유지", len(raw), len(clean))]
    checks += [make_check(f"{c} 합계 유지", float(pd.to_numeric(raw[c]).sum()), float(clean[c].sum())) for c in money]
    return clean, report, {"dropped": [], "checks": checks, "notes": []}


# (파일 이름, 시트 이름, 정제 함수) — 실행 순서 = 위에서 아래
CLEANERS = [
    ("매출입력", clean_sales.SHEET, _sales),
    ("판매및할인", sales_sheets.SHEET_SALES_SUMMARY, sales_sheets.clean_sales_summary),
    ("실사재고", stock_sheets.SHEET_COUNT, stock_sheets.clean_inventory_count),
    ("입고내역", stock_sheets.SHEET_RECEIVING, stock_sheets.clean_receiving),
    ("수불요약", summary_sheets.SHEET_SUMMARY, summary_sheets.clean_summary),
    ("타_폐기", waste_sheet.SHEET_WASTE, waste_sheet.clean_waste),
]


def cross_checks(results: dict) -> list[dict]:
    """시트 사이의 숫자가 서로 맞는지. 원본 데이터 자체의 차이는 note=True(참고)로 표시한다."""
    out = []
    sales = results.get("매출입력")
    if sales is None:
        return out
    s = sales["tables"][None]
    net, guests, qty = float(s["순매출_합계"].sum()), float(s["객수_합계"].sum()), float(s["수량_합계"].sum())
    ledger = results.get("수불요약")
    if ledger and "매출지표" in ledger["tables"]:
        k = ledger["tables"]["매출지표"].set_index("지표")["값"]
        out.append(make_check("수불요약 객수 = 매출입력 객수_합계 합", k["객수"], guests))
        out.append(make_check("수불요약 매출 = 매출입력 순매출_합계 합 (원본 차이)", k["매출"], net, note=True))
    summ = results.get("판매및할인")
    if summ:
        info = summ["info"]
        out.append(make_check("판매및할인 판매금액(중복행 제외) = 매출입력 순매출_합계 합", info["amount_without_duplicates"], net))
        rec = info["reconcile_rows"].get("매출입력")
        if rec:
            out.append(make_check("판매및할인 대조행(매출입력) 금액 = 순매출_합계 합", rec["금액"], net))
            out.append(make_check("판매및할인 대조행(매출입력) 수량 = 수량_합계 합", rec["수량"], qty))
    return out


def main(argv=None) -> int:
    data = Path(__file__).resolve().parent.parent / "data"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=str(data / "f_b_menu_data.md"))
    ap.add_argument("--out", default=str(data / "cleaned" / "수불부" / "2025" / "2025-12"))
    ap.add_argument("--only", nargs="*", help="정제할 파일 이름만 지정 (예: 실사재고 입고내역)")
    a = ap.parse_args(argv)

    print(f"읽는 중: {a.src}")
    sheets = read_sheets(a.src)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results, all_checks, failed = {}, [], False
    for name, sheet, fn in CLEANERS:
        if a.only and name not in a.only:
            continue
        clean, report, info = fn(sheets[sheet])
        tables = clean if isinstance(clean, dict) else {None: clean}
        for t, df in tables.items():
            df.to_csv(out / (f"{name}_정제.csv" if t is None else f"{name}_{t}_정제.csv"), index=False, encoding="utf-8-sig")
        report.to_csv(out / f"{name}_결측치_처리내역.csv", index=False, encoding="utf-8-sig")
        results[name] = {"tables": tables, "report": report, "info": info}
        bad = [c for c in info["checks"] if not c["ok"] and not c.get("참고")]
        failed |= bool(bad)
        all_checks += [{"시트": name, **c} for c in info["checks"]]
        shape = ", ".join(f"{t or name} {len(df):,}행x{df.shape[1]}열" for t, df in tables.items())
        left = sum(int(df.isna().sum().sum()) for df in tables.values())
        print(f"\n■ {name}: {shape}\n  채운 결측 {int(report['채운 개수'].sum()):,}개 | 남은 결측 {left}개 | 점검 {len(info['checks']) - len(bad)}/{len(info['checks'])} 통과")
        if info["dropped"]:
            print("  삭제한 열:", "; ".join(info["dropped"]))
        for b in bad:
            print(f"  ✗ {b['항목']}: 기대 {b['기대']} / 실제 {b['실제']}")
        dup = info.get("duplicates")
        if dup and dup["rows"]:
            print(f"  ⚠ 상품코드 중복 {dup['rows']}행 (판매금액 {dup['amount']:,}원) — 삭제하지 않고 '중복행'으로 표시함")
        for n in info["notes"][:6]:
            print("  ·", n[:150])
        if len(report):
            print(report.to_string(index=False, max_colwidth=36))

    cross = cross_checks(results)
    if cross:
        print("\n■ 시트 간 교차 점검")
        for c in cross:
            mark = "✓" if c["ok"] else ("⚠ 참고(원본 값 차이)" if c["참고"] else "✗")
            print(f"  {mark} {c['항목']}: {c['기대']:,.2f} vs {c['실제']:,.2f}" + ("" if c["ok"] else f" (차이 {c['기대'] - c['실제']:+,.2f})"))
            failed |= (not c["ok"]) and not c["참고"]
        all_checks += [{"시트": "교차점검", **c} for c in cross]
    pd.DataFrame(all_checks).to_csv(out / "정제_점검결과.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장 위치: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
