"""스케줄·인건비 조회 (Streamlit 비의존). 값은 모두 `python -m labor` 로 만든 data/cleaned/스케줄/*.csv 에서 읽는다 (가상 값 없음).

· 직원(PT·PT리더 외)은 연봉이라 비용 없이 근무시간만, PT·PT리더는 시급 기반 변동 인건비(주휴 포함)를 낸다.
· 주휴는 그 주 일요일이 속한 달에 넣는다. 자료의 첫 주·마지막 주는 앞뒤 달이 없어 주휴가 모자랄 수 있다.
"""
from functools import lru_cache
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent / "data" / "cleaned" / "스케줄"
DOW = "월화수목금토일"
DEPTS = ("전체", "FOH", "BK", "FK")


def available() -> bool:
    return all((DIR / f).exists() for f in ("근무일별.csv", "인원월별.csv", "PT리더_인건비.csv"))


@lru_cache(maxsize=8)
def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(DIR / f"{name}.csv")


def _t(name: str) -> pd.DataFrame:
    return _read(name).copy()


def months() -> list[str]:
    return sorted(_read("인원월별")["월"].unique())


def schedule_grid(ym: str, dept: str = "전체") -> pd.DataFrame:
    """그 달 스케줄표: 직급 순서대로 한 사람이 한 줄, 날짜 열에는 시트의 근무 코드 그대로('/'=휴무). 부서는 그 달 주 부서 기준."""
    d = _t("근무일별")
    d = d[(d["월"] == ym) & d["집계"]]
    if dept != "전체":
        d = d[d["주부서"] == dept]
    if d.empty:
        return pd.DataFrame()
    d = d.assign(날짜=pd.to_datetime(d["날짜"]))
    d["일"] = d["날짜"].map(lambda x: f"{x.day}({DOW[x.weekday()]})")
    cols = list(dict.fromkeys(d.sort_values("날짜")["일"]))
    wide = d.pivot_table(index=["직급순위", "직급", "이름", "주부서"], columns="일", values="원문", aggfunc="first").reindex(columns=cols).fillna("")
    pm = _t("인원월별")
    pm = pm[pm["월"] == ym].set_index("이름")
    out = wide.reset_index().sort_values(["직급순위", "이름"]).drop(columns="직급순위")
    out["근무일수(일)"] = out["이름"].map(pm["근무일수"]).fillna(0).astype(int)
    out["근무시간(시간)"] = out["이름"].map(pm["근무시간"]).fillna(0.0)
    return out.rename(columns={"주부서": "부서"}).reset_index(drop=True)


def staff_hours(ym: str) -> pd.DataFrame:
    """직원(연봉)·PT리더의 그 달 근무시간. 기준 174시간 대비 +는 연장(OT) 추정. 직급 순."""
    pm = _t("인원월별")
    pm = pm[(pm["월"] == ym) & pm["구분"].isin(["직원", "PT리더"])].sort_values(["직급순위", "이름"])
    out = pm[["직급", "이름", "근무일수", "근무시간", "유급휴가시간", "기준시간대비"]].copy()
    out["직급"] = out["직급"].replace("", "(직급 없음)")
    return out.rename(columns={"근무일수": "근무일수(일)", "근무시간": "근무시간(시간)", "유급휴가시간": "유급휴가(시간)", "기준시간대비": "174시간 대비(시간)"}).reset_index(drop=True)


def hourly_pay(ym: str) -> pd.DataFrame:
    """PT·PT리더의 그 달 근무시간·주휴시간·시급·인건비 (인건비 많은 순)."""
    c = _t("PT리더_인건비")
    c = c[c["월"] == ym].sort_values("인건비", ascending=False)
    out = c[["구분", "이름", "근무시간", "주휴시간", "시급", "인건비"]]
    return out.rename(columns={"근무시간": "근무시간(시간)", "주휴시간": "주휴(시간)", "시급": "시급(원)", "인건비": "인건비(원)"}).reset_index(drop=True)


def monthly_cost() -> pd.DataFrame:
    """월별 변동 인건비: 월, PT(원), PT리더(원), 합계(원)."""
    c = _t("PT리더_인건비").pivot_table(index="월", columns="구분", values="인건비", aggfunc="sum").fillna(0)
    c = c.reindex(columns=["PT", "PT리더"], fill_value=0)
    c["합계"] = c.sum(axis=1)
    return c.reset_index().rename(columns={"PT": "PT(원)", "PT리더": "PT리더(원)", "합계": "합계(원)"})


def month_summary(sales_by_month: pd.DataFrame) -> pd.DataFrame:
    """월별 변동 인건비 + 순매출 + 변동 인건비율(%). 매출이 있는 달만 비율을 낸다. sales_by_month: month, sales 열."""
    c = monthly_cost()
    c = c[c["월"].isin(months())]          # 스케줄이 있는 달만 (마지막 주 주휴가 걸친 다음 달 0원 행 제외)
    c = c.merge(sales_by_month[["month", "sales"]].rename(columns={"month": "월", "sales": "순매출(원)"}), on="월", how="left")
    c["변동 인건비율(%)"] = (c["합계(원)"] / c["순매출(원)"] * 100).where(c["순매출(원)"] > 0).round(1)
    staff = _t("인원월별")
    staff = staff[staff["구분"] == "직원"].groupby("월")["근무시간"].sum().rename("직원 근무시간(시간)")
    return c.merge(staff, on="월", how="left")


def roster(ym: str | None = None) -> pd.DataFrame:
    """입퇴사 후보(추정). 확정은 사용자가 한다. ym 을 주면 그 달 후보만."""
    r = _t("입퇴사_후보")
    if ym:
        r = r[r["월"] == ym]
    r = r.assign(구분=lambda t: t.apply(lambda x: "입사 후보" if x["입사후보"] and not x["퇴사후보"] else "퇴사 후보" if x["퇴사후보"] and not x["입사후보"] else "입사·퇴사 후보", axis=1))
    return r[["월", "이름", "구분", "입사일추정", "퇴사일추정", "첫근무일", "마지막근무일"]].sort_values(["월", "이름"]).reset_index(drop=True)
