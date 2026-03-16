"""
MommyAgent — Dynamic agent factory and lifecycle manager.

GOVERNANCE RULES (read before touching this file)
--------------------------------------------------
1. MAX_TOTAL_AGENTS     Hard cap on simultaneous live agents (default 12).
2. MAX_PER_ROLE         No more than 1 instance of the same agent at a time
                        unless it is in the MULTI_INSTANCE_ALLOWED set.
3. MAX_LLM_DESIGNS      LLM-designed agents are expensive and risky.
                        Cap at MAX_LLM_DESIGNS per MommyAgent lifetime (default 3).
4. HIERARCHY            Only agents in SPAWN_AUTHORITY may call spawn().
                        Agents must not spawn agents above their own tier.
5. STANDARD_PIPELINE    Only these 5 agents are required. Everything else is
                        optional. fill_pipeline_gaps() only touches these 5.
6. LLM_POWERED          Explicit set. If your agent is not in it, it must NOT
                        call self._ollama. Prevents silent LLM cost bleed.

LLM Power Map
-------------
Agent                   LLM?     Model               What for
----------------------  -------  ------------------  ------------------------
code_generator          MAYBE    qwen2.5-coder:14b   Comment enrichment only
                                                     (use_llm=False by default)
backtest_runner         NO       —                   Subprocess / file I/O
report_parser           NO       —                   BeautifulSoup rule-based
result_analyzer         YES      qwen3.5:9b          Weakness identification
strategy_improver       YES      qwen3.5:9b          Config mutation proposals
news_filter             NO       —                   Calendar HTML parsing
batch_generator         MAYBE    via code_generator  Only if use_llm=True
forward_test_manager    NO       —                   Rule-based PF monitoring
market_regime_detector  NO       —                   ATR/ADX math
signal_agent            NO       —                   Rule-based entry logic
live_trade_agent        NO       —                   Order execution + stops
multi_symbol_orc.       NO       —                   Async coordination only
mommy_agent (self)      MAYBE    qwen3.5:9b          Agent selection/design
                                                     (only when no keyword match)
daddy_agent             MAYBE    qwen3.5:9b          Error diagnosis
                                                     (only after built-in fixes fail)
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants / governance limits
# ---------------------------------------------------------------------------

MAX_TOTAL_AGENTS: int = 12          # Hard cap: system has ~12 known agents
MAX_PER_ROLE: int = 1               # One instance per agent name by default
MAX_LLM_DESIGNS: int = 3            # LLM-designed novel agents per session
SPAWN_COOLDOWN_SECONDS: float = 0.5 # Minimum gap between any two spawn calls

# Agents that are allowed to have >1 simultaneous instance
MULTI_INSTANCE_ALLOWED: frozenset[str] = frozenset()

# Agents whose instance uses an LLM (others must not call OllamaClient)
LLM_POWERED: frozenset[str] = frozenset({
    "code_generator",       # OPTIONAL — use_llm=False by default
    "result_analyzer",      # YES — qwen3.5:9b
    "strategy_improver",    # YES — qwen3.5:9b
    "batch_generator",      # OPTIONAL — delegates to code_generator
    "mommy_agent",          # SELF — agent selection / design only
    "daddy_agent",          # SELF — error diagnosis only
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class AgentStatus(Enum):
    SPAWNED = "spawned"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"


@dataclass
class AgentSpec:
    """Blueprint describing what an agent does and how to build it."""

    name: str
    role: str
    goal: str
    responsibility: str
    skills: list[str]
    module_path: str        # e.g. "agents.code_generator"
    class_name: str         # e.g. "CodeGeneratorAgent"
    init_kwargs: dict = field(default_factory=dict)
    llm_model: Optional[str] = None

    def __str__(self) -> str:
        llm = f" [LLM:{self.llm_model}]" if self.llm_model else " [no-LLM]"
        return f"AgentSpec({self.name} | {self.role}{llm})"


@dataclass
class SpawnedAgent:
    """A live agent instance created by MommyAgent."""

    spec: AgentSpec
    instance: Any
    status: AgentStatus = AgentStatus.SPAWNED
    spawned_at: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        return f"<SpawnedAgent {self.spec.name} [{self.status.value}]>"

    @property
    def is_active(self) -> bool:
        return self.status in (AgentStatus.SPAWNED, AgentStatus.RUNNING)


@dataclass
class SpawnPolicy:
    """Governance rules passed at construction time to override defaults."""

    max_total: int = MAX_TOTAL_AGENTS
    max_per_role: int = MAX_PER_ROLE
    max_llm_designs: int = MAX_LLM_DESIGNS
    cooldown_seconds: float = SPAWN_COOLDOWN_SECONDS
    allow_novel_agents: bool = True     # False = only registry agents allowed


# ---------------------------------------------------------------------------
# MommyAgent
# ---------------------------------------------------------------------------


class MommyAgent:
    """
    Dynamic agent factory governed by hard spawn limits.

    Rules enforced on every spawn:
    - Total active agents < policy.max_total
    - Same-name agent not already active (unless in MULTI_INSTANCE_ALLOWED)
    - LLM-designed agents capped at policy.max_llm_designs
    - Cooldown between spawns (prevents burst loops)
    """

    # ------------------------------------------------------------------
    # Registry — single source of truth for all known agents
    # ------------------------------------------------------------------

    REGISTRY: dict[str, AgentSpec] = {
        # ── Core pipeline (STANDARD_PIPELINE order) ────────────────────
        "code_generator": AgentSpec(
            name="code_generator",
            role="MQL5 Strategy Developer",
            goal="Generate constraint-passing MQL5 EA files via Jinja2 templates",
            responsibility="Render templates; optionally enrich comments with LLM",
            skills=["jinja2_rendering", "mql5_syntax", "constraint_validation"],
            module_path="agents.code_generator",
            class_name="CodeGeneratorAgent",
            llm_model="qwen2.5-coder:14b",  # optional — use_llm=False by default
        ),
        "backtest_runner": AgentSpec(
            name="backtest_runner",
            role="Backtesting Engineer",
            goal="Run MT5 Strategy Tester and return the HTML report path",
            responsibility="Copy .mq5, launch Wine/MT5, poll for report",
            skills=["subprocess_control", "wine_integration", "file_polling"],
            module_path="agents.backtest_runner",
            class_name="BacktestRunnerAgent",
            llm_model=None,  # NO LLM
        ),
        "report_parser": AgentSpec(
            name="report_parser",
            role="Data Extraction Specialist",
            goal="Parse UTF-16 LE MT5 HTML reports → BacktestResult",
            responsibility="BeautifulSoup table extraction, metric normalization",
            skills=["html_parsing", "utf16_encoding", "metric_extraction"],
            module_path="agents.report_parser",
            class_name="ReportParser",
            llm_model=None,  # NO LLM — rule-based only
        ),
        "result_analyzer": AgentSpec(
            name="result_analyzer",
            role="Performance Analyst",
            goal="Identify root-cause weaknesses in a backtest result",
            responsibility="LLM comparison of metrics vs targets → AnalysisReport",
            skills=["metrics_analysis", "weakness_identification", "llm_reasoning"],
            module_path="agents.result_analyzer",
            class_name="ResultAnalyzerAgent",
            llm_model="qwen3.5:9b",  # YES — always uses LLM
        ),
        "strategy_improver": AgentSpec(
            name="strategy_improver",
            role="Quant Strategy Optimizer",
            goal="Propose StrategyConfig mutations to improve next iteration",
            responsibility="Rule-based + LLM parameter changes from weakness report",
            skills=["parameter_optimization", "rule_engine", "llm_mutation"],
            module_path="agents.strategy_improver",
            class_name="StrategyImproverAgent",
            llm_model="qwen3.5:9b",  # YES — always uses LLM
        ),

        # ── Support agents ──────────────────────────────────────────────
        "news_filter": AgentSpec(
            name="news_filter",
            role="Economic Calendar Monitor",
            goal="Block trading during high-impact forex news windows",
            responsibility="Fetch ForexFactory calendar, return blackout periods",
            skills=["http_fetching", "html_parsing", "calendar_parsing"],
            module_path="agents.news_filter",
            class_name="NewsFilterAgent",
            llm_model=None,  # NO LLM — HTML scraping only
        ),
        "batch_generator": AgentSpec(
            name="batch_generator",
            role="Batch Strategy Producer",
            goal="Generate N variants across multiple symbols in one shot",
            responsibility="Parallel code generation + multi-symbol cloning",
            skills=["batch_generation", "multi_symbol", "parallel_execution"],
            module_path="agents.batch_generator",
            class_name="HybridBatchGeneratorAgent",
            llm_model="qwen2.5-coder:14b",  # OPTIONAL — delegates to code_generator
        ),
        "forward_test_manager": AgentSpec(
            name="forward_test_manager",
            role="Forward Test Monitor",
            goal="Track live champion performance and auto-promote when thresholds pass",
            responsibility="Poll bridge for live trades, compare vs backtest baseline",
            skills=["live_monitoring", "pf_tracking", "auto_promotion"],
            module_path="agents.forward_test_manager",
            class_name="ForwardTestManager",
            llm_model=None,  # NO LLM — rule-based PF comparison
        ),
        "market_regime_detector": AgentSpec(
            name="market_regime_detector",
            role="Market Regime Classifier",
            goal="Label market as trending / ranging / volatile",
            responsibility="ATR + ADX calculation for strategy selection",
            skills=["technical_analysis", "regime_classification", "adx_atr"],
            module_path="agents.market_regime_detector",
            class_name="MarketRegimeDetector",
            llm_model=None,  # NO LLM — pure math
        ),
        "signal_agent": AgentSpec(
            name="signal_agent",
            role="Live Signal Generator",
            goal="Emit buy/sell signals from champion EA logic in real time",
            responsibility="Apply entry logic, write signals to bridge IPC",
            skills=["signal_generation", "bridge_ipc", "real_time_processing"],
            module_path="agents.signal_agent",
            class_name="SignalAgent",
            llm_model=None,  # NO LLM — deterministic rule engine
        ),
        "live_trade_agent": AgentSpec(
            name="live_trade_agent",
            role="Live Trade Executor",
            goal="Execute MT5 orders via bridge with emergency DD protection",
            responsibility="Read signals, size lots, send orders, monitor equity",
            skills=["order_execution", "risk_management", "bridge_ipc"],
            module_path="agents.live_trade_agent",
            class_name="LiveTradeAgent",
            llm_model=None,  # NO LLM — must be deterministic for live trading
        ),
        # multi_symbol_orchestrator removed — XAUUSD-only, direct OrchestratorAgent
        "scheduler_agent": AgentSpec(
            name="scheduler_agent",
            role="Loop Scheduler",
            goal="Trigger improvement loop runs on a cron schedule or event",
            responsibility="APScheduler cron jobs, LLM semaphore, DB audit trail",
            skills=["cron_scheduling", "async_execution", "semaphore_management", "db_audit"],
            module_path="agents.scheduler_agent",
            class_name="SchedulerAgent",
            llm_model=None,  # NO LLM — scheduling / gating only
        ),
    }

    # Minimum agents required for one improvement cycle
    STANDARD_PIPELINE: list[str] = [
        "code_generator",
        "backtest_runner",
        "report_parser",
        "result_analyzer",
        "strategy_improver",
    ]

    def __init__(
        self,
        ollama_client: Optional[Any] = None,
        policy: Optional[SpawnPolicy] = None,
    ) -> None:
        self._ollama = ollama_client
        self._policy = policy or SpawnPolicy()
        self._spawned: dict[str, SpawnedAgent] = {}
        self._llm_design_count: int = 0
        self._last_spawn_time: float = 0.0

    # ------------------------------------------------------------------
    # Spawn by registry name  (primary entry point)
    # ------------------------------------------------------------------

    def spawn(self, name: str, **override_kwargs: Any) -> SpawnedAgent:
        """
        Spawn a known agent from the registry.

        Raises SpawnDenied if any governance rule is violated.
        """
        if name not in self.REGISTRY:
            raise KeyError(f"Unknown agent '{name}'. Known: {list(self.REGISTRY)}")
        self._enforce_spawn_policy(name)
        spec = self.REGISTRY[name]
        merged = {**spec.init_kwargs, **override_kwargs}
        return self._instantiate(spec, merged)

    # ------------------------------------------------------------------
    # Spawn from a task description  (LLM-assisted)
    # ------------------------------------------------------------------

    def spawn_for_task(self, task_description: str) -> SpawnedAgent:
        """
        Select and spawn the best agent for a plain-language task.
        Falls back to keyword matching when no LLM is available.
        """
        spec = self._select_or_design_spec(task_description)
        self._enforce_spawn_policy(spec.name)
        return self._instantiate(spec, spec.init_kwargs)

    # ------------------------------------------------------------------
    # Design a brand-new agent via LLM  (expensive — capped)
    # ------------------------------------------------------------------

    def design_agent(self, task_description: str) -> AgentSpec:
        """
        Ask the LLM to design an AgentSpec for a task no existing agent handles.

        Capped at policy.max_llm_designs per session.
        Returns the spec — does NOT instantiate. Call register() + spawn() after.
        """
        if self._ollama is None:
            raise RuntimeError("MommyAgent needs an OllamaClient to design new agents")
        if self._llm_design_count >= self._policy.max_llm_designs:
            raise SpawnDenied(
                f"LLM agent design cap reached ({self._policy.max_llm_designs}). "
                "Increase SpawnPolicy.max_llm_designs or reuse an existing agent."
            )
        if not self._policy.allow_novel_agents:
            raise SpawnDenied(
                "Novel agent design is disabled (SpawnPolicy.allow_novel_agents=False)."
            )

        system = (
            "You are an AI system architect for a MQL5/MetaTrader 5 trading bot. "
            "Design a Python agent spec as JSON with exactly these keys: "
            "name (snake_case str), role (str), goal (str), responsibility (str), "
            "skills (list[str]), module_path (str), class_name (str), "
            "llm_model (str or null). "
            "Only set llm_model if the agent truly needs generative AI reasoning. "
            "Prefer rule-based implementations when possible."
        )
        prompt = f"Design an agent that can: {task_description}"

        data = self._ollama.analyze(prompt=prompt, system=system)
        self._llm_design_count += 1

        spec = AgentSpec(
            name=data.get("name", "custom_agent"),
            role=data.get("role", "Custom Agent"),
            goal=data.get("goal", task_description),
            responsibility=data.get("responsibility", ""),
            skills=data.get("skills", []),
            module_path=data.get("module_path", "agents.custom"),
            class_name=data.get("class_name", "CustomAgent"),
            llm_model=data.get("llm_model"),
        )
        logger.info(
            f"MommyAgent: designed new spec [{self._llm_design_count}/"
            f"{self._policy.max_llm_designs}] — {spec}"
        )
        return spec

    # ------------------------------------------------------------------
    # Spawn from an explicit spec
    # ------------------------------------------------------------------

    def spawn_from_spec(self, spec: AgentSpec, **init_kwargs: Any) -> SpawnedAgent:
        """Instantiate an agent directly from any AgentSpec."""
        self._enforce_spawn_policy(spec.name)
        merged = {**spec.init_kwargs, **init_kwargs}
        return self._instantiate(spec, merged)

    # ------------------------------------------------------------------
    # Auto-fill pipeline gaps  (safe — only touches STANDARD_PIPELINE)
    # ------------------------------------------------------------------

    def fill_pipeline_gaps(self, active: list[str]) -> list[SpawnedAgent]:
        """
        Spawn only the standard pipeline agents that are missing from *active*.
        Never touches optional/support agents.
        """
        gaps = [n for n in self.STANDARD_PIPELINE if n not in active]
        if not gaps:
            logger.info("MommyAgent: pipeline complete — no gaps")
            return []

        logger.info(f"MommyAgent: filling {len(gaps)} gap(s): {gaps}")
        result: list[SpawnedAgent] = []
        for name in gaps:
            try:
                result.append(self.spawn(name))
            except SpawnDenied as exc:
                logger.warning(f"MommyAgent: spawn denied for '{name}': {exc}")
            except Exception as exc:
                logger.error(f"MommyAgent: failed to spawn '{name}': {exc}")
        return result

    # ------------------------------------------------------------------
    # Registry management
    # ------------------------------------------------------------------

    def register(self, spec: AgentSpec) -> None:
        """Add a new blueprint. Existing name is overwritten with a warning."""
        if spec.name in self.REGISTRY:
            logger.warning(f"MommyAgent: overwriting existing blueprint '{spec.name}'")
        self.REGISTRY[spec.name] = spec
        logger.info(f"MommyAgent: registered blueprint — {spec}")

    def unregister(self, name: str) -> None:
        self.REGISTRY.pop(name, None)

    def list_blueprints(self) -> list[str]:
        return list(self.REGISTRY)

    def describe(self, name: str) -> str:
        """Human-readable spec summary, including LLM status."""
        spec = self.REGISTRY.get(name)
        if spec is None:
            return f"Unknown agent '{name}'"
        llm_flag = "YES — " + spec.llm_model if spec.llm_model else "NO"
        return (
            f"[{spec.name}]\n"
            f"  Role:           {spec.role}\n"
            f"  Goal:           {spec.goal}\n"
            f"  Responsibility: {spec.responsibility}\n"
            f"  Skills:         {', '.join(spec.skills)}\n"
            f"  Module:         {spec.module_path}.{spec.class_name}\n"
            f"  LLM powered:    {llm_flag}"
        )

    def describe_all(self) -> str:
        """Print the full LLM power map for all registered agents."""
        lines = ["Agent LLM Power Map", "=" * 60]
        for name, spec in self.REGISTRY.items():
            llm = f"YES ({spec.llm_model})" if spec.llm_model else "no"
            active_flag = " [ACTIVE]" if name in self._spawned and self._spawned[name].is_active else ""
            lines.append(f"  {name:<30} LLM: {llm}{active_flag}")
        lines.append("=" * 60)
        lines.append(
            f"Active: {self.active_count}/{self._policy.max_total}  "
            f"LLM designs used: {self._llm_design_count}/{self._policy.max_llm_designs}"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Live agent tracking
    # ------------------------------------------------------------------

    def list_agents(self) -> list[SpawnedAgent]:
        return list(self._spawned.values())

    def get_agent(self, name: str) -> Optional[SpawnedAgent]:
        return self._spawned.get(name)

    @property
    def active_count(self) -> int:
        return sum(1 for a in self._spawned.values() if a.is_active)

    def mark_running(self, name: str) -> None:
        if name in self._spawned:
            self._spawned[name].status = AgentStatus.RUNNING

    def mark_done(self, name: str) -> None:
        if name in self._spawned:
            self._spawned[name].status = AgentStatus.DONE

    def mark_failed(self, name: str) -> None:
        if name in self._spawned:
            self._spawned[name].status = AgentStatus.FAILED

    def retire(self, name: str) -> None:
        """Mark an agent as done and free its slot for re-spawning."""
        self.mark_done(name)
        logger.info(f"MommyAgent: retired '{name}'")

    # ------------------------------------------------------------------
    # Governance enforcement
    # ------------------------------------------------------------------

    def _enforce_spawn_policy(self, name: str) -> None:
        """
        Raise SpawnDenied if any governance rule is violated.

        Rules checked (in order):
        1. Cooldown between spawns
        2. Total active agent cap
        3. Duplicate active agent (unless MULTI_INSTANCE_ALLOWED)
        """
        # 1. Cooldown
        elapsed = time.time() - self._last_spawn_time
        if elapsed < self._policy.cooldown_seconds:
            wait = self._policy.cooldown_seconds - elapsed
            logger.debug(f"MommyAgent: spawn cooldown — waiting {wait:.2f}s")
            time.sleep(wait)

        # 2. Total cap
        if self.active_count >= self._policy.max_total:
            raise SpawnDenied(
                f"Total agent cap reached ({self._policy.max_total} active). "
                "Call retire() or mark_done() on finished agents first."
            )

        # 3. Duplicate check
        existing = self._spawned.get(name)
        if existing and existing.is_active and name not in MULTI_INSTANCE_ALLOWED:
            raise SpawnDenied(
                f"Agent '{name}' is already active [{existing.status.value}]. "
                "Call retire('{name}') before re-spawning, or add it to MULTI_INSTANCE_ALLOWED."
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_or_design_spec(self, task_description: str) -> AgentSpec:
        """LLM matching → keyword fallback → design new."""
        if self._ollama is None:
            return self._keyword_match(task_description)

        candidates = "\n".join(
            f"- {n}: {s.goal}" for n, s in self.REGISTRY.items()
        )
        system = (
            "You are an AI orchestration assistant. "
            "Given a task and a list of available agents, respond with JSON: "
            '{"agent_name": str or null, "reason": str}. '
            "Prefer existing agents. Set agent_name=null only if truly none fit."
        )
        prompt = (
            f"Task: {task_description}\n\n"
            f"Available agents:\n{candidates}\n\n"
            "Best match?"
        )
        try:
            data = self._ollama.analyze(prompt=prompt, system=system)
            agent_name: Optional[str] = data.get("agent_name")
            reason: str = data.get("reason", "")
            logger.info(f"MommyAgent: LLM matched '{agent_name}' — {reason}")
            if agent_name and agent_name in self.REGISTRY:
                return self.REGISTRY[agent_name]
            return self.design_agent(task_description)
        except Exception as exc:
            logger.warning(f"MommyAgent: LLM selection failed ({exc}), using keyword match")
            return self._keyword_match(task_description)

    def _keyword_match(self, task_description: str) -> AgentSpec:
        lower = task_description.lower()
        for name, spec in self.REGISTRY.items():
            if any(skill.replace("_", " ") in lower for skill in spec.skills):
                logger.info(f"MommyAgent: keyword-matched '{name}'")
                return spec
        raise RuntimeError(
            f"No agent matches '{task_description}' and no LLM available to design one."
        )

    def _instantiate(self, spec: AgentSpec, init_kwargs: dict) -> SpawnedAgent:
        """Import module, call constructor, register in _spawned."""
        # Inject shared OllamaClient only when spec declares an LLM model
        if spec.llm_model and self._ollama is not None and "ollama" not in init_kwargs:
            init_kwargs = {"ollama": self._ollama, **init_kwargs}

        try:
            module = importlib.import_module(spec.module_path)
        except ImportError as exc:
            raise RuntimeError(
                f"MommyAgent: cannot import '{spec.module_path}'. "
                f"Create the module first. ({exc})"
            ) from exc

        try:
            cls = getattr(module, spec.class_name)
        except AttributeError as exc:
            raise RuntimeError(
                f"MommyAgent: '{spec.class_name}' not found in '{spec.module_path}'. ({exc})"
            ) from exc

        try:
            instance = cls(**init_kwargs)
        except TypeError as exc:
            raise RuntimeError(
                f"MommyAgent: {spec.class_name}(**{list(init_kwargs)}) failed: {exc}"
            ) from exc

        spawned = SpawnedAgent(spec=spec, instance=instance)
        self._spawned[spec.name] = spawned
        self._last_spawn_time = time.time()

        llm_note = f" [LLM:{spec.llm_model}]" if spec.llm_model else " [no-LLM]"
        logger.info(f"MommyAgent: spawned '{spec.name}'{llm_note} — {spec.goal}")
        return spawned


# ---------------------------------------------------------------------------
# Governance exception
# ---------------------------------------------------------------------------


class SpawnDenied(Exception):
    """Raised when a spawn request violates MommyAgent governance rules."""
