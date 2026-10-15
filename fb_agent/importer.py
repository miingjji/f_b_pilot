"""실사 재고 파일(CSV/엑셀) -> 품목별 총 g.

지원 형식
- 열 분리형: 품목 | BOX | PK | 낱개(g) | EA   (필요한 열만 있어도 됨)
- 자유 입력형: 품목 | 재고   (예: "1BOX 2pk 300g")
- 세로형: 품목 | 수량 | 단위   (같은 품목이 여러 행이면 합산)
"""
import difflib
import io
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from converter import parse_count, to_boxes, unit_to_grams
from data import ITEMS
from errors import InvalidInputError

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
HEADER_SCAN_ROWS = 10  # 제목 행이 앞에 있는 엑셀 대응

# 표준 열 -> 헤더 별칭 (정규화 후 비교)
HEADER_ALIASES = {
    "item": {"품목", "품목명", "상품", "상품명", "자재", "자재명", "item", "name", "itemname"},
    "code": {"품목코드", "코드", "자재코드", "itemcode", "code"},
    "box": {"box", "박스", "상자", "bx"},
    "pk": {"pk", "팩", "봉", "봉지", "pack"},
    "loose": {"낱개(g)", "낱개", "낱개(기본단위)", "잔량", "잔량(g)", "g", "ml", "gram", "그램"},
    "ea": {"ea", "개", "낱개(ea)"},
    "text": {"재고", "실사", "실사재고", "재고량", "count", "stock"},
    "qty": {"수량", "qty", "quantity"},
    "unit": {"단위", "unit"},
}
UNIT_COLS = ("box", "pk", "loose", "ea")
COL_UNIT = {"box": "BOX", "pk": "PK", "ea": "EA"}   # 낱개(loose)는 품목의 기본단위(g·ml·개 …)로 센다


def template_csv(items) -> str:
    """업로드 양식: 마스터의 모든 품목을 현재재고량(BOX/PK/낱개)과 함께."""
    lines = ["품목코드,품목명,BOX,PK,낱개"]
    for it in items.values():
        box, pk, loose = to_boxes(it, it.current_stock or 0)
        lines.append(f"{it.code},{it.name},{box},{pk},{round(loose, 2):g}")
    return "\n".join(lines) + "\n"


TEMPLATE_CSV = template_csv(ITEMS)


@dataclass
class ImportIssue:
    row: int          # 파일 기준 행 번호(1부터, 헤더 포함; 텍스트 메모는 줄 번호)
    item: str
    message: str


@dataclass
class ImportResult:
    grams: dict = field(default_factory=dict)      # 품목명 -> 총 g
    errors: list = field(default_factory=list)     # list[ImportIssue]
    warnings: list = field(default_factory=list)   # list[ImportIssue]
    missing: list = field(default_factory=list)    # 파일에 없던 등록 품목

    @property
    def ok(self) -> bool:
        return not self.errors


