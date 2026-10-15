"""앱 실행 설정. 환경변수 FB_MASTER 로 품목 마스터를 고른다.

    streamlit run app.py                    # sample (기본): data/items.csv, suppliers.csv (소모품 샘플 28개)
    FB_MASTER=real streamlit run app.py     # real: data/real/ (python -m prep.app_master 로 생성한 실제 데이터 기반)
"""
import os
from datetime import date

MASTER_MODE = "real" if os.environ.get("FB_MASTER", "sample").strip().lower() == "real" else "sample"
STORES = ("수원점", "강남점", "홍대점") if MASTER_MODE == "real" else ("강남점", "홍대점", "판교점")

REAL_TODAY = date(2025, 12, 31)      # 실제 데이터(재고·매출)의 마지막 날. 실제 모드의 기본 기준일


def default_today() -> date:
    """기준일 기본값: 샘플은 실제 오늘, 실제 모드는 데이터의 마지막 날(설정에서 바꿀 수 있음)."""
    return REAL_TODAY if MASTER_MODE == "real" else date.today()
