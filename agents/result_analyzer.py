"""
ResultAnalyzerAgent (Agent 4) — Identifies weaknesses in backtest results via llama3.2:3b.

Inputs:  BacktestResult + optional prior history list
Outputs: AnalysisReport (weaknesses, recommendations, summary)
"""

import json
import logging
import os
from typing import Optional

from core.strategy_config import BacktestResult, AnalysisReport, Weakness
from core.ollama_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — loaded from templates/prompts/analysis_system.txt
# ---------------------------------------------------------------------------

def _load_system_prompt() -> str:
    path = os.path.join(
        os.path.dirname(__file__), '..', 'templates', 'prompts', 'analysis_system.txt'
    )
    with open(path) as f:
        return f.read().strip()


# ---------------------------------------------------------------------------
# Target definitions (from AUREUS_INSPECTION_GUIDELINE.md)
# ---------------------------------------------------------------------------

TARGETS = {
    "profit_factor":     {"target": 1.5,  "direction": "above", "label": "Profit Factor"},
    "max_drawdown_pct":  {"target": 15.0, "direction": "below", "label": "Max Drawdown %"},
    "recovery_factor":   {"target": 3.0,  "direction": "above", "label": "Recovery Factor"},
    "avg_win_loss_ratio":{"target": 2.0,  "direction": "above", "label": "Win/Loss Ratio"},
}


def _severity(gap_pct: float) -> str:
    """Map gap percentage to severity label."""
    if gap_pct >= 50:
        return "critical"
    elif gap_pct >= 25:
        return "high"
    elif gap_pct >= 10:
        return "medium"
    return "low"


def _build_weaknesses(result: BacktestResult) -> list[Weakness]:
    """Rule-based weakness detection — no LLM needed for this part."""
    weaknesses = []

    checks = [
        ("profit_factor",      result.profit_factor,      1.5,  "above"),
        ("max_drawdown_pct",   result.max_drawdown_pct,   15.0, "below"),
        ("recovery_factor",    result.recovery_factor,    3.0,  "above"),
        ("avg_win_loss_ratio", result.avg_win_loss_ratio, 2.0,  "above"),
    ]

    for metric, value, target, direction in checks:
        if direction == "above" and value < target:
            gap = ((target - value) / target) * 100
            weaknesses.append(Weakness(
                metric=metric,
                current_value=value,
                target_value=target,
                gap=round(gap, 1),
                severity=_severity(gap),
                description=f"{TARGETS[metric]['label']} is {value:.2f}, target >{target}. "
                            f"Gap: {gap:.1f}% below target.",
                probable_causes=_probable_causes(metric, value, target, result),
            ))
        elif direction == "below" and value > target:
            gap = ((value - target) / target) * 100
            weaknesses.append(Weakness(
                metric=metric,
                current_value=value,
                target_value=target,
                gap=round(gap, 1),
                severity=_severity(gap),
                description=f"{TARGETS[metric]['label']} is {value:.2f}%, target <{target}%. "
                            f"Exceeds target by {gap:.1f}%.",
                probable_causes=_probable_causes(metric, value, target, result),
            ))

    return weaknesses


def _probable_causes(metric: str, value: float, target: float, result: BacktestResult) -> list[str]:
    """Heuristic probable causes for each failing metric."""
    causes: list[str] = []

    if metric == "profit_factor":
        if result.win_rate_pct < 40:
            causes.append("Low win rate — entry signals may be too permissive")
        if result.avg_win_loss_ratio < 1.5:
            causes.append("Avg win/loss ratio < 1.5 — TP may be too small relative to SL")
        if result.total_trades < 20:
            causes.append("Very few trades — filters may be too restrictive")

    elif metric == "max_drawdown_pct":
        if result.max_consecutive_losses > 5:
            causes.append(f"High consecutive losses ({result.max_consecutive_losses}) — "
                          "consider tightening entry or reducing risk_percent")
        if value > 50:
            causes.append("CRITICAL: Drawdown > 50% — check for fixed USD risk (V4 pattern)")

    elif metric == "recovery_factor":
        causes.append("Low recovery factor = low net profit relative to drawdown")
        if result.net_profit < 0:
            causes.append("Strategy is net losing — entry or exit logic needs rework")

    elif metric == "avg_win_loss_ratio":
        causes.append("Winners are not large enough relative to losers")
        causes.append("Consider increasing take_profit_pips or tightening stop_loss_pips")
        if result.win_rate_pct > 55:
            causes.append("High win rate but small wins — trailing stop may be cutting profits")

    return causes


