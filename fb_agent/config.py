"""앱 실행 설정. 환경변수 FB_MASTER 로 품목 마스터를 고른다.

    streamlit run app.py                    # 기본(auto): data/real/ 이 있으면 실제 데이터 기반, 없으면 샘플
    FB_MASTER=sample streamlit run app.py   # sample: data/items.csv, suppliers.csv (소모품 샘플 28개)
    FB_MASTER=real streamlit run app.py     # real: data/real/ 을 강제 (없으면 안내 오류)
"""
import os
from datetime import date
from pathlib import Path

REAL_ITEMS = Path(__file__).resolve().parent / "data" / "real" / "items.csv"      # python -m prep.app_master 로 생성


def _mode() -> str:
    choice = os.environ.get("FB_MASTER", "auto").strip().lower()
    if choice in ("real", "sample"):
        return choice
    return "real" if REAL_ITEMS.exists() else "sample"      # auto: 실제 데이터 파일이 있을 때만 실제 모드


MASTER_MODE = _mode()
STORES = ("수원점", "강남점", "홍대점") if MASTER_MODE == "real" else ("강남점", "홍대점", "판교점")

def default_today() -> date:
    """기준일 기본값은 실제 오늘 (설정에서 바꿀 수 있음). 실제 모드에서도 같다:
    매출은 2025-12가 실제, 그 밖의 날짜는 요일·공휴일 패턴을 따른 가상 값이라 오늘까지 비어 있지 않다."""
    return date.today()
