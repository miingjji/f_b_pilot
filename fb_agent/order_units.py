"""발주 추천의 수량(발주단위 기준)을 앱 구매청구의 PK 수량으로 바꾼다 (Streamlit 비의존).

구매청구 파일의 발주수량은 발주단위(팩·개·박스·킬로그램·병)로 적혀 있고, 규격에 '1kg/pk', '20g/1ea', '1BOX/24EA' 처럼 한 단위의 양이 있다.
앱 품목 마스터의 1 PK 는 대부분 그 발주단위 하나와 같다.  달라지는 경우만 환산한다:
  · 박스: 1 박스 = 마스터의 BOX당 PK 수 (대부분 1)
  · 킬로그램: 1 kg = 1000 ÷ PK당 수량(g)
  · 팩·개·병: 규격에서 읽은 한 단위의 양 ÷ PK당 수량.  거의 1 이면 그대로, 1 보다 작으면 (병 24개 = 1 PK 처럼) 그만큼만.
"""
import re

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
        return round(qty * box_pk, 2), ""
    if base_unit in COUNT_UNITS:                                 # 개수 기준 품목: 발주단위 하나가 1 PK
        return qty, ""
    if unit in ("킬로그램", "kg"):
        return round(qty * 1000.0 / pk_amount, 2), ""
    m = _BOX_OF.search(spec or "")                                # '1BOX/24EA' → 낱개 24개가 1박스 = 마스터 1 PK
    if m and float(m.group(2)) > 0:
        return round(qty / float(m.group(2)) * float(m.group(1)) * box_pk, 2), ""
    per = spec_amount(spec)
    if per is None or pk_amount <= 0:
        return qty, ""                                            # 규격에 양이 없으면(예: '골든피트') 발주단위 그대로
    ratio = per / pk_amount
    if 0.9 <= ratio <= 1.1:
        return qty, ""
    if ratio < 0.9:
        return round(qty * ratio, 2), ""
    return qty, f"규격({per:g})이 마스터 1 PK({pk_amount:g})보다 커서 수량 그대로 청구 — 확인 필요"
