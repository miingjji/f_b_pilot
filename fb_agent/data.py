from models import Item, StoreCalendar, Supplier

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

SUPPLIERS = {
    "A식자재": Supplier("A식자재", frozenset({MON, WED, FRI}), lead_time_days=1),
    "B유통": Supplier("B유통", frozenset({TUE, THU}), lead_time_days=1),
    "C농산": Supplier("C농산", frozenset({MON, THU}), lead_time_days=3),
}

ITEMS = {
    "짜사이": Item("짜사이", pk_weight_g=1000, daily_usage_g=450, supplier=SUPPLIERS["A식자재"], box_pk=10),
    "단무지": Item("단무지", pk_weight_g=2800, daily_usage_g=1200, supplier=SUPPLIERS["B유통"], box_pk=4),
    "청양고추": Item("청양고추", pk_weight_g=500, daily_usage_g=300, supplier=SUPPLIERS["C농산"], box_pk=10, ea_weight_g=10),
    "춘장": Item("춘장", pk_weight_g=2000, daily_usage_g=0, supplier=SUPPLIERS["A식자재"], box_pk=6),
}

# 기본 매장 캘린더: 일요일 정기 휴무
DEFAULT_CALENDAR = StoreCalendar(closed_weekdays=frozenset({SUN}))

# 예시 실사 재고: (BOX, PK, 낱개 g)
SAMPLE_COUNTS = {
    "짜사이": (0, 1, 300),
    "단무지": (0, 3, 0),
    "청양고추": (0, 0, 200),
    "춘장": (0, 2, 0),
}
