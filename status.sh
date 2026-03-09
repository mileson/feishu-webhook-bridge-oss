#!/bin/bash
set -euo pipefail

LABEL="${FEISHU_BRIDGE_LAUNCHD_LABEL:-io.github.feishu-webhook-bridge}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

echo "=== LaunchAgent ==="
if [ -f "$PLIST" ]; then
  echo "plist: $PLIST"
else
  echo "plist not found: $PLIST"
  exit 1
fi

echo
echo "=== launchctl list ==="
launchctl list | grep "$LABEL" || echo "not loaded"

echo
echo "=== launchctl print ==="
launchctl print "$DOMAIN/$LABEL" | sed -n '1,80p' || true

echo
echo "=== Process ==="
pgrep -af 'feishu-webhook-bridge|run_bot.sh|main.py' || echo "no matching process"
