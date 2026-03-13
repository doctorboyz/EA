"""
StrategyImproverAgent (Agent 5) — Proposes parameter improvements.

Two-stage improvement:
  Stage 1 (Rule-based): Deterministic fixes for known patterns
  Stage 2 (LLM-based): llama3.2:3b suggests additional tuning

Returns a new StrategyConfig with incremented version + change_rationale.
"""

import logging
import os
from copy import deepcopy
from typing import Optional

from core.strategy_config import StrategyConfig, StrategyVersion, AnalysisReport, Weakness
from core.constraint_validator import ConstraintValidator
from core.ollama_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parameter step sizes — how much to change each parameter per iteration
# ---------------------------------------------------------------------------

PARAM_STEPS = {
    "rsi_oversold":       2.0,   # tighten by 2 points
    "rsi_overbought":     2.0,
    "stop_loss_pips":     5,     # widen/tighten by 5 pips
    "take_profit_pips":   10,    # extend by 10 pips
    "breakeven_pips":     5,
    "trailing_stop_pips": 5,
    "atr_max_multiplier": 0.25,
    "risk_percent":       0.1,   # small risk adjustments
    "ema_period":         10,
    "lookback_period":    12,
}

PARAM_BOUNDS = {
    "rsi_oversold":       (20.0, 35.0),
    "rsi_overbought":     (65.0, 80.0),
    "stop_loss_pips":     (20,   60),
    "take_profit_pips":   (60,   150),
    "breakeven_pips":     (10,   30),
    "trailing_stop_pips": (10,   40),
    "atr_max_multiplier": (1.0,  3.0),
    "risk_percent":       (0.5,  2.0),
    "ema_period":         (150,  200),
    "lookback_period":    (48,   240),
}


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _load_improve_prompt() -> str:
    path = os.path.join(
        os.path.dirname(__file__), '..', 'templates', 'prompts', 'improve_system.txt'
    )
    with open(path) as f:
        return f.read().strip()


