"""발주 추천의 수량(발주단위 기준)을 앱 구매청구의 PK 수량으로 바꾼다 (Streamlit 비의존).

구매청구 파일의 발주수량은 발주단위(팩·개·박스·킬로그램·병)로 적혀 있고, 규격에 '1kg/pk', '20g/1ea', '1BOX/24EA' 처럼 한 단위의 양이 있다.
앱 품목 마스터의 1 PK 는 대부분 그 발주단위 하나와 같다.  달라지는 경우만 환산한다:
  · 박스: 1 박스 = 마스터의 BOX당 PK 수 (대부분 1)
  · 킬로그램: 1 kg = 1000 ÷ PK당 수량(g)
  · 팩·개·병: 규격에서 읽은 한 단위의 양 ÷ PK당 수량.  거의 1 이면 그대로, 1 보다 작으면 (병 24개 = 1 PK 처럼) 그만큼만.
"""
import re
from dataclasses import dataclass

COUNT_UNITS = ("개", "장", "매", "롤", "켤레")   # 마스터 기본단위가 개수이면 1 PK = 발주단위 하나
_BOX_OF = re.compile(r"(\d+(?:\.\d+)?)\s*box\s*/\s*(\d+(?:\.\d+)?)\s*(?:ea|개|pk|pack|병)", re.I)
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b", re.I)
_TO_BASE = {"kg": 1000.0, "g": 1.0, "l": 1000.0, "ml": 1.0}


def spec_amount(spec: str) -> float | None:
    """규격 문자열에서 한 단위의 양(기본단위 g·ml 로 환산한 숫자). 읽을 수 없으면 None.
    '1kg/pk'→1000, '500ml/ea'→500, '18L'→18000, '20g/1ea'→20.  규격에 숫자+단위가 여러 번 나오면 첫 번째 (예: '200g*10pack/box'→200)."""
    m = _AMOUNT.search(spec or "")
    return float(m.group(1)) * _TO_BASE[m.group(2).lower()] if m else None


def packs_for(qty: float, unit: str, spec: str, pk_amount: float, box_pk: float = 1.0, base_unit: str = "g") -> tuple[float, str]:
    """(PK 수량, 확인이 필요하면 이유). pk_amount = 마스터의 1 PK 당 기본단위 수량, base_unit = 마스터 기본단위."""
    if unit == "박스":
        bp = box_pack(spec) if base_unit not in COUNT_UNITS and pk_amount > 0 else None
        if bp and bp[0]:                                          # '2.5kg*8pk/BOX' → 박스 = 20kg ÷ PK당 수량
            return round(qty * bp[0] * bp[1] / pk_amount, 2), ""
        return round(qty * box_pk, 2), ""
    if base_unit in COUNT_UNITS:                                 # 개수 기준 품목: 발주단위 하나가 1 PK
        return qty, ""
    if unit in ("킬로그램", "kg"):
        return round(qty * 1000.0 / pk_amount, 2), ""
    m = _BOX_OF.search(spec or "")                                # '1BOX/24EA' → 낱개 24개가 1박스 = 마스터 1 PK
    if m and float(m.group(2)) > 0:
        return round(qty / float(m.group(2)) * float(m.group(1)) * box_pk, 2), ""
    if unit in ("팩", "개") and "*" in (spec or ""):                # '5g*1000ea/pk' 처럼 안쪽 개수가 곱해진 규격은 첫 숫자가 팩 크기가 아니다
        return qty, ""
    per = spec_amount(spec)
    if per is None or pk_amount <= 0:
        return qty, ""                                            # 규격에 양이 없으면(예: '골든피트') 발주단위 그대로
    ratio = per / pk_amount
    if 0.85 <= ratio <= 1.1:                                      # 규격과 마스터가 15% 안쪽으로 다른 것은 같은 단위로 본다 (예: 50장(400g)/pk ↔ 450g)
        return qty, ""
    if ratio < 0.9:
        return round(qty * ratio, 2), ""
    return qty, f"규격({per:g})이 마스터 1 PK({pk_amount:g})보다 커서 수량 그대로 청구 — 확인 필요"


_SPEC_UNIT = re.compile(r"(?:/\s*\d*\s*|\d\s*(?=btl|병))(box|박스|pk|pack|팩|ea|개|btl|병|kg|g|l|ml)\s*$", re.I)
_UNIT_NAME = {"box": "박스", "박스": "박스", "pk": "팩", "pack": "팩", "팩": "팩", "ea": "개", "개": "개", "btl": "병", "병": "병",
              "kg": "킬로그램", "g": "킬로그램", "l": "킬로그램", "ml": "킬로그램"}
UNIT_SHORT = {"킬로그램": "kg"}          # 화면에 줄여 쓰는 단위 이름
WHOLE_UNITS = ("박스", "개", "병")        # 낱개로 세는 단위: 0.5 씩 늘릴 일이 없다


def order_unit(spec: str, history_unit: str | None = None, default: str | None = None) -> str:
    """품목의 발주단위(박스·팩·개·병·킬로그램). 청구 이력에 있으면 그 단위, 없으면 규격 끝('…/box')에서 읽고, 그것도 없으면 default(기본 '팩')."""
    if history_unit:
        return history_unit
    m = _SPEC_UNIT.search(re.sub(r"\s*\([^)]*\)\s*$", "", spec or ""))
    return _UNIT_NAME[m.group(1).lower()] if m else (default or "팩")


