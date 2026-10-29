"""앱 실행 설정.

품목 마스터는 data/real/ (python -m prep.app_master 로 생성)을 쓴다. 테스트만 환경변수 FB_MASTER_DIR 로 다른 폴더(소형 fixture)를 지정한다.
앱이 보여 주는 값은 모두 실제 데이터이고, 근거가 없는 값은 '데이터 없음'으로 표시한다 (가상 값을 만들지 않는다).
"""
import os
from datetime import date
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ASSETS = APP_DIR / "assets"          # 로고 등. 배포 환경은 저장소 루트에서 실행하므로 현재 폴더 기준 상대경로를 쓰지 않는다
REAL_DIR = APP_DIR / "data" / "real"
MASTER_DIR = Path(os.environ["FB_MASTER_DIR"]) if os.environ.get("FB_MASTER_DIR") else REAL_DIR
TEST_MASTER = MASTER_DIR != REAL_DIR
STORES = ("수원점",)


def default_today() -> date:
    """기준일 기본값은 실제 오늘 (설정에서 바꿀 수 있음). 매출 화면은 데이터가 끝난 뒤라면 마지막 영업일을 기준으로 보여 준다."""
    return date.today()
