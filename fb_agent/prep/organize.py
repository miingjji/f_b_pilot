"""정제한 시트에서 업체·품목·메뉴·매출 데이터 파일을 정리한다.

    python -m prep.organize [--src data/f_b_menu_data.md] [--out data/organized]

만드는 표
  업체_마스터     업체명, 유형, 취급 구분, 리드타임(품명 태그 기준), 이번 달 입고 합계
  업체별_품목     업체별로 발주 가능한 식재료·소모품 (규격, 단가, 리드타임, 입고 실적, 실사 재고)
  메뉴_마스터     메뉴 코드/이름/분류/판매가/판매수량/매출 (판매및할인 시트와 코드 단위로 대조)
  통합메뉴_매출   '상품명 통일' 기준으로 합친 메뉴 매출
  일자별_매출     일자별 객수·메뉴 판매·매출

기준
  - 메뉴 매출은 '정상' + '매출취소' 행만 더한다. 이 기준이 판매및할인 시트와 코드 단위로 100% 일치한다
    (메뉴정정·주문취소 행은 시트가 제외하는 행).
  - 리드타임은 파일에 열이 없고, 일부 품명 앞의 `[수D1/부D2]` 태그에만 있다. 태그가 없으면 '정보 없음'이다.
"""
import argparse
import re
import zlib
from pathlib import Path

import pandas as pd

from prep import clean_sales, sales_sheets, stock_sheets
from prep.md_tables import read_sheets

SALE_KINDS = ("정상", "매출취소")                 # 시트와 일치하는 매출 집계 기준
EXCLUDED_KINDS = ("메뉴정정", "주문취소")
NO_MENU = "해당없음"
UNKNOWN = "미확인"
NO_INFO = "정보 없음"
FOOD_ACCOUNTS = {"원재료", "반제품"}
ONLINE_SUPPLIERS = {"온라인", "인터넷구매", "인터넷주문"}
SUFFIXES = ("원재료", "저장품")                   # 같은 업체인데 계정명이 붙은 표기 (쿠팡저장품 등)
DAY_COL = re.compile(r"^(\d+)일_(수량|중량_g|금액)$")
LEAD_TAG = re.compile(r"^수D(\d+)/부D(\d+)$")
D_NOTATION = re.compile(r"(?<![A-Za-z])(D-?\d{1,2})(?!\d)")            # (D1), D-2, (D-1,…) — 기계 모델명 D-2000A 는 제외
WEEKDAY = "월화수목금토일"


# ---------------------------------------------------------------- 이름 다루기
def split_tag(name: str) -> tuple[str, str]:
    """품명 앞의 `[태그]`를 떼어낸다. (태그, 정리한 품명). 앞에 붙은 태그만 본다."""
    m = re.match(r"^\[([^\]]*)\]\s*(.*)$", str(name))
    return (m.group(1), m.group(2)) if m else ("", str(name))


def d_notation(name: str) -> str:
    """품명 속의 D 표기(예: '(D1)', 'D-2'). 없으면 ''. 의미(리드타임인지 발주 마감인지)는 확인 전이라 값만 보존한다."""
    m = D_NOTATION.search(name)
    return m.group(1) if m else ""


