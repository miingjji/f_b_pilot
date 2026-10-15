"""리포트형 시트(제목행·여러 줄 머리글·합계행이 섞인 시트)를 다루는 공통 도구."""
import math
import re

import pandas as pd

REPORT_COLUMNS = ["열", "채운 개수", "규칙", "채운 값"]


class UnhandledMissingError(ValueError):
    """규칙으로 설명되지 않는 결측치가 남았을 때."""


def label(text) -> str:
    """머리글 문자열 정규화: '품목코드\\n(RMS)' -> '품목코드_RMS', '중량(g)' -> '중량_g', '과세/면세' -> '과세면세'."""
    s = re.sub(r"\\n|\n", "", str(text)).strip()
    s = re.sub(r"\(([^)]*)\)", r"_\1", s)
    return re.sub(r"[\s/]+", "", s)


def find_row(df: pd.DataFrame, col: int, value: str, start: int = 0):
    """col 열에서 value(정규화 비교)와 같은 첫 행의 위치. 없으면 None."""
    target = label(value)
    for i in range(start, len(df)):
        v = df.iat[i, col]
        if pd.notna(v) and label(v) == target:
            return i
    return None


def flatten_header(df: pd.DataFrame, header_row: int, last_col: int, overrides: dict | None = None) -> list:
    """2줄 머리글(상단=그룹/항목, 하단=세부)을 한 줄 이름으로. 이름 없는 열은 None.

    상단이 있는 열이 그룹을 시작하고, 상단이 비어 있고 하단만 있는 열은 앞 그룹에 속한다.
    예: ['재고실사', NaN] / ['수량', '중량(g)'] -> '재고실사_수량', '재고실사_중량_g'
    """
    overrides = overrides or {}
    names, group = [], None
    for j in range(last_col + 1):
        top, sub = df.iat[header_row, j], df.iat[header_row + 1, j]
        if pd.notna(top):
            group = label(top)
            name = f"{group}_{label(sub)}" if pd.notna(sub) else group
        elif pd.notna(sub):
            name = f"{group}_{label(sub)}" if group else label(sub)
        else:
            name = None
        names.append(overrides.get(j, name))
    return names


def fill(df: pd.DataFrame, col: str, value, mask, rule: str, report: list, shown=None):
    """mask 인 칸을 value(값 또는 같은 인덱스의 Series)로 채우고 처리 내역을 기록."""
    n = int(mask.sum())
    if n:
        df.loc[mask, col] = value[mask] if isinstance(value, pd.Series) else value
        report.append({"열": col, "채운 개수": n, "규칙": rule, "채운 값": str(shown if shown is not None else value)})


def ensure_no_missing(df: pd.DataFrame):
    left = df.isna().sum()
    left = left[left > 0]
    if len(left):
        raise UnhandledMissingError("규칙이 없는 결측치가 남았습니다: " + ", ".join(f"{c} {int(n)}개" for c, n in left.items()))


def make_check(name: str, expected, actual, ok: bool | None = None, note: bool = False) -> dict:
    """검증 결과 한 줄. note=True 면 '원본 데이터의 차이를 알리는 참고'라 실패해도 정제 오류로 취급하지 않는다."""
    close = math.isclose(float(expected), float(actual), rel_tol=1e-9, abs_tol=1e-6)
    return {"항목": name, "기대": expected, "실제": actual, "ok": close if ok is None else ok, "참고": note}


def to_numbers(df: pd.DataFrame, cols):
    for c in cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="raise")


def take_block(raw, names, start, end, last_col, keep=()):
    """상세표를 잘라 이름을 붙이고, 이름 없는 열/전부 빈 열은 버린다 (keep 은 규칙이 채우는 열이라 유지).
    반환: (표, 버린 열 목록)."""
    body = raw.iloc[start:end, : last_col + 1].copy()
    body.columns = [n if n else f"__열{j}" for j, n in enumerate(names)]
    dropped = []
    for c in list(body.columns):
        if c.startswith("__열") or (body[c].isna().all() and c not in keep):
            if not c.startswith("__열"):
                dropped.append(c)
            body = body.drop(columns=c)
    return body.reset_index(drop=True), dropped


def _is_number(s: str) -> bool:
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def notes_above(raw: pd.DataFrame, header_row: int) -> list[str]:
    """머리글 위의 제목·주석 문구. 숫자뿐인 칸(요약 합계 등)은 메모가 아니라서 뺀다."""
    out: list[str] = []
    for i in range(header_row):
        for v in raw.iloc[i]:
            if pd.notna(v):
                s = str(v).replace("\\n", " ").strip()
                if s and not _is_number(s) and s not in out:
                    out.append(s)
    return out
