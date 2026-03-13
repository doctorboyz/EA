"""
run_loop.py — Entry point for the Aureus AI improvement loop.

Usage:
    python scripts/run_loop.py                        # Run with defaults (10 iterations, live MT5)
    python scripts/run_loop.py --iterations 5        # 5 iterations
    python scripts/run_loop.py --dry-run             # Use V3 fixture (no MT5 needed)
    python scripts/run_loop.py --no-llm              # Rule-based only (no Ollama)
    python scripts/run_loop.py --check               # Health check only

Pre-flight checklist:
    1. ollama serve                  (Ollama must be running)
    2. ollama pull llama3.2:3b       (analysis model)
    3. ollama pull qwen2.5-coder:7b  (code gen model, optional without --no-llm)
    4. createdb aureus + alembic upgrade head   (PostgreSQL must be ready)
    5. MT5 installed via Wine/Whisky (not needed for --dry-run)
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

def check_ollama(no_llm: bool) -> bool:
    """Verify Ollama is running and required models are available."""
    if no_llm:
        print("  [SKIP] Ollama check (--no-llm mode)")
        return True

    client = OllamaClient()
    health = client.health_check()

    if not health["ok"]:
        missing = health.get("missing", [])
        error = health.get("error", "")
        print(f"  [FAIL] Ollama: {error}")
        if missing:
            print(f"         Missing models: {missing}")
            print(f"         Run: ollama pull {' '.join(missing)}")
        return False

    print(f"  [ OK ] Ollama: {len(health['models'])} models available")
    for m in health["models"]:
        print(f"         - {m}")
    return True


def check_database() -> bool:
    """Verify PostgreSQL connection (basic check)."""
    try:
        import asyncpg
        import yaml

        with open("config/system.yaml") as f:
            cfg = yaml.safe_load(f)
        url = cfg["database"]["url"]
        # Quick async connect test
        async def _test():
            conn = await asyncpg.connect(url)
            await conn.close()
        asyncio.run(_test())
        print("  [ OK ] PostgreSQL connected")
        return True
    except ImportError:
        print("  [WARN] asyncpg not installed — database saves will be skipped")
        return True  # Non-fatal
    except Exception as e:
        print(f"  [FAIL] PostgreSQL: {e}")
        print("         Run: createdb aureus && alembic upgrade head")
        return False


def run_health_check(no_llm: bool) -> bool:
    """Run all pre-flight checks. Returns True if all pass."""
    print("\n=== Aureus AI Pre-flight Check ===\n")
    results = [
        check_ollama(no_llm),
        check_database(),
    ]
    ok = all(results)
    print(f"\n{'✓ All checks passed' if ok else '✗ Some checks failed — fix before running loop'}\n")
    return ok


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

    # Health check
    if args.check or not args.dry_run:
        ok = run_health_check(no_llm=args.no_llm)
        if args.check:
            return 0 if ok else 1
        if not ok and not args.dry_run:
            print("Aborting: pre-flight checks failed. Use --dry-run to bypass.")
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
    print(f"LLM:           {'OFF (rule-based only)' if args.no_llm else 'ON (llama3.2:3b)'}")
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
