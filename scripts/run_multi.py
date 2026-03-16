"""
run_multi.py — Entry point for Aureus AI Trading System (XAUUSD focus).

Starts the full pipeline:
  XAUUSD  ← primary focus (champion v0.3.1 PF=2.85 came from here)
  ──────────────────────────────────────────────────────────────────
  Framework priority: XAUBreakout → TrendFollowing → Breakout → ...
  Backtest loop (serialised Wine semaphore — prevents kernel panic)
  → Forward test deployment (demo account)
  → Live trade monitoring (real account, if enabled)

━━━ QUICK START ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Standard hunt — XAUUSD only, 30 iterations, stop when champion found
  source venv/bin/activate
  python scripts/run_multi.py --symbols XAUUSD --until-champion --iterations 30

  # Continuous loop (runs forever, restarts every 5 min between cycles)
  python scripts/run_multi.py --symbols XAUUSD --continuous --iterations 20 --restart-delay 300

  # Quick test — 5 iterations, single run
  python scripts/run_multi.py --symbols XAUUSD --iterations 5

  # Multi-symbol (if re-enabling EURUSD/GBPUSD later)
  python scripts/run_multi.py --symbols XAUUSD EURUSD --iterations 20

━━━ PRE-FLIGHT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ollama serve                          # must be running
  ollama pull qwen2.5-coder:14b         # code generation model
  ollama pull qwen3.5:9b                # analysis model
  # PostgreSQL must be running: createdb aureus + alembic upgrade head
  # MetaTrader 5 must be installed via Whisky (Wine wrapper)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logging_setup import setup_logging
from agents.orchestrator import OrchestratorAgent

# ─── Status file paths ────────────────────────────────────────────────────────
STATUS_FILE  = ROOT / "logs" / "system_status.json"
PID_FILE     = ROOT / "logs" / "run_multi.pid"


def write_pid():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def remove_pid():
    PID_FILE.unlink(missing_ok=True)


def write_status(state: str, extra: dict = None):
    """Write live status to JSON file — merges with orchestrator's phase data."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Read existing status (orchestrator writes phase/hunt_log/champion)
    existing = {}
    if STATUS_FILE.exists():
        try:
            existing = json.loads(STATUS_FILE.read_text())
        except Exception:
            pass

    # Merge: orchestrator fields survive, run_multi updates wrapper fields
    status = {
        **existing,
        "state":      state,
        "pid":        os.getpid(),
        "started_at": _start_time,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "uptime_sec": int(time.time() - _start_ts),
        **(extra or {}),
    }
    STATUS_FILE.write_text(json.dumps(status, indent=2))


_start_time = datetime.now(timezone.utc).isoformat()
_start_ts   = time.time()


# ─── Args ─────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Aureus AI — Multi-Symbol Trading System"
    )
    parser.add_argument("--symbols", nargs="+", default=None, metavar="SYMBOL")
    parser.add_argument("--iterations", type=int, default=20, metavar="N",
                        help="Backtest iterations per symbol per cycle (default: 20)")
    parser.add_argument("--continuous", action="store_true",
                        help="Keep restarting loop forever (for daemon/autostart)")
    parser.add_argument("--restart-delay", type=int, default=300,
                        help="Seconds to wait between cycles in continuous mode (default: 300)")
    parser.add_argument("--until-champion", action="store_true",
                        help="Hunt forever until champion found on all symbols (or timeout)")
    parser.add_argument("--max-hours", type=int, default=72,
                        help="Max hunting time in hours with --until-champion (default: 72)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_once(args, logger) -> bool:
    """Run one cycle. Returns True if completed normally."""
    import yaml

    cfg_path = ROOT / "config" / "system.yaml"
    with open(cfg_path) as _f:
        cfg = yaml.safe_load(_f)

    # XAUUSD-only
    symbol = "XAUUSD"

    mode = "hunting" if args.until_champion else ("continuous" if args.continuous else "single")

    write_status("running", {
        "symbol": symbol,
        "iterations": args.iterations,
        "mode": mode,
        "hunting": args.until_champion,
        "max_hours": args.max_hours if args.until_champion else None,
    })

    # Run XAUUSD orchestrator
    orchestrator = OrchestratorAgent(
        max_iterations=args.iterations,
        dry_run=False,
        symbol=symbol,
    )
    result = await orchestrator.run()

    # Update status with results
    champion_info = None
    if orchestrator._champion_version:
        champion_info = {
            "version": orchestrator._champion_version,
            "pf": round(orchestrator._champion_pf, 2),
        }

    write_status("running", {
        "symbol": symbol,
        "iterations": args.iterations,
        "mode": mode,
        "champion": champion_info,
        "iterations_completed": result.iterations_run,
    })

    return True


async def main():
    args = parse_args()
    setup_logging(level=args.log_level)
    logger = logging.getLogger("run_multi")

    write_pid()

    # Handle SIGTERM gracefully (sent by launchctl stop / systemctl stop)
    def _handle_signal(sig, frame):
        logger.info("Signal %d received — shutting down gracefully", sig)
        write_status("stopped", {"reason": f"signal_{sig}"})
        remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    logger.info("=" * 60)
    logger.info("  Aureus AI — Multi-Symbol Trading System")
    logger.info("  PID: %d", os.getpid())
    logger.info("=" * 60)
    if args.symbols:
        logger.info("  Symbols:    %s", ", ".join(args.symbols))
    else:
        logger.info("  Symbols:    from config/system.yaml")
    logger.info("  Iterations: %d per symbol", args.iterations)
    if args.until_champion:
        logger.info("  Mode:       🔍 HUNTING (max %d hours)", args.max_hours)
    else:
        logger.info("  Mode:       %s", "continuous" if args.continuous else "single")
    logger.info("=" * 60)

    cycle = 0
    try:
        while True:
            cycle += 1
            logger.info("─── Cycle %d ───────────────────────────────────", cycle)
            write_status("running", {"cycle": cycle})

            try:
                await run_once(args, logger)
                logger.info("Cycle %d completed", cycle)
            except Exception as e:
                logger.error("Cycle %d error: %s", cycle, e, exc_info=True)
                write_status("error", {"cycle": cycle, "error": str(e)})

            # Hunting mode runs until completion inside run_once, don't restart
            if args.until_champion:
                logger.info("🔍 HUNT complete")
                break

            if not args.continuous:
                break

            write_status("restarting", {
                "cycle": cycle,
                "next_cycle_in_sec": args.restart_delay,
            })
            logger.info("Continuous mode: waiting %ds before next cycle...", args.restart_delay)
            await asyncio.sleep(args.restart_delay)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        write_status("stopped", {"cycles_completed": cycle})
        remove_pid()


if __name__ == "__main__":
    asyncio.run(main())
