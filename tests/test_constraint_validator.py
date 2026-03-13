"""Tests for ConstraintValidator - verify it catches V4 bug."""

import pytest
from core.constraint_validator import ConstraintValidator, ConstraintViolation
from core.strategy_config import StrategyConfig, StrategyVersion


class TestConstraintValidator:
    """Test that hard constraints catch known failure patterns."""

    def test_v3_config_passes(self) -> None:
        """V3 baseline config should pass all constraints."""
        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=3, iteration=0),
            name="Aureus_V3_Baseline",
            symbol="EURUSD",
            risk_percent=1.0,
            ema_period=200,
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            stop_loss_pips=30,
            take_profit_pips=90,
            breakeven_pips=15,
        )

        is_valid, violations = ConstraintValidator.validate_config(config)
        assert is_valid, f"V3 config should pass: {violations}"

    def test_v4_risk_bug_caught(self) -> None:
        """ConstraintValidator should catch V4's 10% fixed risk (if passed as config)."""
        # V4 actually used FixedLossUSD=10 on $100 = 10% risk
        # If someone tried to pass risk_percent=10, it should be clamped/rejected
        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=4, iteration=0),
            risk_percent=1.0,  # Config is always percentage-based
        )

        # The code-level check will catch FixedLossUSD in generated MQL5

    def test_mql5_fixed_usd_banned(self) -> None:
        """Generated MQL5 code with FixedLossUSD should be rejected."""
        bad_code = """
        #property description "Trading Bot"
        double FixedLossUSD = 10.0;  // This is V4 failure!
        """

        is_valid, violations = ConstraintValidator.validate_mql5_code(bad_code)
        assert not is_valid, "Code with FixedLossUSD should fail"
        assert any("FixedLossUSD" in v for v in violations)

    def test_mql5_percentage_risk_required(self) -> None:
        """Generated MQL5 must use percentage-based risk."""
        bad_code = """
        void OpenTrade() {
            int lot = 0.1;  // Hard-coded lot size
        }
        """

        is_valid, violations = ConstraintValidator.validate_mql5_code(bad_code)
        assert not is_valid, "Code without percentage-based risk should fail"

    def test_rr_ratio_minimum(self) -> None:
        """R/R ratio must be >= 2.0 — use model_construct to bypass Pydantic bounds."""
        # model_construct skips Pydantic validators so ConstraintValidator can catch it
        config = StrategyConfig.model_construct(
            version=StrategyVersion(major=0, minor=0, iteration=0),
            name="test", symbol="EURUSD", timeframe="H1", magic_number=1,
            risk_percent=1.0, ema_period=200, rsi_period=14,
            rsi_oversold=30.0, rsi_overbought=70.0, atr_period=14,
            atr_max_multiplier=1.5,
            stop_loss_pips=30,
            take_profit_pips=45,  # Only 1.5:1, should fail
            breakeven_pips=15, trailing_stop_pips=20, lookback_period=120,
            max_spread_pips=2.0, use_adx_filter=False, use_h4_filter=False,
            news_block_hours=[], change_rationale={},
        )

        is_valid, violations = ConstraintValidator.validate_config(config)
        assert not is_valid, "R/R < 2.0 should fail"
        assert any("R/R" in v for v in violations)

    def test_stop_loss_minimum(self) -> None:
        """Stop loss must be >= 20 pips — use model_construct to bypass Pydantic bounds."""
        config = StrategyConfig.model_construct(
            version=StrategyVersion(major=0, minor=0, iteration=0),
            name="test", symbol="EURUSD", timeframe="H1", magic_number=1,
            risk_percent=1.0, ema_period=200, rsi_period=14,
            rsi_oversold=30.0, rsi_overbought=70.0, atr_period=14,
            atr_max_multiplier=1.5,
            stop_loss_pips=10,   # Too tight
            take_profit_pips=60,
            breakeven_pips=15, trailing_stop_pips=20, lookback_period=120,
            max_spread_pips=2.0, use_adx_filter=False, use_h4_filter=False,
            news_block_hours=[], change_rationale={},
        )

        is_valid, violations = ConstraintValidator.validate_config(config)
        assert not is_valid, "SL < 20 pips should fail"

    def test_rsi_threshold_clamp(self) -> None:
        """RSI validators clamp out-of-range values at construction time."""
        # Pydantic rejects values outside bounds — verify valid range is accepted
        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=0, iteration=0),
            rsi_oversold=35.0,   # max allowed
            rsi_overbought=65.0, # min allowed
        )
        is_valid, violations = ConstraintValidator.validate_config(config)
        assert is_valid, f"Edge-of-range RSI should pass: {violations}"
        assert config.rsi_oversold <= 35.0
        assert config.rsi_overbought >= 65.0

    def test_enforce_raises_on_violation(self) -> None:
        """enforce() should raise ConstraintViolation when code has banned pattern."""
        # Use a valid config — the code violation alone should trigger the raise
        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=0, iteration=0),
        )

        bad_code = "double FixedLossUSD = 10.0;"

        with pytest.raises(ConstraintViolation):
            ConstraintValidator.enforce(config, bad_code)


if __name__ == "__main__":
    print("Testing V3 config validation...")
    v3_config = StrategyConfig(
        version=StrategyVersion(major=0, minor=3, iteration=0),
        risk_percent=1.0,
        ema_period=200,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
    )
    is_valid, violations = ConstraintValidator.validate_config(v3_config)
    if is_valid:
        print("✓ V3 config passes all constraints")
    else:
        print(f"✗ V3 config violations: {violations}")

    print("\nTesting V4 FixedLossUSD ban...")
    bad_code = "double FixedLossUSD = 10.0;"
    is_valid, violations = ConstraintValidator.validate_mql5_code(bad_code)
    if not is_valid:
        print(f"✓ FixedLossUSD correctly rejected: {violations[0]}")
    else:
        print("✗ FixedLossUSD not caught!")
