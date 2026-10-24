"""실제 데이터 기반 앱 마스터(data/real/items.csv, suppliers.csv) 만들기.

    python -m prep.app_master [--src data/source/수불부/2026/2026-09.md] [--out data/real]   (기본: 가장 최근 달의 수불부)
    FB_MASTER=real streamlit run app.py        # 이 마스터로 앱 실행

정리된 업체·품목 표(prep.organize)를 앱의 마스터 형식으로 바꾼다. 실제 근거가 없는 값은 만들지 않고 비워 두며(앱에서는 '데이터 없음'), 출처 열을 남긴다.

  일 소비량   ① 월별 수불부 최근 12개월 실적: (12개월 입고 + 기초 실사재고 − 기말 실사재고) ÷ 일수
              ② 표준사용량(g) 시트의 재료별 합계 ÷ 그 달 일수  ③ 이번 달 입고량 ÷ 그 달 일수 (입고 기반 추정)  ④ 12개월 동안 입고가 한 번도 없으면 소비 0 (`최근 12개월 입고 없음`)
  현재 재고   실사재고. 쓰는 소모품이 실사에서 0으로만 잡혀 있으면(세지 않은 것) 비움
  안전 재고   일 소비량 × 안전 일수(리드타임 동안 매출이 예측보다 클 위험 95%를 덮는 일수, 1~2일) — 정책 값. 소비량이나 리드타임이 없으면 비움
  발주 요일   구매청구 기록(2024~2026)에서 청구가 가장 많은 요일 (청구 10건 이상인 업체만). 없으면 비움
  리드타임    품명 태그(수불부) → 구매청구 실측 권장 리드타임(청구→입고 일수의 90분위, 10건 이상인 업체) → 비움
"""
import argparse
import calendar
import math
import re
from pathlib import Path

import pandas as pd

from master import ITEM_COLUMNS, SUPPLIER_COLUMNS
from prep.blocks import find_row, label
from prep.md_tables import read_sheets
from prep.organize import build_all

SHEET_STD = "표준사용량(g)"
DAYS = 31                                    # 월 일수 기본값 (2025년 12월). 파일 이름이 YYYY-MM 이면 그 달 일수를 쓴다
WEEKDAYS = "월화수목금토"
NO_DATA = "데이터 없음"
NO_RECENT_RECEIPT = "최근 12개월 입고 없음"
USER_SET = "사용자 지정"
USER_SCHEDULE = Path(__file__).resolve().parent.parent / "data" / "real" / "사용자지정_업체일정.csv"      # 마스터를 다시 만들어도 유지되는 사용자 지정 값
MEASURED = "구매청구 실측"
MEASURED_GRADES = ("높음", "보통")           # 청구 10건 이상인 업체만 실측 값으로 쓴다


# ---------------------------------------------------------------- 정책/가상 값
def safety_days(lead: int) -> int:
    """안전재고 일수: 리드타임 동안의 매출이 예측보다 많을 위험 95%를 덮는 일수(올림, 최소 1일).
    매출 예측(2025-07~2026-09, 예측일 이전 자료만)의 리드타임 L일 구간 초과분 95분위가 L=1 0.45일, 2 0.64, 3 0.73, 5 0.88, 7 1.09일이라 0.35 + 0.1×L 로 근사한다.
    (예전 '리드타임의 절반'은 D+3 에 2일, D+5 에 3일로 필요 이상이었다.)"""
    return max(1, math.ceil(round(0.35 + 0.1 * lead, 6)))


USAGE_MONTHS = 12                            # 일 소비량을 구하는 최근 월 수


