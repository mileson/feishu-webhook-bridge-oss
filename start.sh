#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
  cat <<USAGE
Usage:
  ./start.sh codex
  ./start.sh claude

Behavior:
  - On first run, prompts for Feishu App ID and App Secret
  - Saves them into .env
  - Automatically detects the CLI path for codex/claude when possible
USAGE
}

provider="${1:-}"
if [[ "$provider" != "codex" && "$provider" != "claude" ]]; then
  usage
  exit 1
fi

echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Feishu Webhook Bridge${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo

PYTHON_BIN=""
if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.12)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo -e "${RED}❌ 未找到可用的 Python${NC}"
  exit 1
fi

PYTHON_VERSION="$($PYTHON_BIN --version 2>&1)"
echo -e "${GREEN}✓ Python: ${PYTHON_VERSION}${NC}"

if "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info < (3, 13) else 1)
PY
then
  :
else
  echo -e "${RED}❌ 当前 Python 版本过高，飞书 SDK 依赖暂不兼容 Python 3.13+${NC}"
  echo -e "${YELLOW}   建议安装并使用 Python 3.12 后重试${NC}"
  exit 1
fi

if [ ! -d "venv" ]; then
  echo -e "${YELLOW}📦 Creating virtualenv...${NC}"
  "$PYTHON_BIN" -m venv venv
fi

source venv/bin/activate
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

echo -e "${YELLOW}📥 Installing dependencies...${NC}"
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

app_id="$(python3 - <<'PY'
from pathlib import Path
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('FEISHU_APP_ID='):
        print(line.split('=', 1)[1])
        break
PY
)"

app_secret="$(python3 - <<'PY'
from pathlib import Path
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('FEISHU_APP_SECRET='):
        print(line.split('=', 1)[1])
        break
PY
)"

if [ -z "$app_id" ] || [[ "$app_id" == cli_x* ]]; then
  read -r -p "Feishu App ID: " app_id
fi

if [ -z "$app_secret" ] || [[ "$app_secret" == xxxxxxxxx* ]]; then
  read -r -s -p "Feishu App Secret: " app_secret
  echo
fi

cli_command="$(command -v "$provider" || true)"

FEISHU_APP_ID_VALUE="$app_id" \
FEISHU_APP_SECRET_VALUE="$app_secret" \
LOCAL_AI_PROVIDER_VALUE="$provider" \
LOCAL_AI_COMMAND_VALUE="$cli_command" \
python3 - <<'PY'
import os
from pathlib import Path

env_path = Path('.env')
lines = env_path.read_text(encoding='utf-8').splitlines()
updates = {
    'FEISHU_APP_ID': os.environ['FEISHU_APP_ID_VALUE'],
    'FEISHU_APP_SECRET': os.environ['FEISHU_APP_SECRET_VALUE'],
    'LOCAL_AI_PROVIDER': os.environ['LOCAL_AI_PROVIDER_VALUE'],
}
cli_command = os.environ.get('LOCAL_AI_COMMAND_VALUE', '').strip()
if cli_command:
    updates['LOCAL_AI_COMMAND'] = cli_command

result = []
seen = set()
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key = line.split('=', 1)[0].strip()
        if key in updates:
            result.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    result.append(line)

for key, value in updates.items():
    if key not in seen:
        result.append(f"{key}={value}")

env_path.write_text("\n".join(result) + "\n", encoding='utf-8')
PY

set -a
source .env
set +a

echo
echo -e "${GREEN}✓ Provider: ${LOCAL_AI_PROVIDER}${NC}"
if [ -n "${LOCAL_AI_COMMAND:-}" ]; then
  echo -e "${GREEN}✓ CLI Path: ${LOCAL_AI_COMMAND}${NC}"
fi
echo -e "${GREEN}✓ Feishu App configured${NC}"
echo

exec python main.py
