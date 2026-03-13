"""Tests for CodeGeneratorAgent — verifies generated MQL5 code is valid."""

import os
import pytest
import tempfile
from unittest.mock import MagicMock, patch

from core.strategy_config import StrategyConfig, StrategyVersion
from core.constraint_validator import ConstraintValidator, ConstraintViolation
from agents.code_generator import CodeGeneratorAgent, GeneratedCode


def _v3_config() -> StrategyConfig:
    """Standard V3-equivalent config for testing."""
    return StrategyConfig(
        version=StrategyVersion(major=0, minor=3, iteration=0),
        name="AureusTest",
        symbol="EURUSD",
        timeframe="H1",
        magic_number=20260300,
        risk_percent=1.0,
        ema_period=200,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        atr_period=14,
        atr_max_multiplier=1.5,
        stop_loss_pips=30,
        take_profit_pips=90,
        breakeven_pips=15,
        trailing_stop_pips=20,
        lookback_period=120,
        max_spread_pips=2.0,
    )


@pytest.fixture
def agent(tmp_path):
    """CodeGeneratorAgent writing to a temp directory."""
    mock_ollama = MagicMock()
    mock_ollama.code_gen_model = "qwen2.5-coder:7b"
    return CodeGeneratorAgent(
        ollama=mock_ollama,
        generated_dir=str(tmp_path),
        use_llm=False,
    )


class TestTemplateRendering:
    """Verify Jinja2 template renders correct parameter values."""

    def test_generate_returns_generated_code(self, agent):
        result = agent.generate(_v3_config())
        assert isinstance(result, GeneratedCode)
        assert result.validation_passed

    def test_risk_percent_in_code(self, agent):
        """Generated code must contain RiskPercent=1.0."""
        result = agent.generate(_v3_config())
        assert "RiskPercent" in result.code
        assert "1.0" in result.code

    def test_stop_loss_pips_in_code(self, agent):
        result = agent.generate(_v3_config())
        assert "StopLossPips" in result.code
        assert "30" in result.code

    def test_take_profit_pips_in_code(self, agent):
        result = agent.generate(_v3_config())
        assert "TakeProfitPips" in result.code
        assert "90" in result.code

    def test_rsi_thresholds_in_code(self, agent):
        result = agent.generate(_v3_config())
        assert "30.0" in result.code   # rsi_oversold
        assert "70.0" in result.code   # rsi_overbought

    def test_ema_period_in_code(self, agent):
        result = agent.generate(_v3_config())
        assert "200" in result.code    # EMA period

    def test_magic_number_in_code(self, agent):
        result = agent.generate(_v3_config())
        assert "20260300" in result.code

    def test_symbol_in_header(self, agent):
        result = agent.generate(_v3_config())
        assert "EURUSD" in result.code

    def test_version_in_header(self, agent):
        result = agent.generate(_v3_config())
        assert "0.3.0" in result.code


class TestConstraintValidation:
    """Generated code must pass ConstraintValidator."""

    def test_v3_config_passes_validator(self, agent):
        """V3-equivalent code must pass all constraint checks."""
        result = agent.generate(_v3_config())
        is_valid, violations = ConstraintValidator.validate_mql5_code(result.code)
        assert is_valid, f"Generated code has violations: {violations}"

    def test_no_fixed_loss_usd_in_output(self, agent):
        """FixedLossUSD must NEVER appear in generated code."""
        result = agent.generate(_v3_config())
        assert "FixedLossUSD" not in result.code
        assert "fixed_loss" not in result.code.lower()

    def test_percentage_risk_calculation_present(self, agent):
        """Code must contain percentage-based lot size calculation."""
        result = agent.generate(_v3_config())
        # CalculateLotSize must reference RiskPercent/balance
        assert "RiskPercent" in result.code
        assert "CalculateLotSize" in result.code

    def test_code_hash_is_sha256(self, agent):
        result = agent.generate(_v3_config())
        assert len(result.code_hash) == 64
        assert all(c in '0123456789abcdef' for c in result.code_hash)