def ledger_usage(ledger: Path | None = None, months: int = USAGE_MONTHS) -> dict:
    """월별 수불부 정제본에서 품목별 최근 months 개월 실적 소비량 {RMS 코드: (일 소비 수량, 일 소비 중량(g), 입고한 달 수)}.

    소비 = 기간 입고 + 기초 실사재고(직전 달 말) − 기말 실사재고(마지막 달 말). 재고가 늘어 음수가 되면 입고량만 쓴다. 입고가 없으면 넣지 않는다."""
    ledger = ledger or Path(__file__).resolve().parent.parent / "data" / "cleaned" / "수불부"
    dirs = sorted(p for p in ledger.glob("20??/20??-??") if (p / "입고내역_정제.csv").exists())
    if len(dirs) < months + 1:
        return {}
    start, window = dirs[-months - 1], dirs[-months:]
    days = sum(calendar.monthrange(int(p.name[:4]), int(p.name[5:]))[1] for p in window)
    recv_q, recv_g, n_months = {}, {}, {}
    for p in window:
        d = pd.read_csv(p / "입고내역_정제.csv", encoding="utf-8-sig", dtype={"품목코드_RMS": str}, usecols=["품목코드_RMS", "당월합계_수량", "당월합계_중량_g"])
        d = d[d["품목코드_RMS"] != "없음"].groupby("품목코드_RMS").sum()
        for code, r in d.iterrows():
            recv_q[code] = recv_q.get(code, 0.0) + float(r["당월합계_수량"])
            recv_g[code] = recv_g.get(code, 0.0) + float(r["당월합계_중량_g"])
            n_months[code] = n_months.get(code, 0) + int(r["당월합계_수량"] > 0 or r["당월합계_중량_g"] > 0)

    def stock(p: Path) -> pd.DataFrame:
        t = pd.read_csv(p / "실사재고_정제.csv", encoding="utf-8-sig", dtype={"품목코드_RMS": str}, usecols=["품목코드_RMS", "재고실사_수량", "재고실사_중량_g"])
        return t[t["품목코드_RMS"] != "없음"].groupby("품목코드_RMS").sum()

    s0, s1 = stock(start), stock(window[-1])
    out = {}
    for code in recv_q:
        if not n_months[code]:
            continue
        q0, g0 = (float(s0.at[code, "재고실사_수량"]), float(s0.at[code, "재고실사_중량_g"])) if code in s0.index else (0.0, 0.0)
        q1, g1 = (float(s1.at[code, "재고실사_수량"]), float(s1.at[code, "재고실사_중량_g"])) if code in s1.index else (0.0, 0.0)
        use_q, use_g = recv_q[code] + q0 - q1, recv_g[code] + g0 - g1
        use_q, use_g = (use_q if use_q > 0 else recv_q[code]), (use_g if use_g > 0 else recv_g[code])
        out[code] = (use_q / days, use_g / days, n_months[code])
    return out


def _supplier_key(name: str) -> set:
    """'신선농원(구드래)' -> {'신선농원(구드래)', '신선농원', '구드래'}, '(주)가온에프엔비' -> {..., '가온에프엔비'}. 앱의 업체명과 맞춰 보는 용도."""
    base = re.sub(r"^\(주\)|\(주\)$", "", name.strip())
    out = {name.strip(), base}
    m = re.fullmatch(r"(.+?)\((.+)\)", base)
    if m:
        out |= {m[1], m[2]}
    return out


def measured_suppliers(cleaned: Path | None = None) -> dict:
    """구매청구 기록(2024~2026)에서 업체별 실측값 {거래처 표기: (권장 리드타임(일), 발주 요일 문자열)}. 청구 10건 이상인 업체만."""
    from prep.lead_consumption_2026 import lead_by_supplier, received_orders
    cleaned = cleaned or Path(__file__).resolve().parent.parent / "data" / "cleaned"
    files = sorted(cleaned.glob("20*/구매청구_정제.csv"))
    if not files:
        return {}
    req = pd.concat([pd.read_csv(f, encoding="utf-8-sig", dtype=str) for f in files], ignore_index=True)
    o = received_orders(req)
    t = lead_by_supplier(o, req.groupby("거래처").size())
    t = t[t["신뢰도"].isin(MEASURED_GRADES)]
    return {r["거래처"]: (int(r["권장_리드타임_일"]), str(r["주_발주요일"])) for _, r in t.iterrows()}


def match_measured(name: str, measured: dict):
    """앱의 업체명에 맞는 실측값 (리드타임, 발주 요일). 없으면 None."""
    for raw, v in measured.items():
        if name in _supplier_key(raw):
            return v
    return None


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


