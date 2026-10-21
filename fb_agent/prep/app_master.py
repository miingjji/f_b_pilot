"""실제 데이터 기반 앱 마스터(data/real/items.csv, suppliers.csv) 만들기.

    python -m prep.app_master [--src data/source/수불부/2026/2026-09.md] [--out data/real]   (기본: 가장 최근 달의 수불부)
    FB_MASTER=real streamlit run app.py        # 이 마스터로 앱 실행

정리된 업체·품목 표(prep.organize)를 앱의 마스터 형식으로 바꾼다. 파일에 없는 값은 가상으로 채우고, 출처 열을 남긴다.

  일 소비량   ① 표준사용량(g) 시트의 재료별 합계 ÷ 그 달 일수 (실제 근거)  ② 이번 달 입고량 ÷ 그 달 일수 (입고 기반 추정)
              ③ 재고만 있는 품목은 재고 ÷ 30일 (가상)  ④ 근거가 없으면 0 (소비 없음)
  현재 재고   실사재고. 단, 실사에서 0으로만 잡힌 소모품 중 쓰는 품목은 일 소비량 × 10~30일 (가상)
  안전 재고   일 소비량 × 안전 일수(리드타임의 절반, 올림, 최소 1일) — 정책 값
  발주 요일   가상. 월~토 중 입고일이 일요일이 아닌 요일에서 업체 유형·리드타임에 맞는 개수를 고름
  리드타임    prep.organize 의 적용 리드타임 (아워홈만 실제 태그, 나머지 가상)
"""
import argparse
import calendar
import math
import re
import zlib
from itertools import combinations
from pathlib import Path

import pandas as pd

from master import ITEM_COLUMNS, SUPPLIER_COLUMNS
from prep.blocks import find_row, label
from prep.md_tables import read_sheets
from prep.organize import build_all

SHEET_STD = "표준사용량(g)"
DAYS = 31                                    # 월 일수 기본값 (2025년 12월). 파일 이름이 YYYY-MM 이면 그 달 일수를 쓴다
WEEKDAYS = "월화수목금토"
STOCK_ONLY_COVER_DAYS = 30                   # 재고만 있고 사용 근거가 없는 품목의 가상 소비 (재고가 30일치라고 가정)
SYNTH_STOCK_DAYS = (10, 30)                  # 실사에서 0으로 잡힌 소모품의 가상 재고 일수 범위


# ---------------------------------------------------------------- 정책/가상 값
def safety_days(lead: int) -> int:
    """안전재고 일수: 리드타임의 절반(올림), 최소 1일."""
    return max(1, math.ceil(lead / 2))


def order_weekdays(name: str, lead: int, stype: str, kind: str) -> str:
    """가상 발주 요일. 월~토 중 입고일(발주일+리드타임)이 일요일이 아닌 날만 쓰고, 이름으로 값을 고정한다."""
    valid = [d for d in range(6) if (d + lead) % 7 != 6]
    if stype == "센트럴키친(CK)":
        k = 6
    elif stype == "온라인 구매처":
        k = 5
    elif kind == "식재료" and lead <= 1:
        k = 3
    elif lead <= 3:
        k = 2
    else:
        k = 1
    k = min(k, len(valid))

    def spread(c):                                           # 요일이 고르게 퍼진 조합일수록 좋음 (가장 가까운 두 요일 간격이 큼)
        return min((b - a for a, b in zip(c, c[1:])), default=99)

    combos = sorted(combinations(valid, k), key=lambda c: (-spread(c), c))[:3]
    pick = combos[zlib.crc32(name.encode("utf-8")) % len(combos)]
    return "".join(WEEKDAYS[d] for d in pick)


