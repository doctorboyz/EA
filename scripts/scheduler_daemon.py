#!/usr/bin/env python3
"""
Scheduler Daemon — Start the APScheduler for automated improvement loops.

Usage:
    python scripts/scheduler_daemon.py [--dry-run] [--config PATH]

Options:
    --dry-run: Print jobs without actually running them
    --config: Path to scheduler.yaml (default: config/scheduler.yaml)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import yaml

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.scheduler_agent import SchedulerAgent, ScheduledRunRequest
from core.database import get_engine

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """Load scheduler configuration."""
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def setup_logging(log_file: str = "./logs/scheduler.log", level: str = "INFO"):
    """Configure logging."""
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Aureus Scheduler Daemon — Automated improvement loop orchestration"
    )
    parser.add_argument(
        "--config",
        default="config/scheduler.yaml",
        help="Path to scheduler.yaml config file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List jobs without running scheduler",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(level=args.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Aureus Scheduler Daemon Starting")
    logger.info("=" * 60)

    # Load system config (for database URL)
    system_config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
    with open(system_config_path) as f:
        system_cfg = yaml.safe_load(f)

    # Initialize scheduler agent
    scheduler = SchedulerAgent(config_override=system_cfg)

    logger.info("Scheduler initialized:")
    logger.info("  Max concurrent loops: %d", scheduler.max_concurrent_loops)
    logger.info("  LLM queue max wait: %d sec", scheduler.llm_queue_max_wait)

    # Load scheduler config
    if os.path.exists(args.config):
        scheduler_cfg = load_config(args.config)
        logger.info("Loaded scheduler config: %s", args.config)

        # Register cron jobs from config
        jobs_cfg = scheduler_cfg.get('scheduler', {}).get('jobs', [])
        for job_cfg in jobs_cfg:
            if not job_cfg.get('enabled', True):
                logger.info("Skipping disabled job: %s", job_cfg.get('name'))
                continue

            job_id = job_cfg.get('name')
            cron_expr = job_cfg.get('cron')
            params = job_cfg.get('params', {})

            if job_cfg.get('type') == 'cron' and cron_expr:
                scheduler.add_cron_job(
                    job_id=job_id,
                    cron_expr=cron_expr,
                    symbols=params.get('symbols', ['EURUSD']),
                    variant_count=params.get('variant_count', 5),
                    iterations_per_symbol=params.get('iterations_per_symbol', 20),
                )
    else:
        logger.warning("Scheduler config not found: %s", args.config)
        logger.info("Using default: daily 6 AM UTC batch generation")
        scheduler.add_cron_job(
            job_id="default_daily_batch",
            cron_expr="0 6 * * *",
            symbols=["EURUSD", "GBPUSD", "USDJPY"],
            variant_count=5,
            iterations_per_symbol=20,
        )

    # List jobs
    jobs = scheduler.list_jobs()
    logger.info("Registered jobs (%d total):", len(jobs))
    for job in jobs:
        logger.info("  - %s: %s (next run: %s)", job['id'], job['trigger'], job['next_run_time'])

    # Run or dry-run
    if args.dry_run:
        logger.info("\n[DRY RUN] Scheduler would now run indefinitely.")
        logger.info("[DRY RUN] No actual jobs will be executed.")
        logger.info("[DRY RUN] Press Ctrl+C to exit.")
        logger.info("\nJobs to be scheduled:")
        for job in jobs:
            logger.info("  - %s", job['id'])
        return 0

    logger.info("\nStarting scheduler (running indefinitely)...")
    logger.info("Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler interrupted by user")
        scheduler.stop()
        return 0
    except Exception as e:
        logger.error("Scheduler error: %s", e, exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
