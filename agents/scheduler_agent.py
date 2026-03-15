"""
SchedulerAgent — Time-based and event-triggered improvement loop orchestration.

Responsibilities:
1. Schedule cron-based improvement loop runs (e.g., daily 6 AM UTC)
2. Manage concurrent improvement loops (max_concurrent_loops guard)
3. Provide LLM semaphore for rate-limiting llama3.2:3b calls (only 1 concurrent)
4. Queue runs to scheduled_runs table for audit trail
5. Start improvement loops asynchronously

Architecture:
- APScheduler BlockingScheduler for cron jobs
- threading.Semaphore for LLM call gating (max 1 concurrent)
- Database tracking: scheduled_runs, run_triggers
"""

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from core.database import ScheduledRun, RunTrigger, Base, get_session
from core.strategy_config import StrategyConfig, StrategyVersion

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    """Load system.yaml + scheduler.yaml configs."""
    cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
    with open(cfg_path) as f:
        system_cfg = yaml.safe_load(f)

    scheduler_cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'scheduler.yaml')
    scheduler_cfg = {}
    if os.path.exists(scheduler_cfg_path):
        with open(scheduler_cfg_path) as f:
            scheduler_cfg = yaml.safe_load(f) or {}

    return {**system_cfg, 'scheduler': scheduler_cfg.get('scheduler', {})}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScheduledRunRequest:
    """Request to queue a new improvement loop run."""
    symbol: str
    iterations: int
    trigger_type: str  # "cron", "manual", "news", etc.
    trigger_reason: str = ""
    variant_count: Optional[int] = None
    initial_config: Optional[StrategyConfig] = None


# ---------------------------------------------------------------------------
# Scheduler Agent
# ---------------------------------------------------------------------------

