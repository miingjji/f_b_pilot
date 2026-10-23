"""테스트는 소형 fixture 마스터(testdata/master)를 전제로 한다. 모든 test_*.py 가 가장 먼저 import 해서 FB_MASTER_DIR 을 고정한다.
(실제 마스터를 쓰는 테스트는 test_real_mode.py / test_real_sales.py 처럼 FB_MASTER_DIR 을 지운 별도 프로세스에서 실행한다.)"""
import os
from pathlib import Path

os.environ["FB_MASTER_DIR"] = str(Path(__file__).resolve().parent / "testdata" / "master")