class TestMQL5Structure:
    """Verify required MQL5 functions are present."""

    def test_on_init_present(self, agent):
        result = agent.generate(_v3_config())
        assert "OnInit()" in result.code

    def test_on_deinit_present(self, agent):
        result = agent.generate(_v3_config())
        assert "OnDeinit(" in result.code

    def test_on_tick_present(self, agent):
        result = agent.generate(_v3_config())
        assert "OnTick()" in result.code

    def test_calculate_lot_size_present(self, agent):
        result = agent.generate(_v3_config())
        assert "CalculateLotSize" in result.code

    def test_execute_trade_present(self, agent):
        result = agent.generate(_v3_config())
        assert "ExecuteTrade" in result.code

    def test_manage_positions_present(self, agent):
        result = agent.generate(_v3_config())
        assert "ManagePositions" in result.code

    def test_get_filling_mode_present(self, agent):
        result = agent.generate(_v3_config())
        assert "GetFillingMode" in result.code

    def test_indicator_handles_released(self, agent):
        """OnDeinit must release all indicator handles."""
        result = agent.generate(_v3_config())
        assert "IndicatorRelease(handleRSI)" in result.code
        assert "IndicatorRelease(handleATR)" in result.code
        assert "IndicatorRelease(handleEMA)" in result.code

    def test_file_written_to_disk(self, agent, tmp_path):
        result = agent.generate(_v3_config())
        assert os.path.exists(result.file_path)
        content = open(result.file_path).read()
        assert "RiskPercent" in content


class TestParameterVariation:
    """Verify different configs produce different code."""

    def test_different_sl_tp_renders_correctly(self, agent):
        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=3, iteration=1),
            name="AureusTest",
            stop_loss_pips=25,
            take_profit_pips=75,
            breakeven_pips=12,
        )
        result = agent.generate(config)
        assert "25" in result.code    # SL
        assert "75" in result.code    # TP

    def test_adx_filter_disabled_by_default(self, agent):
        """V3 default has ADX filter disabled."""
        result = agent.generate(_v3_config())
        # ADX handle should not be initialized in base V3
        assert "handleADX" not in result.code

    def test_adx_filter_enabled_when_configured(self, agent):
        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=3, iteration=2),
            name="AureusTestADX",
            stop_loss_pips=30,
            take_profit_pips=90,
            breakeven_pips=15,
            use_adx_filter=True,
            adx_min_strength=25,
        )
        result = agent.generate(config)
        assert "handleADX" in result.code
        assert "ADX_MinStrength" in result.code

    def test_h4_filter_enabled_when_configured(self, agent):
        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=3, iteration=3),
            name="AureusTestH4",
            stop_loss_pips=30,
            take_profit_pips=90,
            breakeven_pips=15,
            use_h4_filter=True,
            h4_ema_period=50,
        )
        result = agent.generate(config)
        assert "handleEMA_H4" in result.code
        assert "H4_EMA_Period" in result.code


class TestV3MilestoneTest:
    """Phase 3 milestone: regenerate V3-equivalent code that passes all checks."""

    def test_regenerate_v3_equivalent(self, agent):
        """
        MILESTONE TEST: Generate V3-equivalent code from config.
        Must pass ConstraintValidator and contain correct V3 parameters.
        """
        result = agent.generate_v3_equivalent()

        # Passes constraint validator
        assert result.validation_passed

        # Key V3 parameters present
        assert "RiskPercent" in result.code
        assert "1.0" in result.code        # 1% risk
        assert "30" in result.code         # 30 pip SL
        assert "90" in result.code         # 90 pip TP
        assert "200" in result.code        # EMA 200
        assert "30.0" in result.code       # RSI oversold
        assert "70.0" in result.code       # RSI overbought

        # No banned patterns
        assert "FixedLossUSD" not in result.code

        # All required functions
        assert "CalculateLotSize" in result.code
        assert "OnInit()" in result.code
        assert "OnTick()" in result.code

        print(f"\n✓ PHASE 3 MILESTONE: V3-equivalent code generated")
        print(f"  File: {result.file_path}")
        print(f"  Hash: {result.code_hash[:16]}...")
        print(f"  Lines: {result.code.count(chr(10))}")


if __name__ == "__main__":
    # Smoke test
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_ollama = MagicMock()
        mock_ollama.code_gen_model = "qwen2.5-coder:7b"
        gen = CodeGeneratorAgent(
            ollama=mock_ollama,
            generated_dir=tmpdir,
            use_llm=False,
        )
        result = gen.generate_v3_equivalent()
        print(f"✓ Generated: {result.file_path}")
        print(f"  Validation: {'PASS' if result.validation_passed else 'FAIL'}")
        print(f"  Lines: {result.code.count(chr(10))}")
        is_valid, violations = ConstraintValidator.validate_mql5_code(result.code)
        print(f"  ConstraintValidator: {'PASS' if is_valid else 'FAIL'}")
        if violations:
            for v in violations:
                print(f"    ✗ {v}")
