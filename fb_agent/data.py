"""앱이 쓰는 마스터 데이터. 원본은 data/items.csv, data/suppliers.csv (master.py 가 읽는다)."""
from converter import to_boxes
from master import load_master
from models import StoreCalendar

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

SUPPLIERS, ITEMS = load_master()
ITEMS_BY_CODE = {it.code: it for it in ITEMS.values()}

# 기본 매장 캘린더: 일요일 정기 휴무
DEFAULT_CALENDAR = StoreCalendar(closed_weekdays=frozenset({SUN}))

# 시드 실사 재고: 품목명 -> (BOX, PK, 낱개)  (마스터의 현재재고량을 BOX/PK/낱개로 환산)
SAMPLE_COUNTS = {name: to_boxes(it, it.current_stock or 0) for name, it in ITEMS.items()}