def pk_per_unit(unit: str, spec: str, pk_amount: float, box_pk: float = 1.0, base_unit: str = "g") -> float:
    """발주단위 1 이 앱 PK 몇 개인가 (packs_for 와 같은 환산). 0 이하로 나오면 1 로 본다."""
    v, _ = packs_for(1000.0, unit, spec, pk_amount, box_pk, base_unit)        # 1000 배로 구해 packs_for 의 소수 둘째 자리 반올림 오차를 없앤다
    return v / 1000.0 if v > 0 else 1.0


_PACK_A = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\s*\*\s*(\d+)\s*(ea|pack|pk|병|btl|개|봉|캔)?\s*/\s*box", re.I)   # 375ml*12ea/box
_PACK_B = re.compile(r"(\d+)\s*(병|btl|ea)\s*/\s*box", re.I)                                                       # 6병/box, 24ea/box
_PACK_C = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\s*/\s*(\d+)\s*(ea|개|병)\b", re.I)                            # 330ml/30ea
_LIQUOR = re.compile(r"맥주|소주|진로|고량|정종|가주|이과두|강소백|양하대곡|서울의밤|테라|카스|칭따오|클라우드|스텔라|화요|타이거|설화|주선방|와인|위스키|사케|막걸리|\(병\)")


def box_pack(spec: str) -> tuple[float | None, int, str] | None:
    """한 박스에 같은 낱개가 여러 개 든 규격이면 (낱개 1개의 양(g·ml, 모르면 None), 박스당 개수, 낱개 표기). 아니면 None.
    '375ml*12ea/box'→(375,12,'ea'), '6병/box'→(None,6,'병'), '330ml/30ea'→(330,30,'ea')."""
    m = _PACK_A.search(spec or "")
    if m and int(m.group(3)) > 1:
        return float(m.group(1)) * _TO_BASE[m.group(2).lower()], int(m.group(3)), (m.group(4) or "ea").lower()
    m = _PACK_B.search(spec or "")
    if m and int(m.group(1)) > 1:
        return None, int(m.group(1)), m.group(2).lower()
    m = _PACK_C.search(spec or "")
    if m and int(m.group(3)) > 1:
        return float(m.group(1)) * _TO_BASE[m.group(2).lower()], int(m.group(3)), m.group(4).lower()
    return None


def each_unit(token: str, name: str, supplier: str = "") -> str:
    """낱개를 세는 단위 이름. 병·캔·팩·개. 주류는 병, 이름에 '캔'이 있으면 캔."""
    token = token.lower()
    if token in ("병", "btl"):
        return "병"
    if token in ("pack", "pk", "봉"):
        return "팩"
    if "캔" in name:
        return "캔"
    return "병" if supplier.endswith("주류") or _LIQUOR.search(name) else "개"


@dataclass(frozen=True)
class Units:
    """품목의 단위 정보. unit=발주단위, per=발주단위 1이 앱 PK 몇 개인지, each=박스 안 낱개를 세는 단위(병·캔·개·팩),
    count=박스당 낱개 수, each_amt=낱개 1개의 기본단위(g·ml) 양."""
    unit: str
    per: float
    each: str | None = None
    count: int = 1
    each_amt: float = 0.0


def item_units(name: str, supplier: str, base_unit: str, pk_amount: float, box_pk: float = 1.0, history_unit: str | None = None) -> Units:
    """품목명 끝의 규격과 청구 이력의 발주단위로 Units 를 만든다. 개수 기준 품목(소모품)은 이력·규격이 없으면 '개'."""
    spec = re.sub(r"\s*\(\d+\)\s*$", "", name).rsplit("_", 1)[-1]
    unit = order_unit(spec, history_unit, default="개" if base_unit in COUNT_UNITS else "팩")
    per = pk_per_unit(unit, spec, pk_amount, box_pk, base_unit)
    plain = re.sub(r"\s*\([^)]*\)\s*$", "", spec)
    bp = box_pack(plain) if base_unit not in COUNT_UNITS and unit == "박스" else None
    if not bp and base_unit not in COUNT_UNITS and unit == "박스" and pk_amount > 0:     # '설화맥주500ML' 처럼 낱개 용량만 있으면 박스 용량 ÷ 낱개 용량 = 개수
        one = spec_amount(plain) or spec_amount(name)
        if one and pk_amount / one >= 1.99 and abs(pk_amount / one - round(pk_amount / one)) < 0.02:
            bp = (one, round(pk_amount / one), "ea")
    if not bp:
        return Units(unit, per)
    amt, count, token = bp
    return Units(unit, per, each_unit(token, name, supplier), count, amt or pk_amount * per / count)


def _num(q: float) -> str:
    return f"{q:,.2f}".rstrip("0").rstrip(".")


def qty_text(u: Units, qty: float) -> str:
    """발주단위 수량을 화면 표기로: '2박스'. 박스 안 낱개가 있으면 '24병 (2박스)'."""
    if u.each:
        return f"{_num(qty * u.count)}{u.each} ({_num(qty)}박스)"
    return _num(qty) + UNIT_SHORT.get(u.unit, u.unit)


def stock_text(u: Units, amount: float, pk_amount: float) -> str:
    """재고(기본단위 양)를 발주 단위와 같은 기준으로: 낱개가 있으면 병·캔 수, 없으면 발주단위 수."""
    if u.each:
        return f"{_num(amount / u.each_amt)}{u.each}"
    return _num(amount / pk_amount / u.per) + UNIT_SHORT.get(u.unit, u.unit)
