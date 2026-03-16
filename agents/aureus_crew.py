"""
CrewAI Crew for Aureus AI — Intelligent LLM layer.

Wraps the deterministic agents (CodeGenerator, ResultAnalyzer, StrategyImprover)
as CrewAI agents with tools. Provides a clean interface for multi-agent orchestration.

Layers:
  - Deterministic: BacktestRunner → ReportParser → ConstraintValidator (pure Python)
  - Intelligence: CodeGenerator → ResultAnalyzer → StrategyImprover (via CrewAI crew.kickoff())
"""

import logging
from typing import Any, Dict, Optional
from crewai import Agent, Task, Crew, Process
from crewai.tools import BaseTool
from langchain_community.llms import Ollama

from core.strategy_config import StrategyConfig, BacktestResult
from core.ollama_client import OllamaClient
from agents.code_generator import CodeGeneratorAgent
from agents.result_analyzer import ResultAnalyzerAgent
from agents.strategy_improver import StrategyImproverAgent
from agents.market_regime_detector import MarketRegimeDetector, RegimeSnapshot

logger = logging.getLogger(__name__)


# ─── Tools wrapping existing Python agents ───────────────────────────────────

class GenerateEATool(BaseTool):
    """Generates MQL5 code using CodeGeneratorAgent."""
    name: str = "generate_ea"
    description: str = "Generate MQL5 Expert Advisor code from a StrategyConfig"

    code_gen_agent: CodeGeneratorAgent = None

    def _run(self, config: StrategyConfig, framework: str) -> str:
        """Render MQL5 template."""
        try:
            mql5_code = self.code_gen_agent.render_template(config, framework)
            return f"Generated {len(mql5_code)} bytes of MQL5 code. Framework: {framework}"
        except Exception as e:
            return f"Error generating code: {str(e)}"


class ValidateConfigTool(BaseTool):
    """Validates config against constraints."""
    name: str = "validate_config"
    description: str = "Check StrategyConfig against hard constraints"

    constraint_validator: Any = None

    def _run(self, config: StrategyConfig) -> str:
        """Validate config."""
        try:
            self.constraint_validator.validate_config(config)
            return f"✓ Config valid: {config.name} v{config.version}"
        except Exception as e:
            return f"✗ Config rejected: {str(e)}"


class AnalyzeResultTool(BaseTool):
    """Analyzes backtest results using ResultAnalyzerAgent."""
    name: str = "analyze_result"
    description: str = "Analyze BacktestResult to identify weaknesses"

    analyzer_agent: ResultAnalyzerAgent = None

    def _run(self, result: BacktestResult) -> str:
        """Analyze result and return weaknesses."""
        try:
            analysis = self.analyzer_agent.analyze(result)
            return f"Analysis: {analysis.summary[:500]}..."
        except Exception as e:
            return f"Error analyzing: {str(e)}"


class ImproveTool(BaseTool):
    """Proposes improvements using StrategyImproverAgent."""
    name: str = "improve_strategy"
    description: str = "Propose parameter improvements based on analysis"

    improver_agent: StrategyImproverAgent = None

    def _run(self, config: StrategyConfig, analysis: Any) -> str:
        """Propose improvements."""
        try:
            new_config = self.improver_agent.improve(config, analysis)
            changes = self.improver_agent.describe_changes(config, new_config)
            return f"Proposed improvements: {changes[:500]}..."
        except Exception as e:
            return f"Error proposing improvements: {str(e)}"


# ─── Crew definition ──────────────────────────────────────────────────────────

