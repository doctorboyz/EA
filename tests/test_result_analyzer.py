"""Tests for ResultAnalyzerAgent — verifies rule-based weakness detection."""

import pytest
from unittest.mock import MagicMock, patch
from core.strategy_config import BacktestResult, AnalysisReport
from agents.result_analyzer import ResultAnalyzerAgent, _build_weaknesses, _identify_strengths


def _make_result(**kwargs) -> BacktestResult:
    """Factory for BacktestResult with V3-like defaults."""
    defaults = dict(
        strategy_version="0.3.0",
        symbol="EURUSD",
        timeframe="H1",
        date_from="2026-01-01",
        date_to="2026-03-12",
        initial_capital=1000.0,
        profit_factor=1.24,
        net_profit=7.22,
        gross_profit=60.0,
        gross_loss=48.0,
        expected_payoff=0.10,
        max_drawdown_pct=8.92,
        recovery_factor=0.77,
        total_trades=74,
        winning_trades=32,
        losing_trades=42,
        win_rate_pct=43.0,
        avg_win_usd=1.88,
        avg_loss_usd=1.14,
        avg_win_loss_ratio=0.87,
        max_consecutive_losses=4,
        sharpe_ratio=0.5,
        margin_level_min_pct=1200.0,
    )
    defaults.update(kwargs)
    result = BacktestResult(**defaults)
    result.check_targets()
    return result


class TestWeaknessDetection:
    """Rule-based weakness detection without LLM."""

    def test_v3_weaknesses_identified(self):
        """V3 should have 3 failing metrics (RF, Win/Loss, PF)."""
        result = _make_result()
        weaknesses = _build_weaknesses(result)
        metrics = {w.metric for w in weaknesses}

        assert "recovery_factor" in metrics
        assert "avg_win_loss_ratio" in metrics
        assert "profit_factor" in metrics
        # DD should NOT be a weakness (8.92% < 15%)
        assert "max_drawdown_pct" not in metrics

    def test_v4_all_weaknesses_flagged(self):
        """V4 blown account should flag all 4 metrics."""
        result = _make_result(
            strategy_version="0.4.0",
            profit_factor=0.64,
            max_drawdown_pct=101.71,
            recovery_factor=-0.93,
            avg_win_loss_ratio=0.87,
            net_profit=-100.05,
        )
        weaknesses = _build_weaknesses(result)
        metrics = {w.metric for w in weaknesses}

        assert "profit_factor" in metrics
        assert "max_drawdown_pct" in metrics
        assert "recovery_factor" in metrics
        assert "avg_win_loss_ratio" in metrics

    def test_dd_weakness_severity_critical(self):
        """DD > 50% should be critical severity."""
        result = _make_result(max_drawdown_pct=101.71, recovery_factor=-0.93)
        weaknesses = _build_weaknesses(result)
        dd_weakness = next(w for w in weaknesses if w.metric == "max_drawdown_pct")
        assert dd_weakness.severity == "critical"

    def test_perfect_strategy_no_weaknesses(self):
        """Meeting all targets → no weaknesses."""
        result = _make_result(
            profit_factor=2.0,
            max_drawdown_pct=10.0,
            recovery_factor=4.0,
            avg_win_loss_ratio=2.5,
        )
        weaknesses = _build_weaknesses(result)
        assert len(weaknesses) == 0

    def test_strengths_identified_for_v3(self):
        """V3 passing DD should appear as a strength."""
        result = _make_result()
        result.check_targets()
        strengths = _identify_strengths(result)
        assert any("Drawdown" in s for s in strengths)


class TestResultAnalyzerAgent:
    """Integration tests for the agent (mocking Ollama)."""

    def _mock_ollama(self) -> MagicMock:
        mock = MagicMock()
        mock.analysis_model = "llama3.2:3b"
        mock.analyze.return_value = {
            "summary": "Strategy has low profit factor due to poor R/R.",
            "root_causes": ["Take profit too small relative to stop loss"],
            "recommendations": [
                "Increase take_profit_pips from 90 to 100",
                "Tighten rsi_oversold from 30 to 28",
            ],
        }
        return mock

    def test_analyze_returns_report(self):
        """analyze() should return an AnalysisReport object."""
        with patch(
            "agents.result_analyzer._load_system_prompt",
            return_value="system prompt"
        ):
            agent = ResultAnalyzerAgent(ollama=self._mock_ollama())
            result = _make_result()
            result.check_targets()
            report = agent.analyze(result)

        assert isinstance(report, AnalysisReport)
        assert report.strategy_version == "0.3.0"
        assert len(report.weaknesses) > 0
        assert len(report.recommendations) > 0

    def test_analyze_uses_rule_based_when_ollama_fails(self):
        """Should fall back to rule-based analysis if Ollama is unavailable."""
        from core.ollama_client import OllamaError

        with patch(
            "agents.result_analyzer._load_system_prompt",
            return_value="system prompt"
        ):
            mock = MagicMock()
            mock.analysis_model = "llama3.2:3b"
            mock.analyze.side_effect = OllamaError("Connection refused")

            agent = ResultAnalyzerAgent(ollama=mock)
            result = _make_result()
            result.check_targets()
            report = agent.analyze(result)

        assert isinstance(report, AnalysisReport)
        assert len(report.weaknesses) > 0  # rule-based still fires
        assert "unavailable" in report.summary.lower()

    def test_v4_analysis_identifies_all_failures(self):
        """V4 blown account analysis should identify all 4 critical metrics."""
        with patch(
            "agents.result_analyzer._load_system_prompt",
            return_value="system prompt"
        ):
            agent = ResultAnalyzerAgent(ollama=self._mock_ollama())
            result = _make_result(
                strategy_version="0.4.0",
                profit_factor=0.64,
                max_drawdown_pct=101.71,
                recovery_factor=-0.93,
                avg_win_loss_ratio=0.87,
            )
            result.check_targets()
            report = agent.analyze(result)

        assert len(report.weaknesses) == 4
        assert not result.meets_all_targets


