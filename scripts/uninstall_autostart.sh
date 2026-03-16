#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# uninstall_autostart.sh — Remove Aureus AI autostart
# ──────────────────────────────────────────────────────────────────────────────
set -e

LABEL="com.aureus.trading"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"

echo "Aureus AI — Removing Autostart"
echo "================================"

if launchctl list | grep -q "$LABEL" 2>/dev/null; then
  launchctl stop  "$LABEL" 2>/dev/null || true
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
  echo "✅ Service stopped and unloaded"
else
  echo "   Service was not running"
fi

if [ -f "$PLIST_DEST" ]; then
  rm "$PLIST_DEST"
  echo "✅ Plist removed: $PLIST_DEST"
else
  echo "   Plist not found (already removed)"
fi

echo ""
echo "✅ Aureus AI autostart removed."
echo "   System will no longer start automatically on login."
echo "   To start manually: source venv/bin/activate && python scripts/run_multi.py"
