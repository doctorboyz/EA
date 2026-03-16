"""Hard constraint validator - NEVER relaxed. Guards against V4-style failures."""

from typing import List, Tuple
from core.strategy_config import StrategyConfig
import re


class ConstraintViolation(Exception):
    """Raised when generated code violates hard constraints."""
    pass


class ConstraintValidator:
    """Validates strategy configs and generated MQL5 code against immutable rules."""

    # Hard-coded banned patterns (anti-V4)
    BANNED_PATTERNS = [
        r"FixedLossUSD",
        r"fixed_loss",
        r"loss_usd",
    ]

    @classmethod
    def validate_config(cls, config: StrategyConfig) -> Tuple[bool, List[str]]:
        """
        Validate a StrategyConfig against all hard constraints.
        Returns (is_valid, violations_list)
        """
        violations = []

        # Rule 1: Risk percent bounds
        if config.risk_percent > 2.0:
            violations.append(
                f"Risk percent {config.risk_percent}% exceeds max 2.0% (V4 was 10%)"
            )
        if config.risk_percent < 0.5:
            violations.append(
                f"Risk percent {config.risk_percent}% below min 0.5%"
            )

        # Rule 2: R/R ratio
        rr_ratio = config.take_profit_pips / config.stop_loss_pips
        if rr_ratio < 2.0:
            violations.append(
                f"R/R ratio {rr_ratio:.1f}:1 below 2.0:1 minimum"
            )
        if rr_ratio > 5.0:
            violations.append(
                f"R/R ratio {rr_ratio:.1f}:1 exceeds 5.0:1 (diminishing returns)"
            )

        # Rule 3: SL minimum
        if config.stop_loss_pips < 20:
            violations.append(
                f"Stop loss {config.stop_loss_pips} pips below 20 (spread eats it)"
            )

        # Rule 4: RSI thresholds (V4 used too loose 35/65)
        if config.rsi_oversold > 35.0:
            violations.append(
                f"RSI oversold {config.rsi_oversold} > 35 (V4 mistake)"
            )
        if config.rsi_overbought < 65.0:
            violations.append(
                f"RSI overbought {config.rsi_overbought} < 65 (V4 mistake)"
            )
        if config.rsi_oversold >= config.rsi_overbought:
            violations.append(
                f"RSI oversold {config.rsi_oversold} >= overbought {config.rsi_overbought}"
            )

        # Rule 5: EMA not too short
        if config.ema_period < 150:
            violations.append(
                f"EMA period {config.ema_period} < 150 (too noisy on H1)"
            )

        # Rule 6: Breakeven sanity
        if config.breakeven_pips >= config.take_profit_pips:
            violations.append(
                f"Breakeven {config.breakeven_pips} >= TP {config.take_profit_pips}"
            )

        # Rule 7: Breakeven above spread
        spread_multiple = config.breakeven_pips / config.max_spread_pips
        if spread_multiple < 2.0:
            violations.append(
                f"Breakeven {config.breakeven_pips} only {spread_multiple:.1f}x max spread "
                f"{config.max_spread_pips} (slippage risk)"
            )

        # Rule 8: ADX filter coherence
        if config.use_adx_filter and config.adx_min_strength is None:
            violations.append("ADX filter enabled but adx_min_strength not set")

        # Rule 9: H4 filter coherence
        if config.use_h4_filter and config.h4_ema_period is None:
            violations.append("H4 filter enabled but h4_ema_period not set")

        return len(violations) == 0, violations

    @classmethod
    def validate_mql5_code(cls, code: str) -> Tuple[bool, List[str]]:
        """
        Validate generated MQL5 code against hard constraints.
        Returns (is_valid, violations_list)
        """
        violations = []

        # Check for banned patterns
        for pattern in cls.BANNED_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                violations.append(
                    f"Banned pattern found: {pattern}. "
                    f"This is V4 failure cause (fixed USD risk)."
                )

        # Check for percentage-based risk (positive signal)
        if "risk_percent" not in code.lower() and "riskpercent" not in code.lower():
            violations.append(
                "No RiskPercent found in code. Risk must be percentage-based."
            )

        # Check for proper lot size calculation
        lot_calc_patterns = [
            r"lot\s*=.*balance.*risk",          # lot = (balance * risk ...) in one line
            r"lot_size.*=.*balance.*risk",       # lot_size = ...
            r"CalculateLotSize\s*\(",            # helper function (templates use this)
            r"risk_usd\s*=.*balance.*risk",      # risk_usd = balance * risk_percent / 100
        ]
        has_proper_lot_calc = any(
            re.search(p, code, re.IGNORECASE) for p in lot_calc_patterns
        )
        if not has_proper_lot_calc:
            violations.append(
                "No proper percentage-based lot size calculation found. "
                "Expected: lot = (balance * risk_percent / 100) / (sl_pips * 10 * tick_value)"
            )

        return len(violations) == 0, violations

    @classmethod
    def enforce(cls, config: StrategyConfig, code: str) -> None:
        """
        Enforce constraints. Raises ConstraintViolation if anything fails.
        """
        config_valid, config_violations = cls.validate_config(config)
        code_valid, code_violations = cls.validate_mql5_code(code)

        all_violations = config_violations + code_violations

        if all_violations:
            violation_text = "\n  - ".join(all_violations)
            raise ConstraintViolation(
                f"Strategy violates {len(all_violations)} hard constraint(s):\n  - {violation_text}"
            )