def _norm(s) -> str:
    """공백 제거 + 전각/반각 통일 + 소문자."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s))).lower()


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InvalidInputError("파일 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949 CSV만 지원).")


def _sniff(raw: bytes) -> str:
    """확장자 대신 내용으로 형식 판별."""
    if raw[:4] == b"PK\x03\x04":
        return "ods" if b"application/vnd.oasis.opendocument.spreadsheet" in raw[:300] else "xlsx"
    if raw[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        return "xls"
    if raw[:5] == b"%PDF-" or raw[:4] == b"\x89PNG" or raw[:3] == b"\xff\xd8\xff":
        raise InvalidInputError("PDF·이미지 파일은 지원하지 않습니다. 엑셀/CSV/JSON/텍스트로 올려 주세요.")
    head = raw.lstrip()[:1]
    return "json" if head in (b"{", b"[") else "text"


def _json_table(raw: bytes) -> pd.DataFrame:
    import json
    try:
        data = json.loads(_decode(raw))
    except ValueError as e:
        raise InvalidInputError(f"JSON 형식 오류: {e}") from e
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], (list, dict)):
        data = data["items"]
    if isinstance(data, dict):  # {"짜사이": {"PK": 1} | "1pk 300g"}
        recs = [{"품목": k, **(v if isinstance(v, dict) else {"재고": v})} for k, v in data.items()]
    elif isinstance(data, list) and all(isinstance(r, dict) for r in data):
        recs = data
    else:
        raise InvalidInputError("JSON은 객체 목록 또는 {품목: 값} 형태여야 합니다.")
    cols = list(dict.fromkeys(k for r in recs for k in r))
    rows = [[("" if r.get(c) is None else str(r.get(c))) for c in cols] for r in recs]
    return pd.DataFrame([cols, *rows], dtype=str)


_LINE = re.compile(r"^\s*[-*\u2022]?\s*(?P<name>[^\d:=\t,]*?[^\d\s:=\t,])\s*[:=\t,]?\s*(?P<qty>\d.*?)\s*$")


def _text_candidates(raw: bytes):
    """텍스트 -> [(표, 행 번호 보정)]. 표 형식을 먼저 시도하고, 안 되면 줄 단위 메모로 해석."""
    text = _decode(raw)
    lines = text.splitlines()
    out = []
    if any(ln.lstrip().startswith("|") for ln in lines):  # 마크다운 표
        rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines
                if ln.strip() and not re.fullmatch(r"[\s|:\-]+", ln)]
        width = max((len(r) for r in rows), default=0)
        out.append((pd.DataFrame([r + [""] * (width - len(r)) for r in rows], dtype=str), 0))
    try:
        out.append((pd.read_csv(io.StringIO(text), sep=None, engine="python", header=None, dtype=str,
                                keep_default_na=False, skip_blank_lines=False), 0))
    except Exception:
        pass
    memo = [["품목", "재고"]]  # 헤더 1행 추가 -> 원본 줄 번호는 보정 -1
    for ln in lines:
        m = _LINE.match(ln)
        memo.append([m["name"], m["qty"]] if m else ([ln.strip(), ""] if ln.strip() else ["", ""]))
    out.append((pd.DataFrame(memo, dtype=str), -1))
    return out


def _read_tables(name: str, raw: bytes):
    """파일 -> [(헤더 없는 문자열 표, 행 번호 보정)] 후보들."""
    if not raw.strip():
        raise InvalidInputError("빈 파일입니다.")
    if len(raw) > MAX_BYTES:
        raise InvalidInputError(f"파일이 너무 큽니다 (최대 {MAX_BYTES // 1024 // 1024}MB).")
    kind = _sniff(raw)
    try:
        if kind in ("xlsx", "xls", "ods"):  # 모든 시트를 후보로
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, header=None, dtype=str,
                                   keep_default_na=False, engine={"ods": "odf"}.get(kind))
            tables = [(df, 0) for df in sheets.values()]
        elif kind == "json":
            tables = [(_json_table(raw), 0)]
        else:
            tables = _text_candidates(raw)
    except InvalidInputError:
        raise
    except Exception as e:  # 손상 파일, 암호 걸린 파일 등
        raise InvalidInputError(f"파일을 읽을 수 없습니다: {e}") from e
    for df, _ in tables:
        if len(df) > MAX_ROWS:
            raise InvalidInputError(f"행이 너무 많습니다 (최대 {MAX_ROWS}행).")
    return tables


def _find_header(df: pd.DataFrame):
    """앞쪽 몇 행에서 '품목' 열이 있는 헤더 행을 찾아 (행 인덱스, {표준열: 열 인덱스})."""
    for i in range(min(HEADER_SCAN_ROWS, len(df))):
        cols = {}
        for j, cell in enumerate(df.iloc[i]):
            key = _norm(cell)
            for std, aliases in HEADER_ALIASES.items():
                if key in {_norm(a) for a in aliases} and std not in cols:
                    cols[std] = j
        if ("item" in cols or "code" in cols) and len(cols) > 1:
            return i, cols
    raise InvalidInputError(
        "헤더를 찾을 수 없습니다. '품목'(또는 '품목코드') 열과 함께 BOX/PK/낱개 또는 '재고' 열이 필요합니다.")


def _to_number(cell, label):
    """셀 -> float. 빈 칸은 None. '1,000' 허용, 음수/NaN/문자는 오류."""
    s = unicodedata.normalize("NFKC", str(cell)).strip().replace(",", "")
    if s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        raise InvalidInputError(f"{label}: 숫자가 아닙니다 ({cell!r})") from None
    if v != v or v in (float("inf"), float("-inf")):
        raise InvalidInputError(f"{label}: 유효하지 않은 값입니다 ({cell!r})")
    if v < 0:
        raise InvalidInputError(f"{label}: 음수는 입력할 수 없습니다 ({cell!r})")
    return v


def _row_grams(item, row, cols):
    """한 행 -> g. 사용할 수 있는 입력이 하나도 없으면 None."""
    total, used = 0.0, False
    for col in UNIT_COLS:
        if col in cols:
            v = _to_number(row.iloc[cols[col]], col.upper())
            if v is not None:
                total += unit_to_grams(item, v, item.base_unit if col == "loose" else COL_UNIT[col])
                used = True
    if "text" in cols and str(row.iloc[cols["text"]]).strip():
        total += parse_count(item, row.iloc[cols["text"]])
        used = True
    if "qty" in cols:
        cell = str(row.iloc[cols["qty"]]).strip()
        if cell:
            unit = str(row.iloc[cols["unit"]]).strip() if "unit" in cols else ""
            if unit:
                total += unit_to_grams(item, _to_number(cell, "수량"), unit)
            else:
                total += parse_count(item, cell)  # '1pk 300g' 형태 허용, 단위 없는 숫자는 오류
            used = True
    return total if used else None


def parse_inventory_file(name: str, raw: bytes, items: dict) -> ImportResult:
    """업로드 파일 -> ImportResult. 파일 자체가 읽히지 않으면 InvalidInputError."""
    last_err = None
    for df, offset in _read_tables(name, raw):  # 헤더가 유효한 첫 표(시트)를 사용
        try:
            head, cols = _find_header(df)
        except InvalidInputError as e:
            last_err = e
            continue
        if any(c in cols for c in (*UNIT_COLS, "text", "qty")):
            break
        last_err = InvalidInputError("수량 열이 없습니다. BOX, PK, 낱개(g), 재고 중 하나 이상이 필요합니다.")
    else:
        raise last_err

    lookup = {_norm(n): n for n in items}
    by_code = {_norm(it.code): n for n, it in items.items() if it.code}
    res = ImportResult()
    seen = {}  # 품목 -> 처음 나온 행 번호

    for i in range(head + 1, len(df)):
        row, rownum = df.iloc[i], i + 1 + offset
        raw_name = str(row.iloc[cols["item"]]).strip() if "item" in cols else ""
        raw_code = str(row.iloc[cols["code"]]).strip() if "code" in cols else ""
        if not raw_name and not raw_code and not any(str(c).strip() for c in row):
            continue  # 완전히 빈 행
        if not raw_name and not raw_code:
            res.errors.append(ImportIssue(rownum, "", "품목명(또는 품목코드)이 비어 있습니다."))
            continue
        key = lookup.get(_norm(raw_name)) or by_code.get(_norm(raw_code))   # 이름 우선, 없으면 코드
        raw_name = raw_name or raw_code
        if key is None:
            hint = difflib.get_close_matches(raw_name, list(items), n=1, cutoff=0.5)
            tip = f" (혹시 '{hint[0]}'?)" if hint else ""
            res.errors.append(ImportIssue(rownum, raw_name, f"등록되지 않은 품목입니다{tip}"))
            continue
        try:
            g = _row_grams(items[key], row, cols)
        except InvalidInputError as e:
            res.errors.append(ImportIssue(rownum, key, str(e)))
            continue
        if g is None:
            res.warnings.append(ImportIssue(rownum, key, "수량이 비어 있어 건너뜁니다."))
            continue
        if key in seen:
            res.warnings.append(ImportIssue(rownum, key, f"{seen[key]}행과 중복되어 합산했습니다."))
        else:
            seen[key] = rownum
        res.grams[key] = res.grams.get(key, 0.0) + g

    if offset == -1 and not res.grams:  # 줄 단위 메모로 추측했는데 읽힌 수량이 없음
        raise InvalidInputError("파일 형식을 인식할 수 없습니다. 표(품목/수량 열) 또는 '품목 수량' 줄 형태가 필요합니다.")
    res.missing = [n for n in items if n not in res.grams and n not in {e.item for e in res.errors}]
    return res
