"""품목·거래처 마스터 데이터 로더 (Streamlit 비의존).

data/suppliers.csv, data/items.csv 를 읽어 Supplier / Item 으로 만든다. 엑셀에서 편집해도 되며
(UTF-8 또는 CP949), 잘못된 값은 행 번호와 함께 InvalidInputError 로 알려준다.
"""
import csv
import io
import json
from pathlib import Path

from errors import InvalidInputError
from models import BASE_UNITS, NO_DATA, Item, Supplier

DATA_DIR = Path(__file__).resolve().parent / "data"
WEEKDAYS = "월화수목금토일"

SUPPLIER_COLUMNS = ["거래처명", "발주요일", "기본리드타임", "취급분야"]
ITEM_COLUMNS = ["품목코드", "품목명", "대분류", "중분류", "기본단위", "PK당수량", "BOX당PK", "EA당수량",
                "일소비량", "안전재고량", "현재재고량", "리드타임", "거래처"]   # 선택 열: 업종
CUISINES = ("공통", "한식", "중식", "일식", "양식", "카페")


def _read_rows(path: Path, required: list[str]) -> list[tuple[int, dict]]:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in required if c not in (reader.fieldnames or [])]
    if missing:
        raise InvalidInputError(f"{Path(path).name}: 필수 열이 없습니다 — {', '.join(missing)}")
    return [(i, {k: (v or "").strip() for k, v in row.items()}) for i, row in enumerate(reader, start=2)]


def _num(row: dict, col: str, where: str, *, default=None, integer=False):
    s = row.get(col, "").replace(",", "")
    if s == "":
        if default is not None:
            return default
        raise InvalidInputError(f"{where}: '{col}' 값이 비어 있습니다.")
    try:
        v = float(s)
    except ValueError:
        raise InvalidInputError(f"{where}: '{col}'이(가) 숫자가 아닙니다 ({s!r})") from None
    if integer:
        if v != int(v):
            raise InvalidInputError(f"{where}: '{col}'은(는) 정수여야 합니다 ({s!r})")
        return int(v)
    return v


def load_suppliers(path: Path = DATA_DIR / "suppliers.csv") -> dict[str, Supplier]:
    out = {}
    for line, row in _read_rows(path, SUPPLIER_COLUMNS):
        where = f"suppliers.csv {line}행"
        name = row["거래처명"]
        if not name:
            raise InvalidInputError(f"{where}: 거래처명이 비어 있습니다.")
        if name in out:
            raise InvalidInputError(f"{where}: 거래처명이 중복되었습니다 ({name})")
        days = set()
        for ch in row["발주요일"]:
            if ch not in WEEKDAYS:
                raise InvalidInputError(f"{where}: 발주요일에 알 수 없는 글자 {ch!r} (월화수목금토일)")
            days.add(WEEKDAYS.index(ch))
        lead = None if row["기본리드타임"] == "" else _num(row, "기본리드타임", where, integer=True)      # 비어 있으면 실제 데이터 없음
        out[name] = Supplier(name, frozenset(days), lead)
    return out


def load_items(suppliers: dict[str, Supplier], path: Path = DATA_DIR / "items.csv") -> dict[str, Item]:
    out, codes = {}, set()
    for line, row in _read_rows(path, ITEM_COLUMNS):
        where = f"items.csv {line}행"
        code, name = row["품목코드"], row["품목명"]
        if not code or not name:
            raise InvalidInputError(f"{where}: 품목코드와 품목명은 필수입니다.")
        if code in codes:
            raise InvalidInputError(f"{where}: 품목코드가 중복되었습니다 ({code})")
        if name in out:
            raise InvalidInputError(f"{where}: 품목명이 중복되었습니다 ({name})")
        if row["거래처"] not in suppliers:
            raise InvalidInputError(f"{where}: 등록되지 않은 거래처입니다 ({row['거래처']!r})")
        base = row["기본단위"] or "g"
        if base not in BASE_UNITS:
            raise InvalidInputError(f"{where}: 기본단위는 {', '.join(BASE_UNITS)} 중 하나 ({base!r})")
        cuisines = tuple(c for c in row.get("업종", "").split("|") if c) or ("공통",)
        bad = [c for c in cuisines if c not in CUISINES]
        if bad:
            raise InvalidInputError(f"{where}: 알 수 없는 업종 {bad} (허용: {', '.join(CUISINES)})")
        lead = row["리드타임"]
        try:
            out[name] = Item(
                name=name, code=code, major=row["대분류"], mid=row["중분류"], base_unit=base,
                pk_weight_g=_num(row, "PK당수량", where), box_pk=_num(row, "BOX당PK", where, default=1),
                # g·ml 품목은 EA(낱개)를 선택적으로, 개수 품목은 기본단위 1개가 곧 EA
                ea_weight_g=_num(row, "EA당수량", where, default=0 if base in ("g", "ml") else 1),
                daily_usage_g=_num(row, "일소비량", where, default=0.0), usage_known=row["일소비량"] != "",
                supplier=suppliers[row["거래처"]],
                safety_stock_g=_num(row, "안전재고량", where) if row["안전재고량"] != "" else None,
                current_stock=_num(row, "현재재고량", where) if row["현재재고량"] != "" else None,
                lead_time_override=None if lead == "" else _num(row, "리드타임", where, integer=True),
                cuisines=cuisines)
        except InvalidInputError as e:
            raise InvalidInputError(f"{where}: {e}") from None
        codes.add(code)
    if not out:
        raise InvalidInputError("items.csv: 품목이 하나도 없습니다.")
    return out


def load_master(directory: Path = DATA_DIR) -> tuple[dict[str, Supplier], dict[str, Item]]:
    suppliers = load_suppliers(Path(directory) / "suppliers.csv")
    return suppliers, load_items(suppliers, Path(directory) / "items.csv")


# ---- 내보내기 (화면 표시·CSV·JSON 다운로드 공용) ----
def item_rows(items) -> list[dict]:
    """품목 마스터를 요구 항목 순서의 행으로: 코드, 품목명, 대/중분류, 규격, 안전재고, 현재재고, 리드타임, 거래처."""
    return [{
        "품목코드": it.code, "품목명": it.name, "대분류": it.major, "중분류": it.mid,
        "기본규격/단위": it.spec, "기본단위": it.base_unit,
        "안전재고량": it.safety_stock_g, "현재재고량": it.current_stock,
        "리드타임(일)": it.lead_time_days if it.lead_time_days is not None else NO_DATA, "거래처": it.supplier.name,
    } for it in items]


def to_json(items) -> str:
    return json.dumps(item_rows(items), ensure_ascii=False, indent=2)
