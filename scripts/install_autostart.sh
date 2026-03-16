#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install_autostart.sh — Install Aureus AI as macOS Login Item (LaunchAgent)
#
# Usage:
#   cd /Users/doctorboyz/EA
#   bash scripts/install_autostart.sh
# ──────────────────────────────────────────────────────────────────────────────
set -e

LABEL="com.aureus.trading"
PLIST_SRC="$(dirname "$0")/${LABEL}.plist"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
PLIST_DEST="${LAUNCH_DIR}/${LABEL}.plist"
LOG_DIR="/Users/doctorboyz/EA/logs"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
echo "Aureus AI — Autostart Installer"
echo "================================"

if [ ! -f "$PLIST_SRC" ]; then
  echo "❌ Plist not found: $PLIST_SRC"
  exit 1
fi

if [ ! -f "/Users/doctorboyz/EA/venv/bin/python" ]; then
  echo "❌ Python venv not found. Run: cd /Users/doctorboyz/EA && python3 -m venv venv"
  exit 1
fi

# ── Create log directory ──────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
echo "✅ Log directory: $LOG_DIR"

# ── Unload if already loaded ──────────────────────────────────────────────────
if launchctl list | grep -q "$LABEL" 2>/dev/null; then
  echo "   Unloading existing service..."
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# ── Install plist ─────────────────────────────────────────────────────────────
mkdir -p "$LAUNCH_DIR"
cp "$PLIST_SRC" "$PLIST_DEST"
echo "✅ Installed plist: $PLIST_DEST"

# ── Load service ──────────────────────────────────────────────────────────────
launchctl load "$PLIST_DEST"
echo "✅ Service loaded"

# ── Verify ────────────────────────────────────────────────────────────────────
sleep 2
if launchctl list | grep -q "$LABEL"; then
  PID=$(launchctl list | grep "$LABEL" | awk '{print $1}')
  echo ""
  echo "✅ Aureus AI is running (PID: $PID)"
  echo "   Auto-starts on login: YES"
  echo "   Auto-restarts on crash: YES"
else
  echo "⚠️  Service loaded but may not have started yet"
  echo "   Check logs: tail -f $LOG_DIR/launchagent_stderr.log"
fi

echo ""
echo "Useful commands:"
echo "  Status:  launchctl list | grep aureus"
echo "  Stop:    launchctl stop $LABEL"
echo "  Start:   launchctl start $LABEL"
echo "  Logs:    tail -f $LOG_DIR/multi_run.log"
echo "  Uninstall: bash scripts/uninstall_autostart.sh"
