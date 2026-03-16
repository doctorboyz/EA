"""
run_loop.py — Single-symbol improvement loop (XAUUSD focus).

━━━ USAGE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # Health check only
    python scripts/run_loop.py --check

    # XAUUSD live run — 20 iterations with XAUBreakout framework
    python scripts/run_loop.py --iterations 20

    # Dry run (no MT5 needed — uses V3 fixture)
    python scripts/run_loop.py --dry-run --iterations 5

    # Rule-based only (no Ollama)
    python scripts/run_loop.py --no-llm --iterations 10

    NOTE: For multi-symbol / champion hunt, use run_multi.py instead:
    python scripts/run_multi.py --symbols XAUUSD --until-champion --iterations 30

━━━ PRE-FLIGHT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1. ollama serve
    2. ollama pull qwen2.5-coder:14b   (code gen model)
    3. ollama pull qwen3.5:9b          (analysis model)
    4. createdb aureus && alembic upgrade head
    5. MetaTrader 5 via Whisky/Wine installed  (not needed for --dry-run)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ollama_client import OllamaClient
from agents.orchestrator import OrchestratorAgent
from agents.daddy_agent import DaddyAgent


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(level: str = "INFO") -> None:
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/orchestrator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )
    logging.info("Logging to: %s", log_file)


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aureus AI Trading Bot — Improvement Loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=10,
        help="Number of improvement iterations (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use V3 fixture HTML instead of real MT5 backtest",
    )
    parser.add_argument(
        "--fixture",
        type=str,
        default=None,
        help="Path to HTML fixture for --dry-run (default: tests/fixtures/V3-sample-report.html)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Rule-based analysis only — skip Ollama calls",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run pre-flight health checks only, then exit",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write final JSON results (optional)",
    )
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    setup_logging(args.log_level)

    print("\n" + "=" * 60)
    print(" AUREUS AI TRADING BOT — Improvement Loop")
    print("=" * 60)

    # Health check — DaddyAgent auto-fixes what it can, then reports
    daddy = DaddyAgent()
    report = daddy.prepare(auto_fix=True)
    print(report.summary())
    if args.check:
        return 0 if report.all_ok else 1
    if not report.all_ok and not args.dry_run:
        print("Aborting: CRITICAL environment checks failed. Use --dry-run to bypass.")
        return 1

    # Resolve fixture for dry-run
    fixture_path = args.fixture
    if args.dry_run and fixture_path is None:
        fixture_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tests", "fixtures", "V3-sample-report.html",
        )
        if not os.path.exists(fixture_path):
            print(f"[ERROR] Dry-run fixture not found: {fixture_path}")
            return 1

    print(f"\nMode:          {'DRY RUN (fixture)' if args.dry_run else 'LIVE (MT5)'}")
    print(f"Iterations:    {args.iterations}")
    print(f"LLM:           {'OFF (rule-based only)' if args.no_llm else 'ON (qwen2.5-coder:14b / qwen3.5:9b)'}")
    if args.dry_run:
        print(f"Fixture:       {fixture_path}")
    print()

    # Build orchestrator
    orchestrator = OrchestratorAgent(
        max_iterations=args.iterations,
        dry_run=args.dry_run,
        dry_run_fixture=fixture_path,
        use_llm=not args.no_llm,
    )

    # Run loop
    start = datetime.now()
    loop_result = await orchestrator.run()
    elapsed = (datetime.now() - start).total_seconds()

    # Print summary
    print("\n" + "=" * 60)
    print(" LOOP COMPLETE")
    print("=" * 60)
    print(f"Iterations run:  {loop_result.iterations_run}")
    print(f"Elapsed:         {elapsed:.1f}s")
    print(f"Champion:        v{loop_result.champion_version}  PF={loop_result.champion_pf:.2f}")
    print(f"All targets met: {'YES 🏆' if loop_result.all_targets_met else 'not yet'}")

    if loop_result.history:
        print("\nIteration history:")
        print(f"  {'Iter':>4}  {'Version':>8}  {'PF':>5}  {'DD%':>5}  {'RF':>5}  {'W/L':>5}  {'OK'}")
        print(f"  {'-'*4}  {'-'*8}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*2}")
        for h in loop_result.history:
            ok = "✓" if h["meets_all_targets"] else " "
            print(
                f"  {h['iteration']:>4}  {h['version']:>8}  "
                f"{h['profit_factor']:>5.2f}  "
                f"{h['max_drawdown_pct']:>5.1f}  "
                f"{h['recovery_factor']:>5.2f}  "
                f"{h['avg_win_loss_ratio']:>5.2f}  {ok}"
            )

    # Write output file
    if args.output:
        output_data = {
            "loop_result": {
                "iterations_run": loop_result.iterations_run,
                "champion_version": loop_result.champion_version,
                "champion_pf": loop_result.champion_pf,
                "champion_path": loop_result.champion_path,
                "all_targets_met": loop_result.all_targets_met,
                "elapsed_seconds": elapsed,
            },
            "history": loop_result.history,
        }
        with open(args.output, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to: {args.output}")

    return 0


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