class TestStrategyImproverAgent:
    """Tests for rule-based improvements in StrategyImproverAgent."""

    def _mock_ollama(self) -> MagicMock:
        mock = MagicMock()
        mock.analysis_model = "llama3.2:3b"
        mock.analyze.return_value = {"param_changes": {}}
        return mock

    def _v3_config(self) -> "StrategyConfig":
        from core.strategy_config import StrategyConfig, StrategyVersion
        return StrategyConfig(
            version=StrategyVersion(major=0, minor=3, iteration=0),
            name="Aureus_V3",
            risk_percent=1.0,
            stop_loss_pips=30,
            take_profit_pips=90,
            breakeven_pips=15,
        )

    def _v3_analysis_report(self) -> AnalysisReport:
        from core.strategy_config import Weakness
        return AnalysisReport(
            strategy_version="0.3.0",
            analysis_model="llama3.2:3b",
            summary="PF and Win/Loss below target",
            weaknesses=[
                Weakness(
                    metric="profit_factor",
                    current_value=1.24,
                    target_value=1.5,
                    gap=17.3,
                    severity="medium",
                    description="PF 1.24 below 1.5 target",
                ),
                Weakness(
                    metric="avg_win_loss_ratio",
                    current_value=0.87,
                    target_value=2.0,
                    gap=56.5,
                    severity="critical",
                    description="Win/loss 0.87 below 2.0 target",
                ),
            ],
            recommendations=[],
        )

    def test_improve_returns_new_config(self):
        """improve() should return a new StrategyConfig."""
        from agents.strategy_improver import StrategyImproverAgent

        with patch(
            "agents.strategy_improver._load_improve_prompt",
            return_value="system prompt"
        ):
            agent = StrategyImproverAgent(ollama=self._mock_ollama())
            new_config = agent.improve(
                self._v3_analysis_report(),
                self._v3_config(),
                use_llm=False,
            )

        from core.strategy_config import StrategyConfig
        assert isinstance(new_config, StrategyConfig)
        assert new_config.version.iteration > 0 or new_config.version.minor > 3

    def test_improve_increases_tp_for_low_win_loss(self):
        """Low Win/Loss ratio → rule should increase take_profit_pips."""
        from agents.strategy_improver import StrategyImproverAgent

        with patch(
            "agents.strategy_improver._load_improve_prompt",
            return_value="system prompt"
        ):
            agent = StrategyImproverAgent(ollama=self._mock_ollama())
            config = self._v3_config()
            original_tp = config.take_profit_pips
            new_config = agent.improve(
                self._v3_analysis_report(),
                config,
                use_llm=False,
            )

        assert new_config.take_profit_pips >= original_tp

    def test_improve_passes_constraint_validator(self):
        """Any improved config must still pass ConstraintValidator."""
        from agents.strategy_improver import StrategyImproverAgent
        from core.constraint_validator import ConstraintValidator

        with patch(
            "agents.strategy_improver._load_improve_prompt",
            return_value="system prompt"
        ):
            agent = StrategyImproverAgent(ollama=self._mock_ollama())
            new_config = agent.improve(
                self._v3_analysis_report(),
                self._v3_config(),
                use_llm=False,
            )

        is_valid, violations = ConstraintValidator.validate_config(new_config)
        assert is_valid, f"Improved config violated constraints: {violations}"

    def test_version_bumped_after_improve(self):
        """Version should increment after improvement."""
        from agents.strategy_improver import StrategyImproverAgent

        with patch(
            "agents.strategy_improver._load_improve_prompt",
            return_value="system prompt"
        ):
            agent = StrategyImproverAgent(ollama=self._mock_ollama())
            config = self._v3_config()
            new_config = agent.improve(
                self._v3_analysis_report(),
                config,
                use_llm=False,
            )

        assert str(new_config.version) != str(config.version)
        assert new_config.parent_version == str(config.version)


if __name__ == "__main__":
    # Quick smoke test
    result = _make_result()
    result.check_targets()
    weaknesses = _build_weaknesses(result)
    print(f"V3 weaknesses ({len(weaknesses)}):")
    for w in weaknesses:
        print(f"  [{w.severity.upper()}] {w.metric}: {w.current_value:.2f} → target {w.target_value}")
    strengths = _identify_strengths(result)
    print(f"\nV3 strengths ({len(strengths)}):")
    for s in strengths:
        print(f"  ✓ {s}")
