#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"
mkdir -p logs
export PYTHONUNBUFFERED=1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
exec "$REPO_DIR/venv/bin/python" "$REPO_DIR/main.py" >> "$REPO_DIR/logs/launchd.out" 2>> "$REPO_DIR/logs/launchd.err"
