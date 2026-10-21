"""'타_폐기' 시트 (타계정출고 [재고자산폐기]) 정제.

시트는 위아래 두 표로 이루어져 있다.

  1. 폐기 기록 (일자가 날짜인 행): 일자·품목·수량·중량·사유. 2025년과 2026-05까지는 월말 하루에 한 달치를 몰아 적었고,
     2026-06부터는 일별로 적는다. 밥·라웨이황과처럼 품목코드 대신 이름이 들어간 행(RMS 품목이 아님)도 여기에 있다.
  2. 품목별 월 합계 (일자가 날짜가 아닌 행): 모든 RMS 품목을 나열하고 그 달 폐기량을 적는다. 밥은 쌀로, 라웨이황과는
     재료(참기름·설탕 …)로 분해해 같은 표에 넣었고, 이때 '일자' 칸에 원천 이름이 적혀 있다. 맨 아래 '합 계' 행은 이 표의 합이다.

두 표를 각각 `상세`, `품목별` 로 내보낸다. 폐기량이 0인 품목 행은 지우되 몇 행을 지웠는지 기록한다.
규칙은 데이터에서 성립함을 확인한 관계만 쓴다 (수량 = 중량 ÷ 환산단위).
"""
import re

import pandas as pd

from prep.blocks import REPORT_COLUMNS, UnhandledMissingError, ensure_no_missing, fill, find_row, label, make_check as _check

SHEET_WASTE = "타_폐기"
NONE_TEXT = "없음"
UNSPEC_TEXT = "미기재"
DETAIL_COLS = ["귀속월", "일자", "기록방식", "품목코드", "거래처명", "품명", "규격", "환산단위", "수량", "중량_g", "사유_원문", "사유_분류"]
SUMMARY_COLS = ["분해원천", "품목코드", "거래처명", "품명", "규격", "환산단위", "수량", "중량_g"]
RAW_COLS = ["일자", "품목코드", "거래처명", "품명", "규격", "환산단위", "수량", "중량_g", "사유"]

# 사유 문구 -> 분류. 위에서부터 처음 맞는 것. 띄어쓰기·월 표시(예: '2월 1~28일')는 무시하고 키워드로 본다.
REASON_RULES = [
    ("유통기한", "유통기한 경과"),
    ("잔량", "마감 후 잔량"),
    ("실수", "직원 실수"),
    ("시즌", "시즌 종료"),
    ("자투리", "작업 후 자투리·불량"),
    ("작업", "작업 후 자투리·불량"),
    ("제조불량", "작업 후 자투리·불량"),
    ("불량", "품질·상태 불량"),
    ("상태", "품질·상태 불량"),
    ("워크인", "설비 고장"),
    ("휴무", "백화점 휴무"),
    ("업체변경", "업체 변경"),
    ("판매종료", "판매 종료·중단"),
    ("판매중단", "판매 종료·중단"),
    ("사용중지", "판매 종료·중단"),
    ("교육", "교육·테스트·촬영"),
    ("테스트", "교육·테스트·촬영"),
    ("영상촬영", "교육·테스트·촬영"),
    ("조리연습", "교육·테스트·촬영"),
    ("라벨", "라벨 손상"),
]
OTHER_REASON = "기타"


def reason_category(text: str) -> str:
    s = re.sub(r"\s+", "", str(text))
    for key, cat in REASON_RULES:
        if key in s:
            return cat
    return OTHER_REASON


def _locate(raw: pd.DataFrame):
    h = find_row(raw, 1, "일자")
    if h is None:
        raise ValueError("머리글 행('일자')을 찾지 못했습니다.")
    end = find_row(raw, 1, "합계", start=h + 1)
    if end is None:
        raise ValueError("'합 계' 행을 찾지 못했습니다.")
    return h, end


def _is_rms(code) -> bool:
    return pd.notna(code) and re.fullmatch(r"\d{9,10}", str(code)) is not None