# ---------------------------------------------------------------- 표준사용량 시트
def read_standard_usage(raw: pd.DataFrame) -> pd.DataFrame:
    """'표준사용량(g)' 시트 -> [코드, 이론사용_g]. 재료별 '합계' 열(메뉴별 사용량의 가로 합)을 쓴다."""
    hdr = find_row(raw, 3, "품목코드(RMS)") if raw.shape[1] > 3 else None
    if hdr is None:
        raise ValueError("머리글 행('품목코드(RMS)')을 찾지 못했습니다.")
    total_col = next((j for i in range(hdr) for j in range(raw.shape[1])
                      if pd.notna(raw.iat[i, j]) and label(raw.iat[i, j]) == "합계"), None)
    if total_col is None:
        raise ValueError("'합계' 열을 찾지 못했습니다.")
    body = raw.iloc[hdr + 1:]
    codes = body.iloc[:, 3]
    keep = codes.notna() & (codes.astype(str).map(label) != "없음")
    total = pd.to_numeric(body.loc[keep].iloc[:, total_col], errors="coerce")
    if total.isna().any():
        raise ValueError(f"'합계'가 숫자가 아닌 행이 {int(total.isna().sum())}개 있습니다.")
    out = pd.DataFrame({"코드": codes[keep].astype(str).values, "이론사용_g": total.astype(float).values})
    return out.groupby("코드", as_index=False, sort=False)["이론사용_g"].sum()


# ---------------------------------------------------------------- 변환
def days_in_source(src) -> int:
    """수불부 파일 이름(YYYY-MM.md)의 그 달 일수. 이름에 달이 없으면 DAYS."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", Path(src).stem)
    return calendar.monthrange(int(m[1]), int(m[2]))[1] if m else DAYS


def build_app_master(items: pd.DataFrame, suppliers: pd.DataFrame, std: pd.DataFrame, days: int = DAYS):
    """(품목 표, 업체 표, 요약). 품목 표는 master.py 가 읽는 형식 + 출처 열."""
    std_map = dict(zip(std["코드"], std["이론사용_g"]))
    sup = suppliers.set_index("업체명")
    rows, n_nocode = [], 0
    for _, r in items.iterrows():
        code = r["품목코드_RMS"]
        if code == "없음":
            n_nocode += 1
            code = f"NC-{n_nocode:03d}"
        count_item = float(r["환산단위"]) == 1.0
        unit, pk, ea = ("개", 1.0, 1.0) if count_item else ("g", float(r["환산단위"]), 0.0)
        stock = float(r["실사재고수량"] if count_item else r["실사재고중량_g"])
        recv = float(r["당월입고수량"] if count_item else r["당월입고중량_g"])
        theory = float(std_map.get(r["품목코드_RMS"], 0.0))

        if theory > 0:
            usage, usage_src = theory / days, "표준사용량"
        elif recv > 0:
            usage, usage_src = recv / days, "입고 기반 추정"
        elif stock > 0:
            usage, usage_src = stock / STOCK_ONLY_COVER_DAYS, "가상"
        else:
            usage, usage_src = 0.0, "근거 없음"
        usage = round(usage, 4)

        stock_src = "실사재고"
        if r["품목구분"] == "소모품" and stock == 0 and usage > 0:      # 소모품은 실사에서 0으로만 잡혀 있어 쓰는 품목만 가상 재고
            lo, hi = SYNTH_STOCK_DAYS
            cover = lo + zlib.crc32(code.encode("utf-8")) % (hi - lo + 1)
            stock, stock_src = round(usage * cover, 1), "가상"

        lead = int(r["리드타임_적용_일"])
        default = int(sup.loc[r["발주처"], "리드타임_적용_일"])
        rows.append({
            "품목코드": code, "품목명": r["품명"], "대분류": r["품목구분"], "중분류": r["계정명"], "기본단위": unit,
            "PK당수량": pk, "BOX당PK": 1.0, "EA당수량": ea, "일소비량": usage,
            "안전재고량": round(usage * safety_days(lead), 4), "현재재고량": float(stock),
            "리드타임": lead if lead != default else "", "거래처": r["발주처"],
            "규격": r["규격"], "일소비량_출처": usage_src, "재고_출처": stock_src, "리드타임_출처": r["리드타임_출처"],
            "원거래처": r["원거래처"],
        })
    df = pd.DataFrame(rows)
    dup = df["품목명"].duplicated(keep=False)                       # 이름이 같은 품목은 코드로 구분
    df.loc[dup, "품목명"] = df.loc[dup, "품목명"] + " (" + df.loc[dup, "품목코드"] + ")"
    df = df.sort_values(["대분류", "중분류", "거래처", "품목명"], kind="stable").reset_index(drop=True)

    s_rows = []
    for name, r in sup.iterrows():
        lead = int(r["리드타임_적용_일"])
        s_rows.append({"거래처명": name, "발주요일": order_weekdays(name, lead, r["업체유형"], r["취급구분"]),
                       "기본리드타임": lead, "취급분야": r["취급구분"], "발주요일_출처": "가상", "리드타임_출처": r["리드타임_출처"]})
    sdf = pd.DataFrame(s_rows)
    info = {"items": len(df), "suppliers": len(sdf),
            "일소비량_출처": df["일소비량_출처"].value_counts().to_dict(), "재고_출처": df["재고_출처"].value_counts().to_dict(),
            "리드타임_출처": df["리드타임_출처"].value_counts().to_dict()}
    return df, sdf, info


def build_from_markdown(src):
    sheets = read_sheets(src)
    tables, _ = build_all(src, sheets=sheets)
    return build_app_master(tables["업체별_품목"], tables["업체_마스터"], read_standard_usage(sheets[SHEET_STD]), days_in_source(src))


README = """# 실제 데이터 기반 앱 마스터

