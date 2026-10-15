"""마크다운(pandas/엑셀 덤프) 파일 -> 시트별 DataFrame.

파일 형식: `## 시트명` 제목 아래에 `| a | b |` 표가 오는 구조. 시트마다 열 수가 다르므로 시트별로 따로 읽는다.
모든 값은 문자열로 읽고, `NaN` 문자열과 빈 칸은 pd.NA 로 바꾼다 (형 변환은 정제 단계에서 한다).
"""
import re
from pathlib import Path

import pandas as pd

_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")
_SEPARATOR = re.compile(r"^:?-{3,}:?$")
NA_TOKENS = {"NaN", ""}


def _unescape(s: str) -> str:
    return _ESCAPE.sub(r"\1", s)


def _split_row(line: str) -> list[str]:
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [_unescape(c.strip()) for c in _UNESCAPED_PIPE.split(inner)]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR.match(c) for c in cells)


def read_sheets(path, only: str | None = None) -> dict[str, pd.DataFrame]:
    """파일의 모든 시트(또는 only 로 지정한 한 시트)를 {시트명: DataFrame} 으로."""
    tables: dict[str, list] = {}
    current = None
    with open(Path(path), encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if line.startswith("## "):
                current = line[3:].strip()
                tables[current] = [None, []]               # [헤더, 행들]
            elif line.startswith("|") and current is not None:
                if only is not None and current != only:
                    continue
                cells = _split_row(line)
                header, rows = tables[current]
                if header is None:
                    tables[current][0] = cells
                elif _is_separator(cells):
                    continue
                elif len(cells) != len(header):
                    raise ValueError(f"{current}: {lineno}번째 줄의 열이 {len(cells)}개입니다 (헤더는 {len(header)}개)")
                else:
                    rows.append(cells)
    out = {}
    for name, (header, rows) in tables.items():
        if only is not None and name != only:
            continue
        df = pd.DataFrame(rows, columns=header or [], dtype=object)
        out[name] = df.replace({tok: pd.NA for tok in NA_TOKENS})
    return out


def read_sheet(path, name: str) -> pd.DataFrame:
    """한 시트만 읽는다 (큰 파일에서 필요한 시트만 빠르게)."""
    sheets = read_sheets(path, only=name)
    if name not in sheets:
        raise KeyError(f"시트를 찾을 수 없습니다: {name!r}")
    return sheets[name]