class SchedulerAgent:
    """
    Manages scheduled runs with LLM load control.

    Key features:
    - APScheduler for cron-based runs (e.g., daily 6 AM)
    - max_concurrent_loops guard (e.g., max 2 orchestrator instances)
    - LLM semaphore: only 1 concurrent call to llama3.2:3b
    """

    def __init__(self, config_override: Optional[dict] = None):
        """Initialize scheduler with config."""
        self.config = config_override or _load_config()
        scheduler_cfg = self.config.get('scheduler', {})

        self.enabled = scheduler_cfg.get('enabled', False)
        self.max_concurrent_loops = scheduler_cfg.get('max_concurrent_loops', 2)
        self.llm_queue_max_wait = scheduler_cfg.get('llm_call_queue_max_wait', 300)
        self.timezone = scheduler_cfg.get('default_timezone', 'UTC')

        # Database
        db_url = self.config.get('database', {}).get('url')
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)

        # Scheduler
        self.scheduler = BlockingScheduler(timezone=self.timezone)

        # LLM rate limiting: only 1 concurrent call to llama3.2:3b
        self.llm_semaphore = threading.Semaphore(1)

        # Track active runs (by symbol)
        self._active_runs: Dict[str, datetime] = {}
        self._active_runs_lock = threading.Lock()

        logger.info(
            "SchedulerAgent initialized: max_concurrent=%d, llm_queue_max_wait=%d",
            self.max_concurrent_loops,
            self.llm_queue_max_wait,
        )

    # ------------------------------------------------------------------
    # LLM Semaphore (for rate limiting llama3.2:3b)
    # ------------------------------------------------------------------

    def wait_for_llm_slot(self, timeout: Optional[int] = None) -> bool:
        """
        Acquire LLM semaphore (blocks until available).

        Called by ResultAnalyzer.analyze() and StrategyImprover.improve().

        Args:
            timeout: Max seconds to wait (default: llm_queue_max_wait)

        Returns:
            True if acquired, False if timeout
        """
        timeout = timeout or self.llm_queue_max_wait
        acquired = self.llm_semaphore.acquire(timeout=timeout)
        if acquired:
            logger.debug("LLM slot acquired (semaphore count: %d)", self.llm_semaphore._value)
        else:
            logger.warning("LLM slot timeout after %d seconds", timeout)
        return acquired

    def release_llm_slot(self) -> None:
        """Release LLM semaphore. Called after LLM operation completes."""
        self.llm_semaphore.release()
        logger.debug("LLM slot released (semaphore count: %d)", self.llm_semaphore._value)

    # ------------------------------------------------------------------
    # Run Management
    # ------------------------------------------------------------------

    def get_concurrent_run_count(self) -> int:
        """Count currently active improvement loops."""
        with self._active_runs_lock:
            # Prune expired runs (older than 2 hours)
            cutoff = datetime.utcnow().timestamp() - 7200
            self._active_runs = {
                s: t for s, t in self._active_runs.items()
                if t.timestamp() > cutoff
            }
            return len(self._active_runs)

    def queue_run(self, request: ScheduledRunRequest) -> str:
        """
        Queue a new improvement loop run.

        Respects max_concurrent_loops: blocks until slot available.

        Args:
            request: ScheduledRunRequest with symbol, iterations, trigger info

        Returns:
            run_id for tracking
        """
        # Wait for concurrent loop slot
        while self.get_concurrent_run_count() >= self.max_concurrent_loops:
            logger.info(
                "Waiting for loop slot (current: %d/%d). Retrying in 30s...",
                self.get_concurrent_run_count(),
                self.max_concurrent_loops,
            )
            time.sleep(30)

        # Create DB record
        with Session(self.engine) as session:
            run = ScheduledRun(
                symbol=request.symbol,
                trigger_type=request.trigger_type,
                trigger_reason=request.trigger_reason,
                iterations=request.iterations,
                variant_count=request.variant_count,
                status="queued",
                queued_at=datetime.utcnow(),
            )
            session.add(run)
            session.commit()
            run_id = run.id

            # Also log trigger
            trigger = RunTrigger(
                run_id=run_id,
                trigger_type=request.trigger_type,
                trigger_reason=request.trigger_reason,
                triggered_at=datetime.utcnow(),
            )
            session.add(trigger)
            session.commit()

        # Mark as active
        with self._active_runs_lock:
            self._active_runs[request.symbol] = datetime.utcnow()

        logger.info(
            "Run queued: id=%s, symbol=%s, trigger=%s, iterations=%d",
            run_id, request.symbol, request.trigger_type, request.iterations,
        )
        return str(run_id)

    # ------------------------------------------------------------------
    # Cron Job Management
    # ------------------------------------------------------------------

    def add_cron_job(
        self,
        job_id: str,
        cron_expr: str,
        symbols: List[str],
        variant_count: int = 5,
        iterations_per_symbol: int = 20,
    ) -> None:
        """
        Register a cron-based batch generation + improvement job.

        Example: "0 6 * * *" = every day 6 AM UTC

        Args:
            job_id: Unique job identifier
            cron_expr: APScheduler cron expression
            symbols: List of symbols to generate/improve (e.g., [EURUSD, GBPUSD])
            variant_count: N strategy variants to generate per symbol
            iterations_per_symbol: Max iterations per symbol
        """
        def cron_callback():
            logger.info(
                "Cron job triggered: %s (symbols=%s, variants=%d)",
                job_id, symbols, variant_count,
            )
            # Queue runs for each symbol
            for symbol in symbols:
                request = ScheduledRunRequest(
                    symbol=symbol,
                    iterations=iterations_per_symbol,
                    trigger_type="cron",
                    trigger_reason=f"Cron job: {job_id}",
                    variant_count=variant_count,
                )
                self.queue_run(request)

        self.scheduler.add_job(
            cron_callback,
            trigger=CronTrigger.from_crontab(cron_expr, timezone=self.timezone),
            id=job_id,
            name=f"Cron: {job_id}",
        )
        logger.info(
            "Cron job registered: %s at '%s' (symbols=%s)",
            job_id, cron_expr, symbols,
        )

    # ------------------------------------------------------------------
    # Scheduler Control
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch blocking scheduler (runs forever until stop() called)."""
        if not self.enabled:
            logger.warning("Scheduler disabled in config. Set scheduler.enabled=true to activate.")
            return

        logger.info("Starting scheduler (blocking, will run until interrupted)...")
        try:
            self.scheduler.start()
        except KeyboardInterrupt:
            logger.info("Scheduler interrupted by user")
            self.stop()

    def stop(self) -> None:
        """Gracefully shutdown scheduler."""
        if self.scheduler.running:
            logger.info("Stopping scheduler...")
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all registered jobs."""
        return [
            {
                'id': job.id,
                'name': job.name,
                'trigger': str(job.trigger),
                'next_run_time': str(job.next_run_time),
            }
            for job in self.scheduler.get_jobs()
        ]
