import math
import re
from errors import InvalidInputError
from models import Item

# 단위 별칭(소문자 기준) -> 표준 단위
UNIT_ALIASES = {
    "g": "g", "gram": "g", "그램": "g", "그람": "g",
    "kg": "kg", "킬로": "kg", "킬로그램": "kg",
    "pk": "PK", "pack": "PK", "팩": "PK", "봉": "PK", "봉지": "PK",
    "box": "BOX", "bx": "BOX", "박스": "BOX", "상자": "BOX", "case": "BOX",
    "ea": "EA", "개": "EA", "낱개": "EA",
}


def _check(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInputError(f"{label}: 숫자가 아닙니다 ({value!r})")
    if math.isnan(value) or math.isinf(value):
        raise InvalidInputError(f"{label}: 유효하지 않은 값입니다 ({value})")
    if value < 0:
        raise InvalidInputError(f"{label}: 음수는 입력할 수 없습니다 ({value})")
    return float(value)


def normalize_unit(unit: str) -> str:
    key = str(unit).strip().lower()
    if key not in UNIT_ALIASES:
        raise InvalidInputError(f"알 수 없는 단위: {unit!r} (지원: BOX, PK, EA, g, kg)")
    return UNIT_ALIASES[key]


def unit_to_grams(item: Item, qty, unit: str) -> float:
    """수량 + 단위 -> g (품목별 BOX/PK/EA 무게 기준)."""
    q = _check(qty, f"{unit} 수량")
    u = normalize_unit(unit)
    if u == "g":
        return q
    if u == "kg":
        return q * 1000
    if u == "PK":
        return q * item.pk_weight_g
    if u == "BOX":
        return q * item.box_weight_g
    if item.ea_weight_g <= 0:  # EA
        raise InvalidInputError(f"{item.name}: EA 단위 무게가 등록되지 않았습니다.")
    return q * item.ea_weight_g


def sum_to_grams(item: Item, entries) -> float:
    """[(수량, 단위), ...] 합계를 g로 환산."""
    return sum(unit_to_grams(item, q, u) for q, u in entries)


_TOKEN = re.compile(r"\s*(-?\d+(?:[.,]\d+)?)\s*([A-Za-z가-힣]+)\s*")


def parse_count(item: Item, text: str) -> float:
    """'2BOX 1pk 300g' 같은 자유 입력 문자열 -> g."""
    text = str(text).strip()
    if not text:
        raise InvalidInputError("빈 입력입니다.")
    pos, entries = 0, []
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise InvalidInputError(f"해석할 수 없는 입력: {text[pos:]!r}")
        entries.append((float(m.group(1).replace(",", ".")), m.group(2)))
        pos = m.end()
    return sum_to_grams(item, entries)


def to_grams(item: Item, packs=0, loose_g=0, boxes=0) -> float:
    """실사 입력(BOX + PK + 낱개 g) -> 총 g."""
    return sum_to_grams(item, [(boxes, "BOX"), (packs, "PK"), (loose_g, "g")])


def to_packs(item: Item, grams) -> tuple[int, float, float]:
    """총 g -> (완전 PK 수, 잔량 g, 소수 PK)."""
    g = _check(grams, "재고(g)")
    full, rest = divmod(g, item.pk_weight_g)
    return int(full), rest, g / item.pk_weight_g


def to_boxes(item: Item, grams) -> tuple[int, int, float]:
    """총 g -> (BOX, 나머지 PK, 잔량 g)."""
    g = _check(grams, "재고(g)")
    boxes, rest = divmod(g, item.box_weight_g)
    pk, loose = divmod(rest, item.pk_weight_g)
    return int(boxes), int(pk), loose
