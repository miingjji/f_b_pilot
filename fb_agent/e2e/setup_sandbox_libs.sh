#!/usr/bin/env bash
# sudo 없이 Chromium(Playwright) 실행에 필요한 시스템 라이브러리와 한글 폰트를 .e2e-env/ 에 풀어 둔다.
# 사용:  bash e2e/setup_sandbox_libs.sh && source .e2e-env/env.sh && python e2e/check_ui.py
# 일반 개발 PC(라이브러리·폰트가 이미 있는 환경)에서는 필요 없다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${1:-$ROOT/.e2e-env}"
mkdir -p "$DIR/debs" "$DIR/libs" "$DIR/fonts"
cd "$DIR/debs"

# Ubuntu 24.04+ 는 libasound2t64, 그 이전은 libasound2
ASOUND=libasound2t64
apt-cache show libasound2t64 >/dev/null 2>&1 || ASOUND=libasound2
apt-get download libnspr4 libnss3 "$ASOUND" fonts-nanum

for f in *.deb; do dpkg -x "$f" "$DIR/libs"; done
mv "$DIR/libs/usr/share/fonts" "$DIR/fonts/" 2>/dev/null || true

cat > "$DIR/fonts.conf" <<CONF
<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig><dir>$DIR/fonts/fonts</dir><cachedir>$DIR/fontcache</cachedir></fontconfig>
CONF

cat > "$DIR/env.sh" <<ENV
export LD_LIBRARY_PATH="$DIR/libs/usr/lib/x86_64-linux-gnu:\${LD_LIBRARY_PATH:-}"
export FONTCONFIG_FILE="$DIR/fonts.conf"
ENV
echo "완료. 다음 명령으로 환경을 적용하세요:  source $DIR/env.sh"
