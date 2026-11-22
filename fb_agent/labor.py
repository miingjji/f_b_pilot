"""스케줄 엑셀(.xls) 파서 (Streamlit 비의존). 원문은 지우지 않고 읽고, 못 읽는 값은 '미해석'으로 남긴다.

시트: FOH·BK·FK(게시용)만 읽는다 (MOD는 다른 매장이라 제외). 한 줄 = 한 사람, 날짜별 칸에 근무 코드.
코드: 알파벳=출근(A9시 B10 … K19, S=+30분), 숫자=퇴근시각(기본 20.5), '+'=휴게 1시간. '/'=휴무.
시간: 파일의 '근무조' 시트 표(코드→근무시간)를 먼저 조회하고, 표에 없으면 시작·종료·휴게로 계산한다.
평일의 '+'는 오입력으로 보고 떼어서(휴게 2시간) 다시 조회한다. 주말·공휴일은 표 그대로.
직원(PT 외)은 시간만, PT는 시급×시간(+주 15시간 이상이면 주휴)으로 비용을 낸다.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import xlrd

from store_calendar import public_holidays

DEPTS = ("FOH", "BK", "FK")          # MOD(게시용)는 제외
PT_WAGE = 10400                       # 24~26년 동일 (주휴 미포함)
START = {c: 9 + i for i, c in enumerate("ABCDEFGHIJK")}
SHIFT_RX = re.compile(r"^([A-K])(S?)(\d{2}(?:\.\d)?)?(\+?)$")
HQ_SUPPORT_NOTE = ("지원", "님")   # 본사에서 나오는 지원 인력 표기(예: 실장님지원, PM님C20) — 우리 매장 근무가 아니라 읽지 않는다
YEBIGUN = {"예", "비", "군"}   # 예비군을 한 글자씩 나눠 쓴 칸 (김명률 2024-12, 3일). 근무시간 없음
KINDS = {"/": "휴무", "대휴": "대휴", "연차": "연차", "반차": "반차", "무급": "무급", "경조": "경조", "교육": "교육", "대휴반차": "반차", "훈련": "훈련"}
ROLES = {"GM", "SM", "KM", "AM", "TR", "PT", "사원", "리더", "부점장", "점장", "지원", "중국인"}
PHONE_RX = re.compile(r"^(\d{3,4}-\d{2,4}|01\d[-\d]*)$")


def _text(v) -> str:
    return str(v).strip().strip("'").strip() if v != "" else ""


def _is_workday_off(d: date) -> bool:
    return d.weekday() >= 5 or d in public_holidays()


def shift_table(book) -> dict:
    """'근무조' 시트: 2행=코드, 3행=근무시간."""
    s = book.sheet_by_name("근무조")
    out = {}
    for c in range(s.ncols):
        k, v = _text(s.cell_value(2, c)).upper(), s.cell_value(3, c)
        if k and isinstance(v, float):
            out.setdefault(k, v)
    return out


def classify(raw: str, d: date, table: dict) -> dict:
    """셀 하나 → {종류, 근무시간, 비고}. 종류: 근무·휴무·대휴·연차·반차·무급·경조·교육·훈련·미해석·(빈칸은 호출 전에 거른다)."""
    t = raw.strip().upper()
    if raw.strip() in KINDS:
        k = KINDS[raw.strip()]
        return {"종류": k, "근무시간": table.get("훈련", 8.0) if k == "훈련" else 0.0, "비고": ""}
    if raw.strip() in YEBIGUN:
        return {"종류": "예비군", "근무시간": 0.0, "비고": ""}
    if any(w in raw for w in HQ_SUPPORT_NOTE):
        return {"종류": "본사지원", "근무시간": 0.0, "비고": ""}
    note = ""
    if t.endswith("+") and not _is_workday_off(d):   # 평일 '+' = 오입력 → 휴게 2시간
        t, note = t[:-1], "평일+보정"
    if t in table:
        return {"종류": "근무", "근무시간": table[t], "비고": note}
    m = SHIFT_RX.match(t)
    if not m:
        return {"종류": "미해석", "근무시간": 0.0, "비고": ""}
    start = START[m.group(1)] + (0.5 if m.group(2) else 0)
    end = float(m.group(3) or 20.5)
    dur = end - start
    brk = 1 if m.group(4) else (2 if dur >= 9 else 1 if dur >= 5 else 0)
    return {"종류": "근무", "근무시간": dur - brk, "비고": (note + " 표없음계산").strip()}


def parse_sheet(book, sheet, table: dict, month_hint: str) -> list[dict]:
    hr = next((r for r in range(8) if _text(sheet.cell_value(r, 1)) == "일자"), None)
    if hr is None:
        return []
    c0 = next((c for c in range(2, 8) if sheet.cell_value(hr, c) in (1, 1.0)), None)
    if c0 is None:
        return []
    hc = next((c for c in range(sheet.ncols) if _text(sheet.cell_value(2, c)) == "근무시간"), None)
    days = []
    for c in range(c0, min(c0 + 31, sheet.ncols)):
        v = sheet.cell_value(hr + 1, c)
        days.append((c, xlrd.xldate_as_datetime(v, book.datemode).date()) if isinstance(v, float) and v > 40000 else None)
    rows, last_role = [], ""
    for r in range(hr + 3, sheet.nrows):
        side = [_text(sheet.cell_value(r, c)) for c in range(1, c0)]
        if any("일일 근무" in x or x == "비고" for x in side):   # 사람 구간의 끝 (아래는 범례·집계)
            break
        role = next((x for x in side if x in ROLES), "")
        sabun = next((x for x in side if PHONE_RX.match(x)), "")
        name = next((x for x in side if x and x not in ROLES and not PHONE_RX.match(x) and not re.fullmatch(r"\d+(\.0)?", x)), "")
        if not name:
            continue
        if role:
            last_role = role
        sheet_hours = sheet.cell_value(r, hc) if hc is not None and isinstance(sheet.cell_value(r, hc), float) else None
        for dd in days:
            if dd is None:
                continue
            c, d = dd
            raw = _text(sheet.cell_value(r, c))
            rows.append({"월": month_hint, "부서": sheet.name[:3].strip("("), "이름": name, "직급": role or f"({last_role})", "사번": sabun,
                         "날짜": d, "원문": raw, "시트근무시간": sheet_hours, **(classify(raw, d, table) if raw else {"종류": "빈칸", "근무시간": 0.0, "비고": ""})})
    return rows


def parse_workbook(path) -> pd.DataFrame:
    book = xlrd.open_workbook(str(path))
    table = shift_table(book)
    rows = []
    for s in book.sheets():
        if s.name.strip().split("(")[0] in DEPTS and "게시용" in s.name:
            rows += parse_sheet(book, s, table, "")
    df = pd.DataFrame(rows)
    if len(df):
        df["월"] = pd.to_datetime(df["날짜"]).dt.strftime("%Y-%m")
        # 같은 달 파일인데 다른 달 날짜가 섞이면(31일 칸 등) 가장 많은 달만 남긴다
        df = df[df["월"] == df["월"].mode()[0]].reset_index(drop=True)
    return df


def parse_dir(src) -> pd.DataFrame:
    frames = []
    for f in sorted(Path(src).glob("스케줄(*)(최신).xls")):
        d = parse_workbook(f)
        d["파일"] = f.name
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


# ───────── 구분·시급·집계 ─────────
WAGE = {"PT": 10400, "PT리더": 12000}   # 주휴 미포함. PT리더(시트 표기 '리더') = 비용 + 기준시간 둘 다 본다
BASE_HOURS = 174                        # 월 소정(주5일·8시간). 직원·리더는 이 시간 대비로 본다
PAID_LEAVE = {"대휴": 8.0, "연차": 8.0, "반차": 4.0}   # 시트가 근무시간에 더하는 유급 휴가 (참고 열)
DEPT_ORDER = {d: i for i, d in enumerate(DEPTS)}


ROLE_FIXES = {"이아인": "사원", "지현구": "사원", "정소라": "사원"}   # 직급 칸이 비어 윗줄(SM)을 잘못 이어받은 사람. 사용자 확정(2026-11-22)
MANAGER_ROLES = {"GM", "점장", "부점장"}                                # 홀(FOH) 상주, BK·FK는 지원
# 직급 이력 (사용자 확정 2026-11-22): 시트 표기와 다르면 이쪽이 이긴다. (시작월, 끝월, 직급) — 월은 'YYYY-MM'
ROLE_HISTORY = {
    "박주형": [("0000-00", "2024-12", "사원"), ("2025-01", "9999-99", "PT")],     # 사원이었다가 PT로 변경
    "이수빈": [("0000-00", "9999-99", "AM")],
    "양영모": [("0000-00", "2025-06", "AM"), ("2025-07", "9999-99", "KM")],        # AM(부매니저) → KM
}
# 직급 체계: 점장(GM) > SM·KM > AM(부매니저) > TR > PT리더(정직원은 아니나 본사·점장이 선정) > 사원 > PT. 직급 없는 직원(중국인 등)은 맨 아래 직원.
RANK = {"GM": 1, "점장": 1, "부점장": 2, "SM": 3, "KM": 3, "AM": 4, "TR": 5, "PT리더": 6, "사원": 7, "PT": 8, "": 9, "지원": 9}


def tidy(df: pd.DataFrame) -> pd.DataFrame:
    """직급 괄호 표기 '(PT)'는 윗줄에서 이어받은 값이라는 뜻이다(직급확정=False). 직급 보정을 적용하고 구분(직원·PT·PT리더)과 직급순위를 붙인다.
    중국인은 '직급 없는 직원'(직급 빈칸), 시트의 '리더'는 'PT리더'로 부른다."""
    df = df.copy()
    role = df["직급"].str.strip("()")
    df["직급확정"] = ~df["직급"].str.startswith("(")
    role = role.where(role != "중국인", "").replace({"리더": "PT리더"})
    fix = df["이름"].map(ROLE_FIXES)
    unsure = ~df["직급확정"] & fix.notna()           # 직급이 적혀 있는 달은 그대로 두고, 비어 있던 줄만 확정값으로
    role, df["직급확정"] = role.where(~unsure, fix), df["직급확정"] | unsure
    for name, spans in ROLE_HISTORY.items():         # 직급 이력은 시트 표기보다 우선
        for start, end, r in spans:
            hit = (df["이름"] == name) & (df["월"] >= start) & (df["월"] <= end)
            role, df["직급확정"] = role.where(~hit, r), df["직급확정"] | hit
    df["직급"] = role
    df["구분"] = role.replace("", "직원").map(lambda r: r if r in WAGE else "직원")
    df["직급순위"] = role.map(RANK).fillna(9).astype(int)
    return df


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """같은 사람·같은 날 기록이 여러 부서 시트에 있으면 하나만 센다 ('집계' 열이 True인 줄).
    · 근무 기록이 있는 쪽이 우선 (다른 쪽이 '/'나 대휴여도 근무가 이긴다)
    · 점장급(GM·점장·부점장)은 홀 상주라 BK·FK 기록이 '지원 근무'다 → BK, FK, FOH 순으로 고른다
    · 그 밖의 사람은 그 달 근무일이 가장 많은 '주 부서'를 우선 (동점이면 FOH→BK→FK)
    코드가 서로 다른 날은 '중복코드상이'로 남겨 확인할 수 있게 한다."""
    df = df.copy()
    is_work = df["종류"].isin(["근무", "훈련"])
    main = (df[is_work].groupby(["월", "이름", "부서"]).size().rename("n").reset_index()
            .assign(o=lambda t: t["부서"].map(DEPT_ORDER)).sort_values(["월", "이름", "n", "o"], ascending=[True, True, False, True])
            .drop_duplicates(["월", "이름"]).set_index(["월", "이름"])["부서"])
    df["주부서"] = [main.get((m, n)) for m, n in zip(df["월"], df["이름"])]
    order = df["부서"].map(DEPT_ORDER)
    support_first = order.map({0: 2, 1: 0, 2: 1})                               # BK 0, FK 1, FOH 2
    other = (df["부서"] != df["주부서"]).astype(int) * 10 + order                  # 주 부서 먼저
    df["_p"] = (~is_work).astype(int) * 100 + support_first.where(df["직급"].isin(MANAGER_ROLES), other)
    nb = df[df["종류"] != "빈칸"]
    keep = nb.sort_values("_p", kind="stable").drop_duplicates(["월", "이름", "날짜"]).index
    df["집계"] = df.index.isin(keep)
    w = df[is_work]
    multi = w.groupby(["월", "이름", "날짜"])["부서"].transform("nunique") > 1
    differs = w.groupby(["월", "이름", "날짜"])["원문"].transform("nunique") > 1
    df["중복코드상이"] = df.index.isin(w[multi & differs].index)
    return df.drop(columns="_p")


def person_month(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["집계"]].sort_values("직급순위", kind="stable")   # 한 달에 직급이 둘이면 높은 쪽이 대표
    g = d.groupby(["월", "이름"])
    out = g.agg(구분=("구분", "first"), 직급=("직급", "first"), 직급순위=("직급순위", "min"), 주부서=("주부서", "first"),
                근무일수=("종류", lambda s: int(s.isin(["근무", "훈련"]).sum())), 근무시간=("근무시간", "sum"),
                대휴=("종류", lambda s: int((s == "대휴").sum())), 연차=("종류", lambda s: int((s == "연차").sum())),
                반차=("종류", lambda s: int((s == "반차").sum())), 예비군=("종류", lambda s: int((s == "예비군").sum()))).reset_index()
    out["유급휴가시간"] = out["대휴"] * 8.0 + out["연차"] * 8.0 + out["반차"] * 4.0
    out["기준시간대비"] = (out["근무시간"] - BASE_HOURS).where(out["구분"] != "PT")   # 직원·리더만. 양수 = 연장(OT) 추정
    return out


def weekly_paid_holiday(df: pd.DataFrame) -> pd.DataFrame:
    """PT·리더: 주(월~일)별 근무시간 → 주 15시간 이상이면 주휴 = min(주시간/40*8, 8)시간. 주휴는 그 주 일요일이 속한 달에 넣는다."""
    d = df[df["집계"] & df["구분"].isin(WAGE)].copy()
    d["일요일"] = pd.to_datetime(d["날짜"]) + pd.to_timedelta(6 - pd.to_datetime(d["날짜"]).dt.weekday, unit="D")
    w = d.groupby(["구분", "이름", "일요일"], as_index=False)["근무시간"].sum().rename(columns={"근무시간": "주시간"})
    w["주휴시간"] = (w["주시간"].clip(upper=40) / 40 * 8).where(w["주시간"] >= 15, 0.0).round(2)
    w["월"] = w["일요일"].dt.strftime("%Y-%m")
    return w


def hourly_cost(df: pd.DataFrame) -> pd.DataFrame:
    """PT·리더 월별 인건비 = (근무시간 + 주휴시간) × 시급. 근무시간은 날짜가 속한 달, 주휴시간은 일요일이 속한 달 기준이라 따로 합친다."""
    d = df[df["집계"] & df["구분"].isin(WAGE)]
    a = d.groupby(["월", "구분", "이름"], as_index=False)["근무시간"].sum()
    w = weekly_paid_holiday(df).groupby(["월", "구분", "이름"], as_index=False)["주휴시간"].sum()
    out = a.merge(w, how="outer", on=["월", "구분", "이름"]).fillna(0.0)
    out["시급"] = out["구분"].map(WAGE)
    out["인건비"] = ((out["근무시간"] + out["주휴시간"]) * out["시급"]).round().astype(int)
    return out.sort_values(["월", "구분", "이름"]).reset_index(drop=True)


def roster_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """입퇴사 후보. 달 안에서 '첫 기록 이전 빈칸'은 입사 전, '마지막 근무 이후 휴무·빈칸'은 퇴사 후 후보.
    다음 달에 다시 나오면 퇴사가 아니라 휴가로 본다. 확정은 사용자가 한다."""
    rows = []
    d = df[df["집계"] | (df["종류"] == "빈칸")]
    months = sorted(df["월"].unique())
    for (m, n), g in d.groupby(["월", "이름"]):
        g = g.sort_values("날짜")
        rec, wk = g[g["종류"] != "빈칸"], g[g["종류"].isin(["근무", "훈련"])]
        if rec.empty:
            continue
        rows.append({"월": m, "이름": n, "첫기록일": rec["날짜"].min(), "마지막기록일": rec["날짜"].max(),
                     "첫근무일": wk["날짜"].min() if len(wk) else None, "마지막근무일": wk["날짜"].max() if len(wk) else None, "달길이": g["날짜"].max()})
    t = pd.DataFrame(rows)
    first = t.groupby("이름")["월"].min(); last = t.groupby("이름")["월"].max()
    t["입사후보"] = (t["월"] == t["이름"].map(first)) & (t["월"] != months[0])   # 데이터 첫 달 사람은 입사 시점을 알 수 없다
    t["퇴사후보"] = (t["월"] == t["이름"].map(last)) & (t["월"] != months[-1])
    t["입사일추정"] = t["첫기록일"].where(t["입사후보"])
    t["퇴사일추정"] = t["마지막근무일"].where(t["퇴사후보"])
    return t[t["입사후보"] | t["퇴사후보"]].sort_values(["이름", "월"]).drop(columns=["달길이"]).reset_index(drop=True)


def build(src, out) -> dict:
    """원본 .xls 폴더 → 정제 CSV 6개 (전화번호·사번은 제외). 원문은 그대로 두고 판정 열만 더한다."""
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    df = dedupe(tidy(parse_dir(src)))
    # 사번 칸은 전화번호라 내보내지 않는다
    outs = {"근무일별": df.drop(columns=["시트근무시간", "사번"]), "인원월별": person_month(df), "PT리더_인건비": hourly_cost(df),
            "입퇴사_후보": roster_candidates(df), "미해석": df[df["종류"] == "미해석"][["월", "부서", "이름", "날짜", "원문"]],
            "부서중복_코드상이": df[df["중복코드상이"]][["월", "이름", "날짜", "부서", "원문", "주부서", "집계"]]}
    for k, v in outs.items():
        v.to_csv(out / f"{k}.csv", index=False, encoding="utf-8-sig")
    return {k: len(v) for k, v in outs.items()}
