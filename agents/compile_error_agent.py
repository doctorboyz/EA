"""
CompileErrorAgent — Reads MT5 compile errors and uses LLM to auto-fix MQL5 syntax.

Integration points:
- BacktestRunnerAgent._compile_ea() calls fix() on compile timeout
- DaddyAgent._check_mql5_templates() calls validate_template() pre-flight

MT5 compiler error format (written to .log file next to .mq5):
  file.mq5(45,12) : error 29 : 'variableName' - undeclared identifier
  file.mq5(45,12) : warning 7 : some warning message
  ; 2 error(s), 1 warning(s)

Governance rules:
- MAX_FIX_ATTEMPTS hard cap: prevents runaway LLM loops
- ConstraintValidator runs on EVERY LLM fix: V4 guard always enforced
- Only modifies the .mq5 source file — never touches .ex5 or other files
- Logs every attempt with specific error lines for debugging
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.constraint_validator import ConstraintValidator

logger = logging.getLogger(__name__)


MAX_FIX_ATTEMPTS: int = 3


@dataclass
class MQL5CompileError:
    line: int
    col: int
    severity: str   # 'error' | 'warning'
    code: int
    message: str

    def __str__(self) -> str:
        return f"Line {self.line}:{self.col} [{self.severity} {self.code}]: {self.message}"


class CompileErrorAgent:
    """
    Reads MT5 compile errors from .log file and uses LLM to fix them.

    Usage:
        agent = CompileErrorAgent(ollama=client)
        fixed = agent.fix(mq5_path="/path/to/EA.mq5")
        if fixed:
            # retry compile
    """

    def __init__(self, ollama=None) -> None:
        self._ollama = ollama

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fix(
        self,
        mq5_path: str,
        error_output: str = "",
    ) -> bool:
        """
        Attempt to fix compile errors in mq5_path using LLM.

        Reads errors from:
          1. error_output argument (stdout/stderr captured from compile process)
          2. Auto-detected .log file next to the .mq5 file

        Returns True if code was modified and saved (caller must retry compile).
        Returns False if no fix was possible.
        """
        # Try to load error text from the .log file written by MT5
        if not error_output:
            error_output = self._read_mt5_log(mq5_path)

        errors = self._parse_errors(error_output)
        if not errors:
            logger.warning(
                "[CompileErrorAgent] No parseable compile errors found for %s\n"
                "Raw output (first 500 chars): %s",
                Path(mq5_path).name, error_output[:500],
            )
            return False

        logger.info(
            "[CompileErrorAgent] %d error(s) in %s:",
            len(errors), Path(mq5_path).name,
        )
        for e in errors:
            logger.info("  %s", e)

        if self._ollama is None:
            logger.error("[CompileErrorAgent] No Ollama client — cannot auto-fix")
            return False

        code = Path(mq5_path).read_text(encoding="utf-8")
        current_errors = errors

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            logger.info(
                "[CompileErrorAgent] LLM fix attempt %d/%d for %s",
                attempt, MAX_FIX_ATTEMPTS, Path(mq5_path).name,
            )

            fixed_code = self._llm_fix(code, current_errors, attempt)

            if not fixed_code or fixed_code.strip() == code.strip():
                logger.warning(
                    "[CompileErrorAgent] Attempt %d: LLM returned unchanged code — stopping",
                    attempt,
                )
                break

            # Constraint check — V4 guard must always pass
            is_valid, violations = ConstraintValidator.validate_mql5_code(fixed_code)
            if not is_valid:
                logger.warning(
                    "[CompileErrorAgent] Attempt %d: fix introduced constraint violations: %s — retrying",
                    attempt, violations,
                )
                # Pass violations back to LLM on next attempt
                current_errors = errors  # Reset to original errors
                code = fixed_code        # Still use this as base (violations are minor)
                continue

            # Write fixed code
            Path(mq5_path).write_text(fixed_code, encoding="utf-8")
            logger.info(
                "[CompileErrorAgent] Attempt %d: wrote fixed code → %s",
                attempt, mq5_path,
            )
            return True

        logger.error(
            "[CompileErrorAgent] All %d attempts exhausted for %s — manual fix required",
            MAX_FIX_ATTEMPTS, Path(mq5_path).name,
        )
        return False

    def validate_template_output(self, rendered_code: str) -> tuple[bool, list[str]]:
        """
        Quick static checks on rendered template code before compile.
        Returns (ok, list_of_issues).
        Used by DaddyAgent pre-flight.
        """
        issues: list[str] = []

        # Check ConstraintValidator first
        is_valid, violations = ConstraintValidator.validate_mql5_code(rendered_code)
        if not is_valid:
            issues.extend(violations)

        # Common patterns that fail to compile
        _banned_patterns: list[tuple[str, str]] = [
            ("OrderSelect(",          "Old MT4 API — use PositionSelectByTicket"),
            ("OrdersTotal()",         "Old MT4 API — use PositionsTotal()"),
            ("OrderType()",           "Old MT4 API — use PositionGetInteger(POSITION_TYPE)"),
            ("OrderLots()",           "Old MT4 API — use PositionGetDouble(POSITION_VOLUME)"),
            ("AccountBalance()",      "Old MT4 API — use AccountInfoDouble(ACCOUNT_BALANCE)"),
            ("MarketInfo(",           "Old MT4 API — use SymbolInfoDouble"),
            ("#property strict",      None),   # Must be present
        ]

        for pattern, message in _banned_patterns:
            if message is None:
                # Must-have check
                if pattern not in rendered_code:
                    issues.append(f"Missing required: {pattern}")
            else:
                if pattern in rendered_code:
                    issues.append(f"Banned pattern '{pattern}': {message}")

        # Check balanced braces
        open_braces  = rendered_code.count("{")
        close_braces = rendered_code.count("}")
        if open_braces != close_braces:
            issues.append(
                f"Unbalanced braces: {{ open={open_braces} close={close_braces} }}"
            )

        return len(issues) == 0, issues

    # ------------------------------------------------------------------
    # Log reading
    # ------------------------------------------------------------------

    def _read_mt5_log(self, mq5_path: str) -> str:
        """
        Read the MT5 compile log file (same path as .mq5 but .log extension).
        MT5 writes compiler output here when running /compile.
        """
        log_path = str(mq5_path).replace(".mq5", ".log")
        try:
            content = Path(log_path).read_text(encoding="utf-8", errors="replace")
            if content.strip():
                logger.debug("[CompileErrorAgent] Read log: %s (%d bytes)", log_path, len(content))
            return content
        except (FileNotFoundError, PermissionError):
            return ""

    # ------------------------------------------------------------------
    # Error parsing
    # ------------------------------------------------------------------

    def _parse_errors(self, output: str) -> list[MQL5CompileError]:
        """
        Parse MT5 compiler output lines.

        MT5 format:
          AureusV0_3.mq5(45,12) : error 29 : 'foo' - undeclared identifier
          AureusV0_3.mq5(45,12) : warning 7 : possible loss of data

        Returns only errors (severity == 'error'); warnings don't block compile.
        """
        errors: list[MQL5CompileError] = []
        pattern = re.compile(
            r"\((\d+),(\d+)\)\s*:\s*(error|warning)\s+(\d+)\s*:\s*(.+)",
            re.IGNORECASE,
        )
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                errors.append(MQL5CompileError(
                    line=int(m.group(1)),
                    col=int(m.group(2)),
                    severity=m.group(3).lower(),
                    code=int(m.group(4)),
                    message=m.group(5).strip(),
                ))

        # Only errors block compile; filter out warnings
        compile_errors = [e for e in errors if e.severity == "error"]
        if not compile_errors and errors:
            logger.debug("[CompileErrorAgent] Only warnings found (%d) — code may compile OK", len(errors))

        return compile_errors

    # ------------------------------------------------------------------
    # LLM fix
    # ------------------------------------------------------------------

    def _llm_fix(
        self,
        code: str,
        errors: list[MQL5CompileError],
        attempt: int,
    ) -> Optional[str]:
        """
        Ask LLM to fix specific compile errors in the MQL5 code.
        Returns corrected code string, or None on failure.
        """
        # Build error summary
        error_summary = "\n".join(
            f"  {e}" for e in errors[:12]
        )

        # Show code context around each error line (±3 lines)
        code_lines = code.splitlines()
        context_blocks: list[str] = []
        shown: set[tuple[int, int]] = set()

        for e in errors[:6]:
            start = max(0, e.line - 4)
            end   = min(len(code_lines), e.line + 3)
            key   = (start, end)
            if key in shown:
                continue
            shown.add(key)
            snippet = "\n".join(
                f"{i + 1:4d}: {ln}"
                for i, ln in enumerate(code_lines[start:end], start=start)
            )
            context_blocks.append(f"// ── Context around line {e.line} ──\n{snippet}")

        context_section = "\n\n".join(context_blocks)

        system = (
            "You are an expert MQL5 developer for MetaTrader 5 (not MT4). "
            "Fix the compile errors listed below in the provided MQL5 code. "
            "Return ONLY the complete corrected MQL5 source code — no explanation, "
            "no markdown fences, no ```mql5 wrapper. "
            "CRITICAL rules you MUST follow:\n"
            "1. NEVER use FixedLossUSD or any fixed-dollar risk — only percentage-based lot sizing.\n"
            "2. Use MQL5 API only: MqlTradeRequest/OrderSend or CTrade — NOT OrderSend() MT4 style.\n"
            "3. Use PositionSelectByTicket(ticket) — NOT PositionSelect(symbol).\n"
            "4. All indicators use handles: iATR(), iRSI(), iMA() — NOT the old single-call API.\n"
            "5. Preserve ALL original trading logic — only fix syntax/compile errors.\n"
            "6. Keep #property strict at the top."
        )

        prompt = (
            f"Fix these MQL5 compile errors (attempt {attempt}/{MAX_FIX_ATTEMPTS}):\n\n"
            f"COMPILE ERRORS:\n{error_summary}\n\n"
            f"CODE CONTEXT NEAR ERRORS:\n{context_section}\n\n"
            f"FULL SOURCE CODE:\n{code}"
        )

        try:
            result = self._ollama.generate_code(prompt=prompt, system=system)
            if not result:
                return None

            # Strip any markdown fences the LLM might add
            result = re.sub(r"^```(?:mql5|cpp|c\+\+|mq5)?\s*\n", "", result, flags=re.IGNORECASE | re.MULTILINE)
            result = re.sub(r"\n```\s*$", "", result, flags=re.MULTILINE)

            return result.strip() or None

        except Exception as exc:
            logger.warning("[CompileErrorAgent] LLM error on attempt %d: %s", attempt, exc)
            return None
