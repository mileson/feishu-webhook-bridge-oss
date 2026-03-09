#!/bin/bash
set -euo pipefail

LABEL="${FEISHU_BRIDGE_LAUNCHD_LABEL:-io.github.feishu-webhook-bridge}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"

echo "Uninstalled LaunchAgent: $LABEL"
