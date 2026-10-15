#!/usr/bin/env bash
# 실제 데이터 기반 마스터(data/real)로 앱을 실행한다. 마스터가 없으면 먼저 만든다.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python}"
[ -f data/real/items.csv ] || "$PY" -m prep.app_master
FB_MASTER=real exec "$PY" -m streamlit run app.py "$@"