`python -m prep.app_master`로 만든 파일입니다. 앱에서 쓰려면 `FB_MASTER=real streamlit run app.py`.

**가상 값이 섞여 있습니다.** 출처 열로 구분하세요.

| 항목 | 실제 근거 | 가상/추정 |
|---|---|---|
| 품목·규격·업체·재고(식재료) | 정리된 실사재고·입고내역 | |
| 일 소비량 | `표준사용량` (표준사용량(g) 시트 합계 ÷ 그 달 일수) | `입고 기반 추정`(입고량 ÷ 그 달 일수), `가상`(재고 ÷ 30일), `근거 없음`(0) |
| 현재 재고 | `실사재고` | 실사에서 0으로 잡힌 소모품 중 쓰는 품목: `가상`(일 소비량 × 10~30일) |
| 안전 재고 | | 정책 값: 일 소비량 × 안전 일수(리드타임의 절반, 올림, 최소 1일) |
| 리드타임 | 아워홈만 품명 태그 | 나머지 `가상` (업체 유형·취급 구분 기준) |
| 발주 요일 | | 전부 `가상` (월~토 중 입고일이 일요일이 아닌 요일) |

소모품의 기본단위는 규격 1개(PK)를 `개`로 센 값입니다 (환산단위 1).
"""


def write_master(items: pd.DataFrame, suppliers: pd.DataFrame, out) -> list[Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    extra_i = [c for c in items.columns if c not in ITEM_COLUMNS]
    extra_s = [c for c in suppliers.columns if c not in SUPPLIER_COLUMNS]
    items[[*ITEM_COLUMNS, *extra_i]].to_csv(out / "items.csv", index=False, encoding="utf-8-sig")
    suppliers[[*SUPPLIER_COLUMNS[:1], "발주요일", "기본리드타임", "취급분야", *extra_s]].to_csv(out / "suppliers.csv", index=False, encoding="utf-8-sig")
    (out / "README.md").write_text(README, encoding="utf-8")
    return [out / "items.csv", out / "suppliers.csv", out / "README.md"]


def main(argv=None) -> int:
    data = Path(__file__).resolve().parent.parent / "data"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    months = sorted((data / "source" / "수불부").glob("20??/20??-??.md"))
    ap.add_argument("--src", default=str(months[-1] if months else data / "f_b_menu_data.md"), help="월별 수불부 (기본: 가장 최근 달)")
    ap.add_argument("--out", default=str(data / "real"))
    a = ap.parse_args(argv)
    items, sup, info = build_from_markdown(a.src)
    write_master(items, sup, a.out)
    print(f"품목 {info['items']:,}개, 업체 {info['suppliers']}곳 -> {a.out}")
    for k in ("일소비량_출처", "재고_출처", "리드타임_출처"):
        print(f"  {k}: {info[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