def clean_waste(raw: pd.DataFrame, month: str | None = None):
    """'타_폐기' 시트 -> ({"상세": 표, "품목별": 표}, 처리내역, {"dropped", "checks", "notes"}).

    month 는 'YYYY-MM' (귀속월). 없으면 가장 많은 일자의 달.
    """
    h, end = _locate(raw)
    body = raw.iloc[h + 1:end, 1:10].copy()
    body.columns = RAW_COLS
    body = body.reset_index(drop=True)
    report: list[dict] = []
    unit_text = body["중량_g"].astype("string").str.fullmatch(r"\s*[\d.,]+\s*[gG]\s*").fillna(False)     # '304g' 처럼 단위 글자가 붙은 칸
    if unit_text.any():
        body.loc[unit_text, "중량_g"] = body.loc[unit_text, "중량_g"].astype("string").str.replace(r"[gG,\s]", "", regex=True)
        report.append({"열": "중량_g", "채운 개수": int(unit_text.sum()), "규칙": "숫자 뒤에 단위 글자(g)가 붙어 있어 글자를 뗌", "채운 값": "숫자만"})
    for c in ("환산단위", "수량", "중량_g"):
        body[c] = pd.to_numeric(body[c], errors="raise")
    dates = pd.to_datetime(body["일자"], errors="coerce", format="mixed")
    is_rec = dates.notna()
    checks: list[dict] = []
    notes: list[str] = []
    dropped: list[str] = []

    rec, summ = body[is_rec].copy(), body[~is_rec].copy()
    rec["일자"] = dates[is_rec].dt.strftime("%Y-%m-%d")
    month = month or rec["일자"].str[:7].mode().iat[0]

    # ---- 품목별 월 합계 표 ----
    summ = summ.rename(columns={"일자": "분해원천"})
    master = summ.dropna(subset=["품목코드"]).drop_duplicates("품목코드").set_index("품목코드")[["거래처명", "품명", "규격", "환산단위"]]   # 0인 행 포함 전체 품목
    zero = summ["수량"].fillna(0).eq(0) & summ["중량_g"].fillna(0).eq(0)
    dropped.append(f"품목별 표의 폐기량 0인 행 {int(zero.sum())}개")
    summ = summ[~zero].drop(columns="사유").reset_index(drop=True)
    total = raw.iloc[end]
    checks.append(_check("품목별 수량 합계 = '합 계' 행", pd.to_numeric(total.iloc[7]), summ["수량"].sum(), abs_tol=1e-4))
    checks.append(_check("품목별 중량 합계 = '합 계' 행", pd.to_numeric(total.iloc[8]), summ["중량_g"].sum(), abs_tol=1e-3))
    fill(summ, "분해원천", NONE_TEXT, summ["분해원천"].isna(), "분해 원천 없음(직접 폐기)", report)
    fill(summ, "거래처명", NONE_TEXT, summ["거래처명"].isna(), "거래처 없음", report)
    ensure_no_missing(summ)
    lookup = master["환산단위"]

    # ---- 폐기 기록 표 ----
    empty = rec["품목코드"].isna() & rec["품명"].isna() & rec["수량"].fillna(0).eq(0) & rec["중량_g"].fillna(0).eq(0)
    if empty.any():
        dropped.append(f"폐기 기록 표의 내용 없는 행 {int(empty.sum())}개 (일자만 있고 품목·수량·중량이 없음)")
    rec = rec[~empty].reset_index(drop=True)

    code = rec["품목코드"].astype("string")
    short = code.notna() & code.str.fullmatch(r"\d{9}").fillna(False)
    if short.any():
        fill(rec, "품목코드", code.str.zfill(10), short, "앞자리 0이 빠진 9자리 코드", report, shown="10자리로 맞춤")
        code = rec["품목코드"].astype("string")
    rms = code.str.fullmatch(r"\d{10}").fillna(False)
    named = code.notna() & ~rms                                            # 밥·라웨이황과: 코드 자리에 이름이 적힘
    rec.loc[named, "품명"] = rec.loc[named, "품목코드"]
    rec.loc[named, "품목코드"] = pd.NA
    n_named = int(named.sum())
    if n_named:
        report.append({"열": "품목코드", "채운 개수": n_named, "규칙": "코드 자리에 이름이 적힌 행(밥·라웨이황과)은 이름을 품명으로 옮김", "채운 값": NONE_TEXT})
    rms = rec["품목코드"].notna()

    # 채우기 전 규칙 검증: 수량 × 환산단위 = 중량 (값이 다 있는 RMS 행)
    full = rms & rec[["환산단위", "수량", "중량_g"]].notna().all(axis=1)
    bad = full & ((rec["수량"] * rec["환산단위"] - rec["중량_g"]).abs() > 1e-6 * (1 + rec["중량_g"].abs()) + 0.5)
    checks.append(_check("수량 × 환산단위 = 중량 (값이 다 있는 행 불일치 수)", 0, int(bad.sum()), note=True))

    # 환산단위가 비어 있으면 품목별 표의 같은 코드 값을 쓴다. 수량 칸에 환산단위가 들어간 행(수량 == 환산단위)은 수량을 중량 ÷ 환산단위로 다시 계산한다.
    miss_unit = rms & rec["환산단위"].isna()
    unit = rec["품목코드"].map(lookup)
    fill(rec, "환산단위", unit, miss_unit & unit.notna(), "품목별 표의 같은 코드 환산단위", report, shown="품목별 표 값")
    swapped = miss_unit & unit.notna() & (rec["수량"] == unit) & rec["중량_g"].notna()
    fill(rec, "수량", rec["중량_g"] / rec["환산단위"], swapped, "수량 칸에 환산단위가 적혀 있어 중량 ÷ 환산단위로 다시 계산", report, shown="중량÷환산단위")
    fill(rec, "수량", rec["중량_g"] / rec["환산단위"], rms & rec["수량"].isna() & rec["중량_g"].notna() & rec["환산단위"].notna(),
         "중량 ÷ 환산단위로 계산", report, shown="중량÷환산단위")
    fill(rec, "수량", rec["중량_g"] / rec["환산단위"], rms & rec["수량"].eq(0) & (rec["중량_g"] > 0) & (rec["환산단위"] > 0),
         "수량이 0인데 중량이 있어 중량 ÷ 환산단위로 다시 계산", report, shown="중량÷환산단위")
    fill(rec, "중량_g", rec["수량"] * rec["환산단위"], rms & rec["중량_g"].isna() & rec["수량"].notna() & rec["환산단위"].notna(),
         "수량 × 환산단위로 계산", report, shown="수량×환산단위")
    # RMS 품목이 아닌 행(밥 등)은 무게만 적는다: 수량 0, 환산단위 0(해당 없음)
    fill(rec, "수량", 0.0, ~rms & rec["수량"].isna(), "RMS 품목이 아니라 중량만 기록", report)
    fill(rec, "환산단위", 0.0, ~rms & rec["환산단위"].isna(), "RMS 품목이 아니라 환산단위 없음(0)", report)
    for col in ("거래처명", "품명", "규격"):                                 # 비어 있으면 품목별 표의 같은 코드 값
        fill(rec, col, rec["품목코드"].map(master[col]), rms & rec[col].isna() & rec["품목코드"].map(master[col]).notna(), "품목별 표의 같은 코드 값", report, shown="품목별 표 값")
    fill(rec, "거래처명", NONE_TEXT, rec["거래처명"].isna(), "해당 없음", report)
    fill(rec, "규격", UNSPEC_TEXT, rec["규격"].isna(), "원본에 적혀 있지 않음", report)
    fill(rec, "품목코드", NONE_TEXT, rec["품목코드"].isna(), "RMS 코드 없음", report)
    fill(rec, "사유", UNSPEC_TEXT, rec["사유"].isna(), "원본에 적혀 있지 않음", report)
    ensure_no_missing(rec)

    rec = rec.rename(columns={"사유": "사유_원문"})
    rec["사유_분류"] = rec["사유_원문"].map(lambda t: UNSPEC_TEXT if t == UNSPEC_TEXT else reason_category(t))
    rec["귀속월"] = month
    rec["기록방식"] = "월말일괄" if rec["일자"].nunique() == 1 else "일별"
    off = rec["일자"].str[:7] != month
    if off.any():
        notes.append(f"일자가 {month}이 아닌 기록 {int(off.sum())}개 ({', '.join(sorted(set(rec.loc[off, '일자'])))}): 사유 문구로 보아 {month} 폐기라서 귀속월은 {month}으로 둠")
    other = rec["사유_분류"] == OTHER_REASON
    if other.any():
        notes.append("분류하지 못한 사유: " + "; ".join(sorted(set(rec.loc[other, "사유_원문"]))[:6]))
    detail = rec[DETAIL_COLS].reset_index(drop=True)

    # ---- 두 표 대조: 직접 폐기한 코드의 상세 중량 합 = 품목별 표 중량 (분해원천 없음 행) ----
    # 밥·라웨이황과 분해 행과 코드가 겹치는 품목은 품목별 표에 분해 행만 남아 있어 따로 센다.
    decomposed = set(summ.loc[summ["분해원천"] != NONE_TEXT, "품목코드"])
    d_w = detail[detail["품목코드"] != NONE_TEXT].groupby("품목코드")["중량_g"].sum()
    s_w = summ[summ["분해원천"] == NONE_TEXT].groupby("품목코드")["중량_g"].sum()
    both = d_w.index.union(s_w.index)
    diff = (d_w.reindex(both).fillna(0) - s_w.reindex(both).fillna(0)).abs()
    mismatch = diff[diff > 0.5]
    overlap, real = mismatch[mismatch.index.isin(decomposed)], mismatch[~mismatch.index.isin(decomposed)]
    checks.append(_check("상세 표 코드별 중량 합 = 품목별 표 중량 (분해 품목 제외, 불일치 코드 수, 원본 값 차이)", 0, len(real), note=True))
    if len(overlap):
        notes.append(f"분해 행과 겹쳐 품목별 표에 직접 폐기분이 없는 코드 {len(overlap)}개: " + ", ".join(f"{c}({d:,.0f}g)" for c, d in overlap.head(6).items()))
    if len(real):
        notes.append("상세와 품목별 표의 중량이 다른 코드: " + ", ".join(f"{c}({d:,.0f}g)" for c, d in real.head(6).items()))
    return {"상세": detail, "품목별": summ[SUMMARY_COLS]}, pd.DataFrame(report, columns=REPORT_COLUMNS), {"dropped": dropped, "checks": checks, "notes": notes}
