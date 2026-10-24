from dataclasses import dataclass, field
from datetime import date
from errors import InvalidInputError

WEEKDAY_KR = "월화수목금토일"
NO_DATA = "데이터 없음"


@dataclass(frozen=True)
class Supplier:
    name: str
    order_weekdays: frozenset   # 발주 가능 요일 (0=월 ... 6=일). 비어 있으면 실제 데이터가 없는 것
    lead_time_days: int | None  # 발주 후 입고까지 D+N. None 이면 실제 데이터가 없는 것
    delivery_weekdays: frozenset = frozenset()   # 입고(배송) 가능 요일 (수불부 입고 실적). 비어 있으면 모르는 것 — 제한하지 않는다

    def __post_init__(self):
        if not all(0 <= d <= 6 for d in self.order_weekdays):
            raise InvalidInputError(f"{self.name}: 발주 요일이 올바르지 않습니다.")
        if self.lead_time_days is not None and self.lead_time_days < 0:
            raise InvalidInputError(f"{self.name}: 리드타임은 음수일 수 없습니다.")

    @property
    def has_schedule(self) -> bool:
        """발주 요일과 리드타임이 모두 실제 데이터로 정해져 있는지."""
        return bool(self.order_weekdays) and self.lead_time_days is not None

    @property
    def order_days_label(self) -> str:
        return "/".join(WEEKDAY_KR[d] for d in sorted(self.order_weekdays)) or NO_DATA

    @property
    def lead_time_label(self) -> str:
        return NO_DATA if self.lead_time_days is None else f"D+{self.lead_time_days}"


@dataclass(frozen=True)
class StoreCalendar:
    closed_weekdays: frozenset = frozenset()   # 정기 휴무 요일
    closed_dates: frozenset = frozenset()      # 임시 휴무일 (date)

    def is_open(self, d: date) -> bool:
        return d.weekday() not in self.closed_weekdays and d not in self.closed_dates


BASE_UNITS = ("g", "ml", "개", "장", "매", "롤", "켤레")   # 재고를 세는 기본 단위 (무게·부피·개수)


def fmt_amount(q: float, base: str) -> str:
    """기본단위 수량을 읽기 좋게: 1800ml -> 1.8L, 5000g -> 5kg, 100장 -> 100장."""
    if base == "g" and abs(q) >= 1000:
        return f"{q / 1000:,.2f}".rstrip("0").rstrip(".") + "kg"
    if base == "ml" and abs(q) >= 1000:
        return f"{q / 1000:,.2f}".rstrip("0").rstrip(".") + "L"
    return f"{q:,.1f}".rstrip("0").rstrip(".") + base


@dataclass(frozen=True)
class Item:
    """품목 마스터. 수량은 모두 '기본단위'(base_unit: g·ml·개·장 …)로 센다.

    필드 이름의 *_g 는 과거(무게 전용) 이름을 유지한 것이고, 실제 단위는 base_unit 이다.
    """
    name: str
    pk_weight_g: float      # 1 PK(팩) 당 수량 (기본단위)
    daily_usage_g: float    # 최근 일일 평균 소비량 (기본단위)
    supplier: Supplier = None
    box_pk: float = 1       # 1 BOX 당 PK 수
    ea_weight_g: float = 0  # 1 EA(낱개) 당 수량 (기본단위), 0이면 EA 미지원
    code: str = ""          # 품목코드
    major: str = ""         # 대분류 (식자재 / 소모품)
    mid: str = ""           # 중분류
    base_unit: str = "g"
    safety_stock_g: float | None = None   # 안전재고량 (기본단위). None이면 일 소비량 × 1일
    current_stock: float | None = None    # 시드 현재재고량 (기본단위)
    lead_time_override: int | None = None  # 품목별 리드타임(일). None이면 거래처 기본값
    cuisines: tuple = ()    # 주로 쓰는 업종 (한식·중식·일식·양식·카페, 공통)
    usage_known: bool = True   # False 면 일 소비량의 실제 근거가 없다 (daily_usage_g 는 0)

    def __post_init__(self):
        if self.pk_weight_g <= 0 or self.box_pk <= 0:
            raise InvalidInputError(f"{self.name}: PK 수량/BOX 입수는 0보다 커야 합니다.")
        if self.daily_usage_g < 0 or self.ea_weight_g < 0:
            raise InvalidInputError(f"{self.name}: 소비량/EA 수량은 음수일 수 없습니다.")
        if self.supplier is None:
            raise InvalidInputError(f"{self.name}: 거래처가 지정되지 않았습니다.")
        if self.base_unit not in BASE_UNITS:
            raise InvalidInputError(f"{self.name}: 기본단위는 {', '.join(BASE_UNITS)} 중 하나여야 합니다 ({self.base_unit!r}).")
        for label, v in (("안전재고량", self.safety_stock_g), ("현재재고량", self.current_stock)):
            if v is not None and v < 0:
                raise InvalidInputError(f"{self.name}: {label}은 음수일 수 없습니다.")
        if self.lead_time_override is not None and self.lead_time_override < 0:
            raise InvalidInputError(f"{self.name}: 리드타임은 음수일 수 없습니다.")

    @property
    def lead_time_days(self) -> int | None:
        return self.supplier.lead_time_days if self.lead_time_override is None else self.lead_time_override

    @property
    def lead_time_label(self) -> str:
        return NO_DATA if self.lead_time_days is None else f"D+{self.lead_time_days}"

    @property
    def box_weight_g(self) -> float:
        return self.pk_weight_g * self.box_pk

    @property
    def spec(self) -> str:
        """기본 규격/단위 표기. 예: 5kg/PK · 4PK/BOX, 100장/PK · 10PK/BOX."""
        s = f"{fmt_amount(self.pk_weight_g, self.base_unit)}/PK"
        return s + (f" · {self.box_pk:g}PK/BOX" if self.box_pk > 1 else "")

    def fmt(self, q: float) -> str:
        return fmt_amount(q, self.base_unit)
