"""
ProcessGuard — Watchdog that keeps critical system processes alive.

Monitors and auto-restarts:
  - PostgreSQL (database)
  - Ollama LLM server
  - Wine wineserver (required for MT5)

Usage:
    python -m agents.process_guard          # run in foreground
    python -m agents.process_guard --daemon # run in background
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30  # seconds between health checks


def _is_running(pattern: str) -> bool:
    """Return True if any process matching pattern is running."""
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        capture_output=True,
    )
    return result.returncode == 0


def _ensure_postgres() -> None:
    """Ensure PostgreSQL is running."""
    if not _is_running("postgres"):
        logger.warning("[Guard] PostgreSQL not running — starting...")
        subprocess.Popen(
            ["brew", "services", "start", "postgresql@14"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        if _is_running("postgres"):
            logger.info("[Guard] PostgreSQL started ✅")
        else:
            logger.error("[Guard] Failed to start PostgreSQL ❌")


def _ensure_ollama() -> None:
    """Ensure Ollama is running on port 11434."""
    if not _is_running("ollama"):
        logger.warning("[Guard] Ollama not running — starting...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(5)
        if _is_running("ollama"):
            logger.info("[Guard] Ollama started ✅")
        else:
            logger.error("[Guard] Failed to start Ollama ❌")


def _ensure_wineserver() -> None:
    """Ensure Wine wineserver is running (required for MT5 Wine processes)."""
    wine_prefix = "/Users/doctorboyz/Library/Application Support/net.metaquotes.wine.metatrader5"
    wineserver = "/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wineserver"

    if not _is_running("wineserver") and os.path.exists(wineserver):
        logger.warning("[Guard] Wine wineserver not running — starting...")
        env = os.environ.copy()
        env["WINEPREFIX"] = wine_prefix
        subprocess.Popen(
            [wineserver, "--foreground"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        time.sleep(2)
        if _is_running("wineserver"):
            logger.info("[Guard] Wineserver started ✅")
        else:
            logger.warning("[Guard] Wineserver not detected (may still be starting)")


def run_guard(checks=("postgres", "ollama", "wineserver")) -> None:
    """
    Run the process guard loop indefinitely.
    checks: tuple of services to monitor.
    """
    logger.info("[Guard] ProcessGuard started (interval: %ds)", POLL_INTERVAL)
    logger.info("[Guard] Monitoring: %s", ", ".join(checks))

    while True:
        try:
            if "postgres" in checks:
                _ensure_postgres()
            if "ollama" in checks:
                _ensure_ollama()
            if "wineserver" in checks:
                _ensure_wineserver()
        except Exception as e:
            logger.error("[Guard] Unexpected error: %s", e)

        time.sleep(POLL_INTERVAL)


def status() -> dict:
    """Return current status of all monitored processes."""
    return {
        "postgres":   _is_running("postgres"),
        "ollama":     _is_running("ollama"),
        "wineserver": _is_running("wineserver"),
        "terminal64": _is_running("terminal64"),
    }


if __name__ == "__main__":
    import argparse
    from core.logging_setup import setup_logging

    parser = argparse.ArgumentParser(description="Aureus ProcessGuard")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    parser.add_argument("--no-ollama", action="store_true", help="Skip Ollama check")
    args = parser.parse_args()

    setup_logging(level="INFO", format_type="json")

    if args.status:
        s = status()
        for name, running in s.items():
            icon = "✅" if running else "❌"
            print(f"  {icon}  {name}")
        sys.exit(0)

    checks = ["postgres", "wineserver"]
    if not args.no_ollama:
        checks.append("ollama")

    if args.daemon:
        # Fork to background
        if os.fork() > 0:
            print(f"ProcessGuard running in background. PID: {os.getpid() + 1}")
            sys.exit(0)

    run_guard(tuple(checks))