class AureusCrewAI:
    """
    CrewAI crew for intelligent strategy improvement loop.

    Agents:
      1. CodeGenerator — generates MQL5 from config
      2. ResultAnalyzer — identifies weaknesses
      3. StrategyImprover — proposes parameter changes

    Usage:
      crew = AureusCrewAI(config)
      result = crew.analyze_and_improve(backtest_result, market_regime)
    """

    def __init__(self, config: dict, dry_run: bool = False):
        """Initialize crew with config."""
        self._cfg = config
        self.dry_run = dry_run
        self._ollama_client = OllamaClient(config.get('ollama', {}))

        # Instantiate Python agents that will be wrapped as tools
        self.code_gen_agent = CodeGeneratorAgent(config)
        self.analyzer_agent = ResultAnalyzerAgent(config)
        self.improver_agent = StrategyImproverAgent(config)

        # CrewAI LLM (via Ollama)
        self.llm = Ollama(
            base_url=config.get('ollama', {}).get('base_url', 'http://localhost:11434'),
            model=config.get('ollama', {}).get('code_gen_model', 'qwen2.5-coder:14b'),
            temperature=0.7,
        )

        self._setup_crew()

    def _setup_crew(self):
        """Create CrewAI agents and crew."""
        # Tools
        gen_tool = GenerateEATool(code_gen_agent=self.code_gen_agent)
        val_tool = ValidateConfigTool(constraint_validator=self.code_gen_agent.constraint_validator)
        ana_tool = AnalyzeResultTool(analyzer_agent=self.analyzer_agent)
        imp_tool = ImproveTool(improver_agent=self.improver_agent)

        # Agents (sequential: gen → analyze → improve)
        self.code_gen_crew_agent = Agent(
            role="XAUUSD MQL5 Strategy Developer",
            goal=(
                "Generate robust MQL5 Expert Advisor code for XAUUSD gold trading. "
                "Target: Champion tier (PF > 1.3, DD < 30%, RF > 1.0, W/L > 1.5). "
                "Must pass ConstraintValidator (no FixedLossUSD, percentage-based risk only, R/R >= 2:1)."
            ),
            backstory=(
                "Expert C++ developer specializing in MetaTrader 5 gold trading EAs. "
                "Deep knowledge of XAUUSD volatility patterns, ATR-based entries, and "
                "8 framework types (XAUBreakout, TrendFollowing, MeanReversion, etc.). "
                "All code must pass hard constraints — the V4 FixedLossUSD bug blew an account."
            ),
            tools=[gen_tool, val_tool],
            llm=self.llm,
            verbose=False,
        )

        self.analyzer_crew_agent = Agent(
            role="XAUUSD Performance Analyst",
            goal=(
                "Identify why a XAUUSD strategy fails to reach Champion tier. "
                "Champion targets: PF > 1.3, DD < 30%, RF > 1.0, W/L > 1.5. "
                "Gold targets: PF > 1.8, DD < 20%, RF > 2.0, W/L > 2.0. "
                "Pinpoint the exact metric gap and root cause."
            ),
            backstory=(
                "Quantitative analyst specialized in gold/XAUUSD strategy evaluation. "
                "Expert at diagnosing: high DD from oversized positions, low PF from "
                "bad entry timing, poor W/L from premature exits. Considers market regime "
                "(trending vs choppy) when analyzing results."
            ),
            tools=[ana_tool],
            llm=self.llm,
            verbose=False,
        )

        self.improver_crew_agent = Agent(
            role="XAUUSD Quant Optimizer",
            goal=(
                "Propose parameter changes to push XAUUSD EA toward Champion tier "
                "(PF > 1.3, DD < 30%, RF > 1.0, W/L > 1.5). "
                "Balance exploitation (refine what works) with exploration (try new frameworks). "
                "Must respect bounds: risk 0.5-2%, SL 20-60 pips, TP >= 2x SL."
            ),
            backstory=(
                "Experienced quant optimizer for gold trading strategies. "
                "Knows XAUUSD needs wider stops (high volatility), ATR-based entries, "
                "and conservative risk (0.5% default). Uses 8 frameworks rotated via "
                "ExperienceDB (80% exploit / 20% explore)."
            ),
            tools=[imp_tool],
            llm=self.llm,
            verbose=False,
        )

        # Tasks
        self.gen_task = Task(
            description=(
                "Generate MQL5 Expert Advisor code for XAUUSD using the given StrategyConfig and framework. "
                "Validate all hard constraints (no FixedLossUSD, R/R >= 2:1, percentage-based risk). "
                "Framework options: XAUBreakout, TrendFollowing, Breakout, MeanReversion, SniperEntry, "
                "CandlePattern, IchimokuCloud, GridTrading."
            ),
            agent=self.code_gen_crew_agent,
            expected_output="Generated MQL5 code path and constraint validation confirmation",
        )

        self.ana_task = Task(
            description=(
                "Analyze the XAUUSD backtest result against Champion-tier targets: "
                "PF > 1.3, DD < 30%, RF > 1.0, W/L > 1.5. "
                "Identify the biggest gap, its root cause, and whether the framework choice "
                "was appropriate for the current market regime."
            ),
            agent=self.analyzer_crew_agent,
            expected_output="Weakness list with severity, root cause, and framework-specific insights",
        )

        self.imp_task = Task(
            description=(
                "Propose parameter improvements to close the gap toward Champion tier. "
                "Consider: adjusting SL/TP ratio, risk percent, indicator periods, "
                "switching framework if current one underperforms. "
                "Keep changes small (one parameter step per iteration) to isolate effects."
            ),
            agent=self.improver_crew_agent,
            expected_output="Specific parameter changes with rationale and expected impact on metrics",
        )

        # Crew (sequential process)
        self.crew = Crew(
            agents=[self.code_gen_crew_agent, self.analyzer_crew_agent, self.improver_crew_agent],
            tasks=[self.gen_task, self.ana_task, self.imp_task],
            process=Process.sequential,
            memory=True,
            verbose=False,
        )

    def analyze_and_improve(
        self,
        config: StrategyConfig,
        result: BacktestResult,
        regime: Optional[RegimeSnapshot] = None,
    ) -> Dict[str, Any]:
        """
        Run crew to analyze result and propose improvements.

        Args:
            config: Current strategy config
            result: Backtest result to analyze
            regime: Market regime (optional)

        Returns:
            Dict with analysis and improved config
        """
        if self.dry_run:
            logger.info("[CrewAI] DRY RUN — skipping crew.kickoff()")
            return {
                'analysis': f"Dry run analysis of {result.strategy_version}",
                'improved_config': config,
                'changes': [],
            }

        logger.info("[CrewAI] Starting crew.kickoff() for %s", result.strategy_version)

        try:
            inputs = {
                'config': config.model_dump_json(),
                'result': result.model_dump_json(),
                'regime': regime.model_dump_json() if regime else 'unknown',
            }

            # Run crew
            result_output = self.crew.kickoff(inputs=inputs)

            logger.info("[CrewAI] Crew completed: %s", str(result_output)[:200])

            # Parse crew output and extract improved config
            # Note: In practice, you'd parse the LLM output to extract the new config
            # For now, return the original config + analysis
            return {
                'analysis': str(result_output),
                'improved_config': config,  # Would be parsed from crew output
                'changes': [],              # Would be extracted from improved_config
            }

        except Exception as e:
            logger.error("[CrewAI] Crew failed: %s", e, exc_info=True)
            return {
                'analysis': f"Error: {str(e)}",
                'improved_config': config,
                'changes': [],
            }