def lead_times(tag: str):
    """'수D1/부D2' -> (1, 2). 리드타임 태그가 아니면 None (예: '부산', 'CK')."""
    m = LEAD_TAG.match(tag or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def normalize_supplier(name: str, known: set) -> str:
    """'쿠팡저장품' -> '쿠팡'. 접미사를 뗀 이름이 실제로 있는 업체일 때만 합친다."""
    for suf in SUFFIXES:
        if name.endswith(suf) and name[: -len(suf)] in known:
            return name[: -len(suf)]
    return name


def supplier_type(name: str) -> str:
    if name == "CK":
        return "센트럴키친(CK)"
    if name in ONLINE_SUPPLIERS:
        return "온라인 구매처"
    return "업체"


FRESH_WORDS = ("축산", "미트", "수산", "페스카", "농산", "청과", "야채")     # 신선 식재료 업체는 다음 날 입고로 가정
PACKING_WORDS = ("포장", "패키지", "팩", "광고")                           # 포장·제작물은 길게 가정
FOOD_DAYS = (1, 2, 2, 3)
SUPPLY_DAYS = (2, 3, 3, 4, 5)


def synthetic_lead_time(name: str, kind: str, stype: str) -> int:
    """파일에 리드타임이 없는 업체를 위한 **가상 값** (실제 데이터가 아님).

    업체 유형·취급 구분·업체명 키워드로 현실적인 범위에서 정하고, 같은 이름은 항상 같은 값이 나오도록 이름으로 고정한다.
      센트럴키친(CK) D1 | 원거래처(CK 경유) D1 | 온라인 구매 D2~3 | 신선 식재료 D1 | 식재료 D1~3 | 포장·제작물 D4 | 소모품 D2~5
    """
    h = zlib.crc32(name.encode("utf-8"))
    if stype == "센트럴키친(CK)" or stype.startswith("원거래처"):
        return 1
    if stype == "온라인 구매처":
        return (2, 3)[h % 2]
    if kind == "식재료":
        return 1 if any(w in name for w in FRESH_WORDS) else FOOD_DAYS[h % len(FOOD_DAYS)]
    return 4 if any(w in name for w in PACKING_WORDS) else SUPPLY_DAYS[h % len(SUPPLY_DAYS)]


def supplier_lead_map(items: pd.DataFrame) -> dict:
    """업체 -> (적용 리드타임(일), 출처). 품명 태그가 있는 업체는 태그의 수원점 대표값, 나머지는 가상 값."""
    out = {}
    for n in sorted(set(items["발주처"]) | set(items["원거래처"])):
        direct = items[items["발주처"] == n]
        tagged = direct[direct["리드타임_확인"] == "품명 태그"]
        if len(tagged):
            out[n] = (int(tagged["리드타임_수원점_일"].mode().min()), "품명 태그 대표값")
            continue
        related = items[(items["발주처"] == n) | (items["원거래처"] == n)]
        kinds = set(related["품목구분"])
        kind = next(iter(kinds)) if len(kinds) == 1 else "혼합"
        stype = supplier_type(n) if len(direct[direct["입고내역_있음"]]) else "원거래처(CK 경유 또는 입고 기록 없음)"
        out[n] = (synthetic_lead_time(n, kind, stype), "가상")
    return out


def _range_text(values) -> str:
    vals = sorted(set(values))
    if not vals:
        return NO_INFO
    return f"D{vals[0]}" if len(vals) == 1 else f"D{vals[0]}~D{vals[-1]}"


# ---------------------------------------------------------------- 업체별_품목
def build_supplier_items(rec: pd.DataFrame, cnt: pd.DataFrame) -> pd.DataFrame:
    """입고내역(발주·입고)을 기준으로 실사재고를 붙여 업체별 품목표를 만든다."""
    known = set(rec["거래처명"]) | set(cnt["거래처명"])
    day_cols = [c for c in rec.columns if DAY_COL.match(c)]
    qty_cols = [c for c in day_cols if c.endswith("_수량")]
    amt_cols = [c for c in day_cols if c.endswith("_금액")]

    # 실사재고 행은 한 번만 쓴다: 코드로 먼저 연결하고, 남은 입고 품목만 품명으로 남은 실사 행에 연결
    by_code = {r["품목코드_RMS"]: idx for idx, r in cnt.iterrows() if r["품목코드_RMS"] != "없음"}
    stock_of: dict = {}
    used: set = set()
    for i, r in rec.iterrows():
        idx = by_code.get(r["품목코드_RMS"])
        if idx is not None and idx not in used:
            stock_of[i] = idx
            used.add(idx)
    for i, r in rec.iterrows():
        if i in stock_of:
            continue
        idx = next((j for j in cnt.index[cnt["품명"] == r["품명"]] if j not in used), None)
        if idx is not None:
            stock_of[i] = idx
            used.add(idx)

    def lead(tag):
        lt = lead_times(tag)
        return (lt[0], lt[1], "품명 태그") if lt else (0, 0, NO_INFO)

    rows = []
    for i, r in rec.iterrows():
        stock = cnt.loc[stock_of[i]] if i in stock_of else None
        tag, clean = split_tag(r["품명"])
        s_lead, b_lead, how = lead(tag)
        days = int(((rec.loc[i, qty_cols] != 0) | (rec.loc[i, amt_cols] != 0)).sum()) if day_cols else 0
        origin = normalize_supplier(stock["거래처명"], known) if stock is not None else normalize_supplier(r["거래처명"], known)
        rows.append({
            "발주처": normalize_supplier(r["거래처명"], known), "발주처_원본표기": r["거래처명"], "원거래처": origin,
            "발주경로": "CK경유" if str(r["구분"]).startswith("CK") else "직접", "입고구분": r["구분"],
            "품목구분": "식재료" if r["계정명"] in FOOD_ACCOUNTS else "소모품", "계정명": r["계정명"],
            "품목코드_RMS": r["품목코드_RMS"], "품목코드_CK": r["품목코드_CK"], "품목코드_매장": r["품목코드_매장"],
            "품명": clean, "품명_원본": r["품명"], "품명태그": tag or "없음", "품명_D표기": d_notation(clean) or "없음",
            "규격": r["규격"], "과세면세": r["과세면세"],
            "환산단위": float(r["환산단위"]), "입고단가": float(r["단가"]), "입고단가_g": float(r["단가_g"]),
            "당월발주수량": float(r["당월발주"]), "당월입고수량": float(r["당월합계_수량"]),
            "당월입고중량_g": float(r["당월합계_중량_g"]), "당월입고금액": float(r["당월합계_금액"]), "당월입고일수": days,
            "리드타임_수원점_일": s_lead, "리드타임_부점_일": b_lead, "리드타임_확인": how,
            "실사재고수량": float(stock["재고실사_수량"]) if stock is not None else 0.0,
            "실사재고중량_g": float(stock["재고실사_중량_g"]) if stock is not None else 0.0,
            "입고내역_있음": True, "실사재고_있음": stock is not None,
        })
    for idx, s in cnt.iterrows():                              # 실사재고에만 있는 품목 (입고내역에 연결되지 않은 것)
        if idx in used:
            continue
        tag, clean = split_tag(s["품명"])
        s_lead, b_lead, how = lead(tag)
        name = normalize_supplier(s["거래처명"], known)
        rows.append({
            "발주처": name, "발주처_원본표기": s["거래처명"], "원거래처": name, "발주경로": UNKNOWN, "입고구분": "없음",
            "품목구분": "식재료" if s["계정명"] in FOOD_ACCOUNTS else "소모품", "계정명": s["계정명"],
            "품목코드_RMS": s["품목코드_RMS"], "품목코드_CK": s["품목코드_CK"], "품목코드_매장": s["품목코드_매장"],
            "품명": clean, "품명_원본": s["품명"], "품명태그": tag or "없음", "품명_D표기": d_notation(clean) or "없음",
            "규격": s["규격"], "과세면세": s["과세면세"],
            "환산단위": float(s["환산단위"]), "입고단가": 0.0, "입고단가_g": 0.0, "당월발주수량": 0.0, "당월입고수량": 0.0,
            "당월입고중량_g": 0.0, "당월입고금액": 0.0, "당월입고일수": 0, "리드타임_수원점_일": s_lead,
            "리드타임_부점_일": b_lead, "리드타임_확인": how, "실사재고수량": float(s["재고실사_수량"]),
            "실사재고중량_g": float(s["재고실사_중량_g"]), "입고내역_있음": False, "실사재고_있음": True,
        })
    df = pd.DataFrame(rows)
    leads = supplier_lead_map(df)
    applied = []
    for _, r in df.iterrows():
        if r["리드타임_확인"] == "품명 태그":
            applied.append((int(r["리드타임_수원점_일"]), "품명 태그"))
        else:
            days, src = leads[r["발주처"]]
            applied.append((days, "업체 태그 대표값" if src == "품명 태그 대표값" else "가상"))
    df["리드타임_적용_일"] = [a[0] for a in applied]
    df["리드타임_출처"] = [a[1] for a in applied]
    cols = list(df.columns)
    cols.insert(cols.index("리드타임_확인") + 1, cols.pop(cols.index("리드타임_적용_일")))
    cols.insert(cols.index("리드타임_적용_일") + 1, cols.pop(cols.index("리드타임_출처")))
    return df[cols].sort_values(["발주처", "품목구분", "계정명", "품명"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------- 업체_마스터
def build_suppliers(items: pd.DataFrame) -> pd.DataFrame:
    names = sorted(set(items["발주처"]) | set(items["원거래처"]))
    leads = supplier_lead_map(items)
    rows = []
    for n in names:
        direct = items[items["발주처"] == n]
        received = direct[direct["입고내역_있음"]]
        origin = items[items["원거래처"] == n]
        related = items[(items["발주처"] == n) | (items["원거래처"] == n)]
        kinds = set(related["품목구분"])
        tagged = direct[direct["리드타임_확인"] == "품명 태그"]
        dmarks = direct[direct["품명_D표기"] != "없음"]
        variants = sorted(set(direct["발주처_원본표기"]) - {n})
        rows.append({
            "업체명": n,
            "업체유형": supplier_type(n) if len(received) else "원거래처(CK 경유 또는 입고 기록 없음)",
            "취급구분": next(iter(kinds)) if len(kinds) == 1 else "혼합",
            "취급계정": "/".join(sorted(set(related["계정명"]))),
            "과세면세": "/".join(sorted(set(related["과세면세"]))),
            "품목수": len(related), "발주처_품목수": len(received), "원거래처_품목수": len(origin),
            "표기_변형": "/".join(variants) or "없음",
            "리드타임_수원점": _range_text(tagged["리드타임_수원점_일"]), "리드타임_부점": _range_text(tagged["리드타임_부점_일"]),
            "리드타임_확인": "품명 태그" if len(tagged) else NO_INFO,
            "리드타임_적용_일": leads[n][0], "리드타임_출처": leads[n][1], "태그품목수": len(tagged),
            "D표기_품목수": len(dmarks), "D표기": ", ".join(sorted(set(dmarks["품명_D표기"]))) or "없음",
            "입고품목수": int(((received["당월입고수량"] != 0) | (received["당월입고금액"] != 0)).sum()),
            "당월입고수량": float(received["당월입고수량"].sum()), "당월입고중량_g": float(received["당월입고중량_g"].sum()),
            "당월입고금액": float(received["당월입고금액"].sum()),
        })
    df = pd.DataFrame(rows)
    return df.sort_values(["당월입고금액", "업체명"], ascending=[False, True], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------- 메뉴_마스터
def build_menu(sales: pd.DataFrame, prod: pd.DataFrame) -> pd.DataFrame:
    real = sales[sales["메뉴코드"] != NO_MENU]
    sold = real[real["취소구분"].isin(SALE_KINDS)]
    excluded = real[real["취소구분"].isin(EXCLUDED_KINDS)]
    money = ["총매출", "할인", "실매출", "순매출", "부가세"]
    agg = sold.groupby("메뉴코드").agg(판매수량=("수량", "sum"), **{c: (c, "sum") for c in money})
    agg["영수증수"] = sold.groupby("메뉴코드").apply(lambda d: d[["매출일자", "영수증번호"]].drop_duplicates().shape[0], include_groups=False)
    agg["판매일수"] = sold.groupby("메뉴코드")["매출일자"].nunique()
    agg["제외된_취소정정수량"] = excluded.groupby("메뉴코드")["수량"].sum()

    info = real.groupby("메뉴코드").agg(메뉴명=("메뉴명", "first"), 대분류=("대분류명", "first"), 중분류=("중분류명", "first"),
                                    소분류=("소분류명", "first"), 과면세=("과/면세", "first"))
    normal = real[(real["취소구분"] == "정상") & (real["단가"] > 0)]
    price = normal.groupby("메뉴코드")["단가"].agg(판매가=lambda s: s.mode().min(), 최저단가="min", 최고단가="max", 단가종류수="nunique")

    p = prod[~prod["중복행"]].drop_duplicates("상품코드").set_index("상품코드")
    codes = sorted(set(info.index) | set(p.index))
    m = pd.DataFrame(index=pd.Index(codes, name="메뉴코드"))
    m = m.join(info).join(price).join(agg)
    m["메뉴명"] = m["메뉴명"].fillna(p["상품명"].reindex(m.index))
    for col in ("대분류", "중분류", "소분류", "과면세"):
        m[col] = m[col].fillna(UNKNOWN)
    m["통합메뉴명"] = p["상품명통일"].reindex(m.index).fillna(m["메뉴명"])
    m["BOM유무"] = p["조회_BOM유무"].reindex(m.index).fillna(NO_INFO)
    m["판매및할인_수량"] = p["판매수량"].reindex(m.index)
    m["판매및할인_금액"] = p["판매금액"].reindex(m.index)
    in_prod = m["판매및할인_수량"].notna()
    for col in ("판매수량", *money, "영수증수", "판매일수", "제외된_취소정정수량", "판매및할인_수량", "판매및할인_금액", "판매가", "최저단가",
                "최고단가", "단가종류수"):
        m[col] = m[col].fillna(0).astype("int64")
    m["가격출처"] = [("매출입력 단가" if pr > 0 else ("구성품(단가 0)" if q != 0 or n > 0 else "미확인(이번 달 판매 없음)"))
                 for pr, q, n in zip(m["판매가"], m["판매수량"], m["영수증수"])]
    m["판매및할인_일치"] = ["판매및할인에 없음" if not ip else ("일치" if (q == pq and a == pa) else "불일치")
                      for ip, q, pq, a, pa in zip(in_prod, m["판매수량"], m["판매및할인_수량"], m["순매출"], m["판매및할인_금액"])]
    total = m["순매출"].sum()
    m["순매출비중"] = (m["순매출"] / total * 100).round(4) if total else 0.0
    cols = ["메뉴명", "통합메뉴명", "대분류", "중분류", "소분류", "과면세", "판매가", "가격출처", "최저단가", "최고단가", "단가종류수",
            "판매수량", *money, "순매출비중", "판매일수", "영수증수", "제외된_취소정정수량", "판매및할인_수량", "판매및할인_금액",
            "판매및할인_일치", "BOM유무"]
    return m[cols].reset_index().sort_values(["순매출", "메뉴코드"], ascending=[False, True], kind="stable").reset_index(drop=True)


def build_menu_rollup(menu: pd.DataFrame) -> pd.DataFrame:
    money = ["총매출", "할인", "실매출", "순매출", "부가세"]

    def top_category(s):
        known = s[s != UNKNOWN]
        return known.mode().min() if len(known) else UNKNOWN

    g = menu.groupby("통합메뉴명").agg(메뉴코드수=("메뉴코드", "count"), 대분류=("대분류", top_category),
                                    판매수량=("판매수량", "sum"), **{c: (c, "sum") for c in money})
    total = g["순매출"].sum()
    g["순매출비중"] = (g["순매출"] / total * 100).round(4) if total else 0.0
    return g.reset_index().sort_values(["순매출", "통합메뉴명"], ascending=[False, True], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------- 일자별_매출
def build_daily(sales: pd.DataFrame) -> pd.DataFrame:
    sold = sales[sales["취소구분"].isin(SALE_KINDS) & (sales["메뉴코드"] != NO_MENU)]
    money = ["총매출", "할인", "실매출", "순매출", "부가세"]
    g = sold.groupby("매출일자").agg(메뉴판매수량=("수량", "sum"), **{c: (c, "sum") for c in money})
    day = sales.groupby("매출일자").agg(영수증수=("영수증번호", "nunique"), 객수=("객수_합계", "sum"), 순매출_영수증합계=("순매출_합계", "sum"))
    d = day.join(g).fillna(0)
    for col in d.columns:
        d[col] = d[col].astype("int64")
    d["객단가"] = [int(round(n / g_)) if g_ else 0 for n, g_ in zip(d["순매출"], d["객수"])]
    d["요일"] = [WEEKDAY[pd.Timestamp(x).weekday()] for x in d.index]
    cols = ["요일", "영수증수", "객수", "메뉴판매수량", *money, "객단가", "순매출_영수증합계"]
    return d[cols].reset_index()


# ---------------------------------------------------------------- 열 설명
COLUMN_DOC = {
    "업체_마스터": {
        "업체명": "업체 이름. '쿠팡저장품'처럼 계정명이 붙은 표기는 같은 업체로 합침",
        "업체유형": "업체 / 센트럴키친(CK) / 온라인 구매처 / 원거래처(CK 경유 또는 입고 기록 없음)",
        "취급구분": "식재료(원재료·반제품) / 소모품(저장품·포장재료) / 혼합",
        "취급계정": "취급하는 계정명",
        "과세면세": "과세·면세 구분",
        "품목수": "이 업체와 연결된 품목 수 (발주처 또는 원거래처)",
        "발주처_품목수": "이 업체가 입고처(발주처)인 품목 수 (입고내역 기준)",
        "원거래처_품목수": "실사재고에 원거래처로 적힌 품목 수 (CK를 거쳐 들어오는 품목 포함)",
        "표기_변형": "같은 업체의 다른 표기",
        "리드타임_수원점": "품명 태그 `[수Dn/부Dn]`의 수원점 값. 태그가 없으면 '정보 없음'",
        "리드타임_부점": "품명 태그의 '부' 값 (부산점으로 추정, 확인 필요)",
        "리드타임_확인": "리드타임을 알아낸 근거 (품명 태그 / 정보 없음). 실제 데이터에서 읽은 값만 해당",
        "리드타임_적용_일": "발주 계산에 쓰는 리드타임(일). 품명 태그가 있으면 그 값, 없으면 **가상 값**(실제 데이터 아님)",
        "리드타임_출처": "품명 태그 대표값(실제) / 가상 (업체 유형·취급 구분·이름 기준으로 만든 값)",
        "태그품목수": "리드타임 태그가 붙은 품목 수",
        "D표기_품목수": "품명에 D 표기(D1, D-2 등)가 있는 품목 수 (의미 확인 필요: 리드타임 또는 발주 마감일)",
        "D표기": "품명에 쓰인 D 표기 종류",
        "입고품목수": "이번 달 입고 실적이 있는 품목 수",
        "당월입고수량": "이번 달 입고 수량 합계 (규격 단위)",
        "당월입고중량_g": "이번 달 입고 중량 합계(g)",
        "당월입고금액": "이번 달 입고 금액 합계(원)",
    },
    "업체별_품목": {
        "발주처": "발주·입고 업체(입고내역 거래처명, 표기 정리)", "발주처_원본표기": "입고내역에 적힌 원래 업체명",
        "원거래처": "실사재고에 적힌 거래처 (CK 경유 품목은 발주처와 다를 수 있음)",
        "발주경로": "직접 / CK경유(입고구분이 CK) / 미확인(입고내역에 없는 품목)", "입고구분": "입고내역의 구분 (예: 아워홈과세, CK)",
        "품목구분": "식재료 / 소모품", "계정명": "원재료·반제품·저장품·포장재료",
        "품목코드_RMS": "RMS 품목코드", "품목코드_CK": "CK 품목코드", "품목코드_매장": "매장 품목코드",
        "품명": "품명 (앞의 [태그] 제거)", "품명_원본": "원본 품명", "품명태그": "품명 앞의 태그 (리드타임 또는 위치 표시)",
        "품명_D표기": "품명 속 D 표기 (예: D1, D-2). 점포 구분이 없고 의미가 확인되지 않아 리드타임 열에는 넣지 않음",
        "규격": "규격", "과세면세": "과세/면세", "환산단위": "규격 1개당 g",
        "입고단가": "입고 단가(원, 규격 1개당)", "입고단가_g": "입고 단가(원/g)",
        "당월발주수량": "이번 달 발주 수량", "당월입고수량": "이번 달 입고 수량", "당월입고중량_g": "이번 달 입고 중량(g)",
        "당월입고금액": "이번 달 입고 금액(원)", "당월입고일수": "이번 달 입고가 있었던 날 수",
        "리드타임_수원점_일": "품명 태그의 수원점 리드타임(일). 정보 없으면 0", "리드타임_부점_일": "품명 태그의 '부' 리드타임(일). 정보 없으면 0",
        "리드타임_확인": "품명 태그 / 정보 없음 (0일과 구분하는 열). 실제 데이터에서 읽은 값만 해당",
        "리드타임_적용_일": "발주 계산에 쓰는 리드타임(일). 품명 태그가 있으면 그 값, 없으면 업체 대표값 또는 **가상 값**",
        "리드타임_출처": "품명 태그 / 업체 태그 대표값 (실제) / 가상 (실제 데이터 아님)",
        "실사재고수량": "실사재고 수량 (규격 단위)", "실사재고중량_g": "실사재고 중량(g)",
        "입고내역_있음": "입고내역 시트에 있는 품목인지", "실사재고_있음": "실사재고 시트와 연결됐는지 (연결 안 되면 재고는 0으로 표시)",
    },
    "메뉴_마스터": {
        "메뉴코드": "메뉴(상품) 코드", "메뉴명": "메뉴 이름", "통합메뉴명": "판매및할인의 '상품명 통일' (채널별 변형을 합친 이름)",
        "대분류": "음식/음료 (이번 달 판매 기록이 없으면 미확인)", "중분류": "중분류", "소분류": "소분류", "과면세": "과세/면세",
        "판매가": "가장 많이 쓰인 0원 초과 단가", "가격출처": "매출입력 단가 / 구성품(단가 0) / 미확인(이번 달 판매 없음)",
        "최저단가": "0원 초과 단가 중 최저", "최고단가": "단가 중 최고", "단가종류수": "서로 다른 0원 초과 단가 수",
        "판매수량": "'정상'+'매출취소' 행의 수량 합", "총매출": "총매출 합", "할인": "할인 합", "실매출": "실매출 합",
        "순매출": "순매출 합 (판매및할인의 판매금액과 같은 기준)", "부가세": "부가세 합", "순매출비중": "전체 순매출 대비 비중(%)",
        "판매일수": "판매가 있었던 날 수", "영수증수": "이 메뉴가 들어간 영수증 수",
        "제외된_취소정정수량": "메뉴정정·주문취소 행의 수량 (매출 집계에서 제외)",
        "판매및할인_수량": "판매및할인 시트의 판매수량", "판매및할인_금액": "판매및할인 시트의 판매금액",
        "판매및할인_일치": "일치 / 불일치 / 판매및할인에 없음", "BOM유무": "판매및할인의 BOM 유무",
    },
    "통합메뉴_매출": {
        "통합메뉴명": "상품명 통일", "메뉴코드수": "합쳐진 메뉴 코드 수", "대분류": "대표 대분류",
        "판매수량": "판매수량 합", "총매출": "총매출 합", "할인": "할인 합", "실매출": "실매출 합", "순매출": "순매출 합",
        "부가세": "부가세 합", "순매출비중": "전체 순매출 대비 비중(%)",
    },
    "일자별_매출": {
        "매출일자": "날짜", "요일": "요일", "영수증수": "그날 영수증 수", "객수": "객수 합계 (영수증 단위)",
        "메뉴판매수량": "정상+매출취소 행의 수량 합", "총매출": "총매출 합", "할인": "할인 합", "실매출": "실매출 합",
        "순매출": "순매출 합 (정상+매출취소 행)", "부가세": "부가세 합", "객단가": "순매출 ÷ 객수(원, 반올림)",
        "순매출_영수증합계": "영수증 단위 순매출 합계(확인용)",
    },
}
TABLE_DESCRIPTION = {
    "업체_마스터": "업체별 요약: 유형, 취급 구분, 리드타임(태그 기준), 이번 달 입고 합계",
    "업체별_품목": "업체별로 발주 가능한 식재료·소모품 목록 (규격·단가·리드타임·입고 실적·실사 재고 포함)",
    "메뉴_마스터": "메뉴별 판매가·판매수량·매출 (판매및할인 시트와 코드 단위로 대조)",
    "통합메뉴_매출": "'상품명 통일' 기준으로 합친 메뉴 매출",
    "일자별_매출": "일자별 객수·메뉴 판매·매출",
}


# ---------------------------------------------------------------- 실행
def build_all(src, sheets: dict | None = None) -> tuple[dict, dict]:
    """마크다운 파일 -> ({표 이름: DataFrame}, {"checks": [...], "notes": [...]}). sheets 를 주면 파일을 다시 읽지 않는다."""
    sheets = sheets if sheets is not None else read_sheets(src)
    sales, _ = clean_sales.clean_sales_detail(sheets[clean_sales.SHEET])
    prod, _, _ = sales_sheets.clean_sales_summary(sheets[sales_sheets.SHEET_SALES_SUMMARY])
    cnt, _, _ = stock_sheets.clean_inventory_count(sheets[stock_sheets.SHEET_COUNT])
    rec, _, _ = stock_sheets.clean_receiving(sheets[stock_sheets.SHEET_RECEIVING])
    items = build_supplier_items(rec, cnt)
    menu = build_menu(sales, prod)
    tables = {"업체_마스터": build_suppliers(items), "업체별_품목": items, "메뉴_마스터": menu,
              "통합메뉴_매출": build_menu_rollup(menu), "일자별_매출": build_daily(sales)}
    in_prod = menu[menu["판매및할인_일치"] != "판매및할인에 없음"]
    only_sales = menu[menu["판매및할인_일치"] == "판매및할인에 없음"]
    checks = [
        ("판매및할인에 있는 메뉴의 판매수량 합 = 판매및할인(중복 제외) 합", int(in_prod["판매수량"].sum()), int(prod[~prod["중복행"]]["판매수량"].sum())),
        ("판매및할인에 있는 메뉴의 순매출 합 = 판매및할인(중복 제외) 판매금액 합", int(in_prod["순매출"].sum()), int(prod[~prod["중복행"]]["판매금액"].sum())),
        ("메뉴 순매출 합 = 일자별 순매출 합", int(menu["순매출"].sum()), int(tables["일자별_매출"]["순매출"].sum())),
        ("업체별 품목 당월입고금액 합 = 입고내역 합", round(float(items["당월입고금액"].sum()), 4), round(float(rec["당월합계_금액"].sum()), 4)),
    ]
    mismatch = menu[menu["판매및할인_일치"] == "불일치"]
    notes = [f"메뉴 {len(mismatch)}개가 판매및할인과 일치하지 않음"] if len(mismatch) else []
    if len(only_sales):
        notes.append(f"판매및할인에 없는 메뉴 {len(only_sales)}개 (판매수량 {int(only_sales['판매수량'].sum()):,}개, 순매출 "
                     f"{int(only_sales['순매출'].sum()):,}원): 판매및할인 시트에는 목록이 없는 메뉴")
    return tables, {"checks": [{"항목": n, "기대": a, "실제": b, "ok": a == b} for n, a, b in checks], "notes": notes}


def write_outputs(tables: dict, out: Path) -> list[Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, df in tables.items():
        p = out / f"{name}.csv"
        df.to_csv(p, index=False, encoding="utf-8-sig")
        written.append(p)
    doc_rows = [{"표": t, "열": c, "설명": d} for t, cols in COLUMN_DOC.items() for c, d in cols.items()]
    pd.DataFrame(doc_rows).to_csv(out / "열_설명.csv", index=False, encoding="utf-8-sig")
    readme = ["# 정리된 데이터 파일", "", "`data/f_b_menu_data.md`에서 만든 업체·품목·메뉴·매출 표입니다 (모두 `python -m prep.organize`로 다시 만들 수 있음).", "",
              "> **주의: 리드타임의 `가상` 값은 실제 데이터가 아닙니다.** 원본 파일에는 아워홈 한 곳의 품명 태그에만 리드타임이 있어서,",
              "> 나머지 업체는 업체 유형·취급 구분·이름 기준의 현실적인 값을 만들어 `리드타임_적용_일`에 넣고 `리드타임_출처`를 `가상`으로 표시했습니다.",
              "> 실제 값(`리드타임_수원점`, `리드타임_부점`, `리드타임_확인`)은 그대로 두었습니다. 실제 리드타임을 알게 되면 `data/` 쪽 값을 바꾸면 됩니다.", ""]
    for t, desc in TABLE_DESCRIPTION.items():
        readme += [f"## {t}  ({len(tables[t]):,}행)", desc, "", "| 열 | 설명 |", "|---|---|",
                   *[f"| {c} | {d} |" for c, d in COLUMN_DOC[t].items()], ""]
    (out / "README.md").write_text("\n".join(readme), encoding="utf-8")
    xlsx = out / "F&B_데이터정리.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        pd.DataFrame([{"표": t, "행 수": len(tables[t]), "설명": TABLE_DESCRIPTION[t]} for t in tables]).to_excel(w, sheet_name="목차", index=False)
        for name, df in tables.items():
            df.to_excel(w, sheet_name=name, index=False)
            w.sheets[name].freeze_panes = "B2"
        pd.DataFrame(doc_rows).to_excel(w, sheet_name="열_설명", index=False)
    return [*written, out / "열_설명.csv", out / "README.md", xlsx]


def main(argv=None) -> int:
    data = Path(__file__).resolve().parent.parent / "data"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=str(data / "f_b_menu_data.md"))
    ap.add_argument("--out", default=str(data / "organized"))
    a = ap.parse_args(argv)
    tables, info = build_all(a.src)
    files = write_outputs(tables, a.out)
    for t, df in tables.items():
        print(f"■ {t}: {len(df):,}행 x {df.shape[1]}열")
    for c in info["checks"]:
        print(("  ✓ " if c["ok"] else "  ✗ ") + f"{c['항목']}: {c['기대']:,} vs {c['실제']:,}")
    for n in info["notes"]:
        print("  ·", n)
    print(f"저장: {a.out} ({len(files)}개 파일)")
    return 0 if all(c["ok"] for c in info["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