def user_schedules(path: Path | None = None) -> dict:
    """사용자가 직접 정한 업체 일정 {업체명: (리드타임(일), 발주 요일 문자열)}. 파일: 거래처명, 발주요일, 리드타임(일), 메모."""
    path = path or USER_SCHEDULE
    if not Path(path).exists():
        return {}
    t = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    return {r["거래처명"].strip(): (int(r["리드타임(일)"]), r["발주요일"].strip()) for _, r in t.iterrows() if r["거래처명"].strip()}


def _supplier_lead(name: str, sup: pd.DataFrame, measured: dict, user: dict | None = None):
    """업체의 (리드타임, 출처). 사용자 지정 → 수불부 태그 대표값 → 구매청구 실측 → (None, 데이터 없음)."""
    if user and name in user:
        return user[name][0], USER_SET
    r = sup.loc[name]
    if r["리드타임_출처"] != NO_DATA and pd.notna(r["리드타임_적용_일"]):
        return int(r["리드타임_적용_일"]), r["리드타임_출처"]
    m = match_measured(name, measured)
    return (m[0], MEASURED) if m else (None, NO_DATA)


def _item_lead(r, sup: pd.DataFrame, measured: dict, user: dict | None = None):
    """품목의 (리드타임, 출처). 품명 태그가 있으면 그 값, 아니면 발주처(업체)의 값."""
    if r["리드타임_출처"] == "품명 태그" and pd.notna(r["리드타임_적용_일"]):
        return int(r["리드타임_적용_일"]), "품명 태그"
    return _supplier_lead(r["발주처"], sup, measured, user)


def drop_unusable_suppliers(items: pd.DataFrame, suppliers: pd.DataFrame):
    """리드타임·발주 요일을 모르는 업체와 그 품목을 뺀다(계산된 소비량이 있어도 일정 없이는 발주 시점을 못 정한다).
    (items, suppliers, 삭제한 업체 목록) 을 돌려준다."""
    keep = (suppliers["기본리드타임"] != "") | (suppliers["발주요일"] != "")
    dropped = sorted(suppliers.loc[~keep, "거래처명"])
    return (items[~items["거래처"].isin(dropped)].reset_index(drop=True), suppliers[keep].reset_index(drop=True), dropped)


