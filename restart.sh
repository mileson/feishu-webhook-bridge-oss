#!/bin/bash
set -euo pipefail

LABEL="${FEISHU_BRIDGE_LAUNCHD_LABEL:-io.github.feishu-webhook-bridge}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

if [ ! -f "$PLIST" ]; then
  echo "plist not found: $PLIST"
  echo "Install it first with ./scripts/install_launch_agent.sh"
  exit 1
fi

echo "Restarting $LABEL ..."

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "$DOMAIN/$LABEL"
else
  launchctl bootstrap "$DOMAIN" "$PLIST"
  launchctl enable "$DOMAIN/$LABEL"
  launchctl kickstart -k "$DOMAIN/$LABEL"
fi

sleep 2
launchctl print "$DOMAIN/$LABEL" | sed -n '1,40p' || true
