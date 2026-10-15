from dataclasses import dataclass, field
from datetime import date
from errors import InvalidInputError

WEEKDAY_KR = "월화수목금토일"


@dataclass(frozen=True)
class Supplier:
    name: str
    order_weekdays: frozenset   # 발주 가능 요일 (0=월 ... 6=일)
    lead_time_days: int         # 발주 후 입고까지 D+N

    def __post_init__(self):
        if not self.order_weekdays or not all(0 <= d <= 6 for d in self.order_weekdays):
            raise InvalidInputError(f"{self.name}: 발주 요일이 올바르지 않습니다.")
        if self.lead_time_days < 0:
            raise InvalidInputError(f"{self.name}: 리드타임은 음수일 수 없습니다.")

    @property
    def order_days_label(self) -> str:
        return "/".join(WEEKDAY_KR[d] for d in sorted(self.order_weekdays))


@dataclass(frozen=True)
class StoreCalendar:
    closed_weekdays: frozenset = frozenset()   # 정기 휴무 요일
    closed_dates: frozenset = frozenset()      # 임시 휴무일 (date)

    def is_open(self, d: date) -> bool:
        return d.weekday() not in self.closed_weekdays and d not in self.closed_dates


@dataclass(frozen=True)
class Item:
    name: str
    pk_weight_g: float      # 1 PK(팩) 당 무게(g)
    daily_usage_g: float    # 최근 일일 평균 소비량(g)
    supplier: Supplier = None
    box_pk: float = 1       # 1 BOX 당 PK 수
    ea_weight_g: float = 0  # 1 EA(낱개) 당 무게(g), 0이면 EA 미지원

    def __post_init__(self):
        if self.pk_weight_g <= 0 or self.box_pk <= 0:
            raise InvalidInputError(f"{self.name}: PK 무게/BOX 입수는 0보다 커야 합니다.")
        if self.daily_usage_g < 0 or self.ea_weight_g < 0:
            raise InvalidInputError(f"{self.name}: 소비량/EA 무게는 음수일 수 없습니다.")
        if self.supplier is None:
            raise InvalidInputError(f"{self.name}: 거래처가 지정되지 않았습니다.")

    @property
    def lead_time_days(self) -> int:
        return self.supplier.lead_time_days

    @property
    def box_weight_g(self) -> float:
        return self.pk_weight_g * self.box_pk