class StrategyImproverAgent:
    """
    Agent 5: Produces the next StrategyConfig version from an analysis report.

    Approach:
    1. Apply rule-based fixes first (fast, deterministic, always safe)
    2. Optionally ask LLM for additional parameter suggestions
    3. Validate result against ConstraintValidator (reject if fails)
    4. Return new config with bumped version + rationale

    Rule-based improvements:
    - PF too low + win rate ok → increase TP (better R/R)
    - PF too low + win rate low → tighten RSI (fewer, higher quality signals)
    - DD too high → reduce risk_percent
    - RF too low + PF ok → reduce drawdown via tighter trailing stop
    - Win/loss ratio low → increase TP or tighten SL
    - Too few trades → relax RSI or ATR filter
    """

    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.ollama = ollama or OllamaClient()
        self._system_prompt: Optional[str] = None

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _load_improve_prompt()
        return self._system_prompt

    # ------------------------------------------------------------------
    # Stage 1: Rule-based improvements
    # ------------------------------------------------------------------

    def _apply_rules(
        self,
        config: StrategyConfig,
        analysis: AnalysisReport,
        changes: dict,
    ) -> dict:
        """
        Apply deterministic rules based on which metrics are failing.
        Updates `changes` dict in place: {param: {from, to, reason}}
        """
        result_metrics = {w.metric: w for w in analysis.weaknesses}

        pf_weak = "profit_factor" in result_metrics
        dd_weak = "max_drawdown_pct" in result_metrics
        rf_weak = "recovery_factor" in result_metrics
        rr_weak = "avg_win_loss_ratio" in result_metrics

        # --- Drawdown too high: reduce risk ---
        if dd_weak and config.risk_percent > 0.6:
            new_val = _clamp(config.risk_percent - PARAM_STEPS["risk_percent"], 0.5, 2.0)
            changes["risk_percent"] = {
                "from": config.risk_percent,
                "to": new_val,
                "reason": "Drawdown too high — reducing risk_percent",
            }

        # --- PF too low: improve entry quality ---
        if pf_weak:
            w = result_metrics["profit_factor"]
            # Very few trades = filters too strict → relax RSI slightly
            if w.current_value < 1.0 and config.rsi_oversold > 22.0:
                new_val = _clamp(
                    config.rsi_oversold - PARAM_STEPS["rsi_oversold"],
                    *PARAM_BOUNDS["rsi_oversold"],
                )
                changes["rsi_oversold"] = {
                    "from": config.rsi_oversold,
                    "to": new_val,
                    "reason": "PF < 1.0: relaxing RSI oversold threshold slightly",
                }
            # PF between 1.0-1.4 and win rate ok → improve R/R via larger TP
            elif 1.0 <= w.current_value < 1.4 and config.take_profit_pips < 140:
                new_tp = _clamp(
                    config.take_profit_pips + PARAM_STEPS["take_profit_pips"],
                    *PARAM_BOUNDS["take_profit_pips"],
                )
                # Ensure 2:1 R/R still holds
                if new_tp >= config.stop_loss_pips * 2:
                    changes["take_profit_pips"] = {
                        "from": config.take_profit_pips,
                        "to": new_tp,
                        "reason": "PF 1.0-1.4: extending TP to improve R/R",
                    }

        # --- Win/loss ratio too low: widen TP or tighten SL ---
        if rr_weak and "take_profit_pips" not in changes:
            new_tp = _clamp(
                config.take_profit_pips + PARAM_STEPS["take_profit_pips"],
                *PARAM_BOUNDS["take_profit_pips"],
            )
            if new_tp >= config.stop_loss_pips * 2:
                changes["take_profit_pips"] = {
                    "from": config.take_profit_pips,
                    "to": new_tp,
                    "reason": "Win/loss ratio low — extending take_profit_pips",
                }

        # --- RF too low and DD is ok → problem is low net profit ---
        if rf_weak and not dd_weak and config.breakeven_pips > 12:
            new_be = _clamp(
                config.breakeven_pips - PARAM_STEPS["breakeven_pips"],
                *PARAM_BOUNDS["breakeven_pips"],
            )
            changes["breakeven_pips"] = {
                "from": config.breakeven_pips,
                "to": new_be,
                "reason": "RF low: reducing breakeven to let more winners run",
            }

        return changes

    # ------------------------------------------------------------------
    # Stage 2: LLM suggestions
    # ------------------------------------------------------------------

    def _ask_llm(
        self,
        config: StrategyConfig,
        analysis: AnalysisReport,
        existing_changes: dict,
    ) -> dict:
        """
        Ask llama3.2:3b for additional parameter suggestions.
        Returns dict of {param: {from, to, reason}} to merge with existing_changes.
        """
        prompt = self._build_llm_prompt(config, analysis, existing_changes)

        try:
            data = self.ollama.analyze(
                prompt=prompt,
                system=self._get_system_prompt(),
            )
            suggested = data.get("param_changes", {})
            llm_changes: dict = {}
            for param, info in suggested.items():
                if param not in existing_changes and param in PARAM_BOUNDS:
                    lo, hi = PARAM_BOUNDS[param]
                    raw_val = info.get("to")
                    if raw_val is None:
                        continue
                    clamped = _clamp(raw_val, lo, hi)
                    llm_changes[param] = {
                        "from": getattr(config, param),
                        "to": clamped,
                        "reason": f"[LLM] {info.get('reason', 'LLM suggestion')}",
                    }
            return llm_changes
        except (OllamaError, KeyError) as e:
            logger.warning("LLM improvement step skipped: %s", e)
            return {}

    def _build_llm_prompt(
        self,
        config: StrategyConfig,
        analysis: AnalysisReport,
        existing_changes: dict,
    ) -> str:
        lines = [
            "## Current Strategy Parameters",
            f"- risk_percent: {config.risk_percent}",
            f"- ema_period: {config.ema_period}",
            f"- rsi_oversold: {config.rsi_oversold}  rsi_overbought: {config.rsi_overbought}",
            f"- stop_loss_pips: {config.stop_loss_pips}  take_profit_pips: {config.take_profit_pips}",
            f"- breakeven_pips: {config.breakeven_pips}  trailing_stop_pips: {config.trailing_stop_pips}",
            f"- atr_max_multiplier: {config.atr_max_multiplier}",
            f"- lookback_period: {config.lookback_period}",
            "",
            "## Analysis Summary",
            analysis.summary or "(no summary)",
            "",
            "## Failing Metrics",
        ]
        for w in analysis.weaknesses:
            lines.append(f"- {w.metric}: {w.current_value:.2f} (target: {w.target_value})")
        if existing_changes:
            lines.extend(["", "## Already-Applied Rule-Based Changes"])
            for p, c in existing_changes.items():
                lines.append(f"- {p}: {c['from']} → {c['to']} ({c['reason']})")
        lines.extend([
            "",
            "## Task",
            "Suggest 1-2 additional parameter changes NOT already applied above.",
            "Return JSON: {\"param_changes\": {\"param_name\": {\"to\": value, \"reason\": \"why\"}}}",
            "Only suggest parameters within these bounds:",
        ])
        for p, (lo, hi) in PARAM_BOUNDS.items():
            lines.append(f"  {p}: [{lo}, {hi}]")
        lines.append("Only change params that will meaningfully improve failing metrics.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def improve(
        self,
        analysis: AnalysisReport,
        current_config: StrategyConfig,
        use_llm: bool = True,
    ) -> StrategyConfig:
        """
        Generate the next strategy configuration.

        Args:
            analysis:       AnalysisReport from ResultAnalyzerAgent
            current_config: Current StrategyConfig to improve from
            use_llm:        Whether to ask Ollama for additional suggestions

        Returns:
            New StrategyConfig with bumped version and change_rationale
        """
        changes: dict = {}

        # Stage 1: rule-based
        changes = self._apply_rules(current_config, analysis, changes)

        # Stage 2: LLM (if requested)
        if use_llm:
            llm_changes = self._ask_llm(current_config, analysis, changes)
            changes.update(llm_changes)

        if not changes:
            logger.info("No improvements identified for version %s", current_config.version)
            # Return bumped iteration with no-change rationale
            return StrategyConfig(
                **{
                    **current_config.model_dump(exclude={"version", "change_rationale", "created_at"}),
                    "version": current_config.version.bump_iteration(),
                    "change_rationale": {"no_changes": "All metrics within acceptable range"},
                    "parent_version": str(current_config.version),
                }
            )

        # Build new config params
        new_params = current_config.model_dump(
            exclude={"version", "change_rationale", "created_at"}
        )
        for param, info in changes.items():
            new_params[param] = info["to"]
        new_params["version"] = current_config.version.bump_iteration()
        new_params["parent_version"] = str(current_config.version)
        new_params["change_rationale"] = {
            p: {"from": c["from"], "to": c["to"], "reason": c["reason"]}
            for p, c in changes.items()
        }

        # Attempt to build validated config
        try:
            new_config = StrategyConfig(**new_params)
        except Exception as e:
            logger.warning("Proposed config failed Pydantic validation: %s", e)
            # Return unchanged config with bumped iteration
            return StrategyConfig(
                **{
                    **current_config.model_dump(exclude={"version", "change_rationale", "created_at"}),
                    "version": current_config.version.bump_iteration(),
                    "change_rationale": {"validation_failed": str(e)},
                    "parent_version": str(current_config.version),
                }
            )

        # Final: check hard constraints
        is_valid, violations = ConstraintValidator.validate_config(new_config)
        if not is_valid:
            logger.warning(
                "Proposed config violates hard constraints: %s — returning unchanged",
                violations,
            )
            return StrategyConfig(
                **{
                    **current_config.model_dump(exclude={"version", "change_rationale", "created_at"}),
                    "version": current_config.version.bump_iteration(),
                    "change_rationale": {"constraint_violation": violations},
                    "parent_version": str(current_config.version),
                }
            )

        logger.info(
            "Improved config v%s → v%s: %d changes",
            current_config.version,
            new_config.version,
            len(changes),
        )
        return new_config