def build_app_master(items: pd.DataFrame, suppliers: pd.DataFrame, std: pd.DataFrame, days: int = DAYS, measured: dict | None = None, usage_hist: dict | None = None, user: dict | None = None, drop_unscheduled: bool = True):
    """(품목 표, 업체 표, 요약). 품목 표는 master.py 가 읽는 형식 + 출처 열. measured 는 measured_suppliers() 결과, user 는 user_schedules() 결과."""
    measured = measured or {}
    user = user or {}
    usage_hist = usage_hist or {}
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

        hist = usage_hist.get(r["품목코드_RMS"])
        if hist is not None:
            usage, usage_src = hist[0] if count_item else hist[1], f"수불부 {USAGE_MONTHS}개월 실적"
        elif theory > 0:
            usage, usage_src = theory / days, "표준사용량"
        elif recv > 0:
            usage, usage_src = recv / days, "입고 기반 추정"
        else:                                             # 12개월 동안 입고가 한 번도 없다: 소비가 관측되지 않았다 (데이터가 없는 것이 아니라 0)
            usage, usage_src = 0.0, NO_RECENT_RECEIPT
        usage = round(usage, 4)
        months_used = hist[2] if hist is not None else 0

        stock_src = "실사재고"
        if r["품목구분"] == "소모품" and stock == 0 and usage:      # 쓰는 소모품이 실사에서 0으로만 잡혀 있으면 세지 않은 것: 재고를 모른다
            stock, stock_src = None, NO_DATA

        lead, lead_src = _item_lead(r, sup, measured, user)
        s_lead, _s_src = _supplier_lead(r["발주처"], sup, measured, user)
        rows.append({
            "품목코드": code, "품목명": r["품명"], "대분류": r["품목구분"], "중분류": r["계정명"], "기본단위": unit,
            "PK당수량": pk, "BOX당PK": 1.0, "EA당수량": ea, "일소비량": usage,
            "안전재고량": "" if lead is None else round(usage * safety_days(lead), 4),
            "현재재고량": "" if stock is None else float(stock),
            "리드타임": "" if lead is None or lead == s_lead else lead, "거래처": r["발주처"],
            "규격": r["규격"], "일소비량_출처": usage_src, "일소비량_입고월수": months_used, "재고_출처": stock_src, "리드타임_출처": lead_src,
            "원거래처": r["원거래처"],
        })
    df = pd.DataFrame(rows)
    dup = df["품목명"].duplicated(keep=False)                       # 이름이 같은 품목은 코드로 구분
    df.loc[dup, "품목명"] = df.loc[dup, "품목명"] + " (" + df.loc[dup, "품목코드"] + ")"
    df = df.sort_values(["대분류", "중분류", "거래처", "품목명"], kind="stable").reset_index(drop=True)

    s_rows = []
    for name, r in sup.iterrows():
        lead, lead_src = _supplier_lead(name, sup, measured, user)
        m = (user[name][1], USER_SET) if name in user else ((match_measured(name, measured) or (None, ""))[1], MEASURED)
        has_days = bool(m[0])
        s_rows.append({"거래처명": name, "발주요일": m[0] if has_days else "", "기본리드타임": "" if lead is None else lead, "취급분야": r["취급구분"],
                       "발주요일_출처": m[1] if has_days else NO_DATA, "리드타임_출처": lead_src})
    sdf = pd.DataFrame(s_rows)
    df, sdf, dropped = drop_unusable_suppliers(df, sdf) if drop_unscheduled else (df, sdf, [])
    info = {"items": len(df), "suppliers": len(sdf), "삭제된_업체": dropped,
            "일소비량_출처": df["일소비량_출처"].value_counts().to_dict(), "재고_출처": df["재고_출처"].value_counts().to_dict(),
            "리드타임_출처": df["리드타임_출처"].value_counts().to_dict()}
    return df, sdf, info


def build_from_markdown(src, ledger_history: bool = True):
    sheets = read_sheets(src)
    tables, _ = build_all(src, sheets=sheets)
    return build_app_master(tables["업체별_품목"], tables["업체_마스터"], read_standard_usage(sheets[SHEET_STD]), days_in_source(src),
                            measured_suppliers(), ledger_usage() if ledger_history else None, user_schedules())


README = """# 실제 데이터 기반 앱 마스터

`python -m prep.app_master`로 만든 파일입니다. 앱에서 쓰려면 `FB_MASTER=real streamlit run app.py`.

**실제 근거가 없는 값은 만들지 않고 비워 둡니다** (앱에는 '데이터 없음'). 출처 열로 구분하세요.

| 항목 | 실제 근거 | 근거가 없으면 |
|---|---|---|
| 품목·규격·업체·재고(식재료) | 정리된 실사재고·입고내역 | |
| 일 소비량 | `수불부 12개월 실적`(12개월 입고 + 기초 실사재고 − 기말 실사재고) ÷ 일수, 없으면 `표준사용량`, 그다음 `입고 기반 추정` | 12개월 동안 입고가 없으면 소비 0 (`최근 12개월 입고 없음`) |
| 현재 재고 | `실사재고` | 쓰는 소모품이 실사에서 0으로만 잡혀 세지 않은 것이면 비움 |
| 안전 재고 | 정책 값: 일 소비량 × 안전 일수(리드타임 동안 매출이 예측보다 클 위험 95%를 덮는 일수, 1~2일) | 리드타임이 없으면 비움 |
| 리드타임 | `사용자 지정`(`사용자지정_업체일정.csv`), 품명 태그(수불부), `구매청구 실측`(2024~2026 청구→입고 일수 90분위, 청구 10건 이상 업체) | 비움 |
| 발주 요일 | `사용자 지정`, `구매청구 실측`(청구가 가장 많은 요일, 청구 10건 이상 업체) | 비움 (리드타임·발주 요일과 계산된 소비량이 모두 없는 업체는 품목과 함께 뺀다) |

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