class ResultAnalyzerAgent:
    """
    Agent 4: Analyzes backtest results to identify weaknesses.

    Works in two stages:
    1. Rule-based: Always identifies objective metric failures
    2. LLM-based: llama3.2:3b provides deeper context + root cause analysis
       (falls back gracefully if Ollama is unavailable)
    """

    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.ollama = ollama or OllamaClient()
        self._system_prompt: Optional[str] = None

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _load_system_prompt()
        return self._system_prompt

    def _build_prompt(
        self,
        result: BacktestResult,
        weaknesses: list[Weakness],
        history: Optional[list[BacktestResult]] = None,
    ) -> str:
        """Build the LLM analysis prompt."""
        lines = [
            "## Current Backtest Result",
            f"- Strategy: {result.strategy_version}",
            f"- Symbol: {result.symbol}  Timeframe: {result.timeframe}",
            f"- Period: {result.date_from} → {result.date_to}",
            f"- Capital: ${result.initial_capital:.0f}",
            "",
            "### Metrics vs Targets",
            f"| Metric | Value | Target | Pass? |",
            f"|---|---|---|---|",
            f"| Profit Factor | {result.profit_factor:.2f} | >1.5 | {'✓' if result.meets_pf_target else '✗'} |",
            f"| Max Drawdown | {result.max_drawdown_pct:.1f}% | <15% | {'✓' if result.meets_dd_target else '✗'} |",
            f"| Recovery Factor | {result.recovery_factor:.2f} | >3.0 | {'✓' if result.meets_rf_target else '✗'} |",
            f"| Win/Loss Ratio | {result.avg_win_loss_ratio:.2f} | >2.0 | {'✓' if result.meets_rr_target else '✗'} |",
            "",
            f"- Trades: {result.total_trades}  Win rate: {result.win_rate_pct:.1f}%",
            f"- Net profit: ${result.net_profit:.2f}",
            f"- Consecutive losses: {result.max_consecutive_losses}",
        ]

        if weaknesses:
            lines.extend(["", "### Identified Weaknesses"])
            for w in weaknesses:
                lines.append(f"- [{w.severity.upper()}] {w.description}")

        if history:
            lines.extend(["", f"### Prior {min(len(history), 5)} Backtest History"])
            for h in history[-5:]:
                lines.append(
                    f"- {h.strategy_version}: PF={h.profit_factor:.2f}, "
                    f"DD={h.max_drawdown_pct:.1f}%, "
                    f"Trades={h.total_trades}"
                )

        lines.extend([
            "",
            "## Task",
            "Analyze the above backtest result. Return a JSON object with:",
            '{"summary": "1-2 sentence overall assessment",',
            ' "root_causes": ["cause1", "cause2"],',
            ' "recommendations": ["action1", "action2", "action3"]}',
            "",
            "Be specific to the metrics. If profit factor is low, say what parameter to change.",
        ])
        return "\n".join(lines)

    def analyze(
        self,
        result: BacktestResult,
        history: Optional[list[BacktestResult]] = None,
    ) -> AnalysisReport:
        """
        Analyze a backtest result.

        Args:
            result:  The BacktestResult to analyze
            history: Optional prior results for trend analysis

        Returns:
            AnalysisReport with weaknesses, recommendations, and LLM summary
        """
        # Stage 1: Rule-based weakness detection
        weaknesses = _build_weaknesses(result)

        # Stage 2: LLM-based analysis (graceful fallback)
        llm_response_raw: Optional[str] = None
        llm_summary = ""
        recommendations: list[str] = []

        try:
            prompt = self._build_prompt(result, weaknesses, history)
            llm_data = self.ollama.analyze(
                prompt=prompt,
                system=self._get_system_prompt(),
            )
            llm_summary = llm_data.get("summary", "")
            recommendations = llm_data.get("recommendations", [])
            root_causes = llm_data.get("root_causes", [])
            llm_response_raw = json.dumps(llm_data)

            # Merge root causes into weakness probable_causes if not already present
            for weakness in weaknesses:
                for cause in root_causes:
                    if cause not in weakness.probable_causes:
                        weakness.probable_causes.append(cause)

        except OllamaError as e:
            logger.warning("Ollama unavailable, using rule-based analysis only: %s", e)
            llm_summary = (
                f"Rule-based analysis: {len(weaknesses)} metric(s) failing. "
                "LLM analysis unavailable."
            )
            # Generate simple recommendations from weaknesses
            recommendations = [
                f"Improve {w.metric}: currently {w.current_value:.2f}, target {w.target_value}"
                for w in weaknesses[:3]
            ]

        return AnalysisReport(
            strategy_version=result.strategy_version,
            analysis_model=self.ollama.analysis_model,
            summary=llm_summary,
            weaknesses=weaknesses,
            strengths=_identify_strengths(result),
            recommendations=recommendations,
            raw_llm_response=llm_response_raw,
        )


def _identify_strengths(result: BacktestResult) -> list[str]:
    """Identify what the strategy is doing well."""
    strengths = []
    if result.meets_pf_target:
        strengths.append(f"Profit Factor {result.profit_factor:.2f} exceeds 1.5 target")
    if result.meets_dd_target:
        strengths.append(f"Max Drawdown {result.max_drawdown_pct:.1f}% within 15% limit")
    if result.meets_rf_target:
        strengths.append(f"Recovery Factor {result.recovery_factor:.2f} exceeds 3.0 target")
    if result.meets_rr_target:
        strengths.append(f"Win/Loss Ratio {result.avg_win_loss_ratio:.2f} exceeds 2.0 target")
    if result.total_trades >= 50:
        strengths.append(f"Good sample size: {result.total_trades} trades")
    if result.win_rate_pct >= 45:
        strengths.append(f"Solid win rate: {result.win_rate_pct:.1f}%")
    return strengths
