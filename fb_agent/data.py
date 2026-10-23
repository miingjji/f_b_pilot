"""앱이 쓰는 마스터 데이터: data/real/ (prep.app_master 가 생성). 테스트는 FB_MASTER_DIR 로 fixture 폴더를 쓴다."""
from pathlib import Path

from config import MASTER_DIR, TEST_MASTER
from converter import to_boxes
from errors import InvalidInputError
from master import load_master
from models import StoreCalendar

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

DATA_DIR = Path(__file__).resolve().parent / "data"
if not (MASTER_DIR / "items.csv").exists():
    raise InvalidInputError(f"{MASTER_DIR / 'items.csv'} 가 없습니다. 먼저 `python -m prep.app_master` 로 만들어 주세요.")

SUPPLIERS, ITEMS = load_master(MASTER_DIR)
ITEMS_BY_CODE = {it.code: it for it in ITEMS.values()}
DATASET_LABEL = f"테스트 마스터 · 품목 {len(ITEMS)}개" if TEST_MASTER else f"실제 데이터 기반 · 품목 {len(ITEMS):,}개"

# 기본 매장 캘린더: 일요일 정기 휴무
DEFAULT_CALENDAR = StoreCalendar(closed_weekdays=frozenset({SUN}))

# 시드 실사 재고: 품목명 -> (BOX, PK, 낱개)  (마스터의 현재재고량을 BOX/PK/낱개로 환산)
SAMPLE_COUNTS = {name: to_boxes(it, it.current_stock or 0) for name, it in ITEMS.items()}
