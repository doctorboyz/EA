"""
CodeGeneratorAgent (Agent 1) — Generates MQL5 Expert Advisor code from StrategyConfig.

Steps:
  1. Render Jinja2 template with StrategyConfig parameters
  2. Optionally ask qwen2.5-coder:7b to add/improve a specific section
  3. Run ConstraintValidator — hard reject if fails
  4. Write .mq5 file to strategies/generated/
  5. Return path to generated file + code string
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from core.strategy_config import StrategyConfig
from core.constraint_validator import ConstraintValidator, ConstraintViolation
from core.ollama_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template directory
# ---------------------------------------------------------------------------

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', 'templates', 'mql5')
GENERATED_DIR = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'generated')
PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'templates', 'prompts', 'code_gen_system.txt'
)


@dataclass
class GeneratedCode:
    """Result of a code generation run."""
    config_version: str
    code: str
    file_path: str
    code_hash: str
    used_llm: bool
    validation_passed: bool
    violations: list[str]


def _load_code_gen_prompt() -> str:
    with open(PROMPT_PATH) as f:
        return f.read().strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class CodeGeneratorAgent:
    """
    Agent 1: Generates valid MQL5 EA code from a StrategyConfig.

    Template-first approach:
    - Core structure always comes from Jinja2 (safe, predictable)
    - LLM only used for optional comment/description enrichment
    - ConstraintValidator is the final gate — nothing passes without it

    Usage:
        agent = CodeGeneratorAgent()
        result = agent.generate(config)
        if result.validation_passed:
            print(result.file_path)
    """

    def __init__(
        self,
        ollama: Optional[OllamaClient] = None,
        generated_dir: Optional[str] = None,
        use_llm: bool = False,   # Default off; turn on for enrichment pass
    ) -> None:
        self.ollama = ollama or OllamaClient()
        self.generated_dir = Path(generated_dir or GENERATED_DIR)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.use_llm = use_llm
        self._system_prompt: Optional[str] = None

        # Jinja2 env with strict undefined (missing variables = error)
        self._jinja_env = Environment(
            loader=FileSystemLoader(os.path.abspath(TEMPLATE_DIR)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _load_code_gen_prompt()
        return self._system_prompt

    # ------------------------------------------------------------------
    # Core: Jinja2 rendering
    # ------------------------------------------------------------------

    def _render_template(self, config: StrategyConfig) -> str:
        """Render base_ea.mq5.jinja2 with config parameters."""
        template = self._jinja_env.get_template("base_ea.mq5.jinja2")
        version_str = str(config.version)
        return template.render(
            name=config.name,
            version=version_str,
            symbol=config.symbol,
            timeframe=config.timeframe,
            magic_number=config.magic_number,
            risk_percent=config.risk_percent,
            max_spread_pips=config.max_spread_pips,
            stop_loss_pips=config.stop_loss_pips,
            take_profit_pips=config.take_profit_pips,
            breakeven_pips=config.breakeven_pips,
            trailing_stop_pips=config.trailing_stop_pips,
            rsi_period=config.rsi_period,
            rsi_oversold=config.rsi_oversold,
            rsi_overbought=config.rsi_overbought,
            atr_period=config.atr_period,
            atr_max_multiplier=config.atr_max_multiplier,
            ema_period=config.ema_period,
            lookback_period=config.lookback_period,
            use_adx_filter=config.use_adx_filter,
            adx_min_strength=config.adx_min_strength,
            use_h4_filter=config.use_h4_filter,
            h4_ema_period=config.h4_ema_period,
        )

    # ------------------------------------------------------------------
    # Optional: LLM comment enrichment
    # ------------------------------------------------------------------

    def _enrich_with_llm(self, code: str, config: StrategyConfig) -> str:
        """
        Ask qwen2.5-coder:7b to add a descriptive header comment block.
        Only affects the comment section — never touches logic code.
        Falls back silently if Ollama unavailable.
        """
        prompt = self._build_enrichment_prompt(code, config)
        try:
            enriched = self.ollama.generate_code(
                prompt=prompt,
                system=self._get_system_prompt(),
            )
            # Extract only the comment block (between /* and */)
            match = re.search(r'/\*.*?\*/', enriched, re.DOTALL)
            if match:
                comment_block = match.group(0)
                # Insert after the first line (property copyright line)
                lines = code.split('\n', 3)
                return '\n'.join(lines[:2]) + '\n' + comment_block + '\n' + '\n'.join(lines[2:])
        except OllamaError as e:
            logger.debug("LLM enrichment skipped: %s", e)
        return code

    def _build_enrichment_prompt(self, code: str, config: StrategyConfig) -> str:
        return (
            f"Write a MQL5 comment block (/* ... */) describing this Expert Advisor:\n"
            f"- Name: {config.name}\n"
            f"- Strategy: EMA{config.ema_period} trend filter + RSI{config.rsi_period} momentum\n"
            f"- Entry: RSI oversold ({config.rsi_oversold}) for buys, overbought "
            f"({config.rsi_overbought}) for sells\n"
            f"- Risk: {config.risk_percent}% per trade (percentage-based, never fixed USD)\n"
            f"- SL: {config.stop_loss_pips} pips  TP: {config.take_profit_pips} pips\n"
            f"- Symbol: {config.symbol}  Timeframe: {config.timeframe}\n\n"
            f"Return ONLY the comment block, nothing else. Keep it under 15 lines."
        )

    # ------------------------------------------------------------------
    # Output: write .mq5 file
    # ------------------------------------------------------------------

    def _write_file(self, code: str, config: StrategyConfig) -> str:
        """Write code to strategies/generated/ and return file path."""
        filename = f"{config.name}_v{config.version}.mq5".replace('.', '_', 2)
        file_path = self.generated_dir / filename
        file_path.write_text(code, encoding='utf-8')
        logger.info("Wrote generated EA: %s", file_path)
        return str(file_path)

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def generate(self, config: StrategyConfig) -> GeneratedCode:
        """
        Generate MQL5 code from StrategyConfig.

        Returns GeneratedCode with validation result.
        Raises ConstraintViolation if validation fails (hard reject).
        """
        # Step 1: Render template
        code = self._render_template(config)

        # Step 2: Optional LLM enrichment (comments only)
        used_llm = False
        if self.use_llm:
            code = self._enrich_with_llm(code, config)
            used_llm = True

        # Step 3: Validate — hard gate
        is_valid, violations = ConstraintValidator.validate_mql5_code(code)

        # Step 4: Write file regardless (for inspection), but mark validation status
        file_path = self._write_file(code, config)
        code_hash = _sha256(code)

        result = GeneratedCode(
            config_version=str(config.version),
            code=code,
            file_path=file_path,
            code_hash=code_hash,
            used_llm=used_llm,
            validation_passed=is_valid,
            violations=violations,
        )

        if not is_valid:
            logger.error(
                "Generated code for v%s failed validation: %s",
                config.version,
                violations,
            )
            raise ConstraintViolation(
                f"Generated code violates {len(violations)} constraint(s): "
                + "; ".join(violations)
            )

        logger.info(
            "Generated valid EA v%s → %s (hash: %s...)",
            config.version,
            file_path,
            code_hash[:8],
        )
        return result

    # ------------------------------------------------------------------
    # Convenience: regenerate V3 baseline from config
    # ------------------------------------------------------------------

    def generate_v3_equivalent(self) -> GeneratedCode:
        """
        Generate a V3-equivalent EA from the default V3 config.
        Used as Phase 3 milestone test.
        """
        from core.strategy_config import StrategyVersion

        config = StrategyConfig(
            version=StrategyVersion(major=0, minor=3, iteration=0),
            name="AureusV3_Generated",
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
        return self.generate(config)
