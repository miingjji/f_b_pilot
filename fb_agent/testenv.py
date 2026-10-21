"""테스트는 샘플 마스터를 전제로 한다. 모든 test_*.py 가 가장 먼저 import 해서 FB_MASTER 를 sample 로 고정한다.
(실제 모드 테스트는 test_real_mode.py / test_real_sales.py 처럼 별도 프로세스에서 FB_MASTER=real 로 실행한다.)"""
import os

os.environ["FB_MASTER"] = "sample"
