"""Agent 3: Parses MT5 HTML backtest reports (UTF-16 LE encoded). Pure parsing, no LLM."""

import re
from pathlib import Path
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from core.strategy_config import BacktestResult


class ReportParserError(Exception):
    """Raised when report parsing fails."""
    pass


class ReportParser:
    """Parse MT5 Strategy Tester HTML reports."""

    # MT5 HTML reports are UTF-16 LE encoded
    ENCODING = 'utf-16'

    @classmethod
    def parse(cls, report_path: str) -> BacktestResult:
        """
        Parse MT5 HTML report and extract metrics.

        Args:
            report_path: Path to HTML report file

        Returns:
            BacktestResult with all extracted metrics
        """
        try:
            with open(report_path, 'r', encoding=cls.ENCODING) as f:
                html_content = f.read()
        except Exception as e:
            raise ReportParserError(f"Failed to read report {report_path}: {e}")

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
        except Exception as e:
            raise ReportParserError(f"Failed to parse HTML: {e}")

        return cls._extract_metrics(soup, report_path)

    @classmethod
    def _extract_metrics(cls, soup: BeautifulSoup, report_path: str) -> BacktestResult:
        """Extract all metrics from parsed HTML."""

        # Find all tables
        tables = soup.find_all('table')
        if not tables:
            raise ReportParserError("No tables found in HTML report")

        # Extract from summary section
        strategy_name = cls._extract_text(soup, r"Expert\s*Advisor", 1)
        symbol = cls._extract_text(soup, r"Symbol", 1)
        timeframe = cls._extract_text(soup, r"Period", 1)
        test_period = cls._extract_text(soup, r"Bars in test", 1)
        test_ticks = cls._extract_text(soup, r"Ticks modeled", 1)
        initial_capital = cls._extract_number(soup, r"Initial deposit", 1)

        # Extract test dates
        date_from = cls._extract_text(soup, r"From", 1)
        date_to = cls._extract_text(soup, r"To", 1)

        # Parse edge metrics
        profit_factor = cls._extract_number(soup, r"Profit Factor", 1)
        net_profit = cls._extract_number(soup, r"Net Profit", 1)
        gross_profit = cls._extract_number(soup, r"Gross Profit", 1)
        gross_loss = cls._extract_number(soup, r"Gross Loss", 1)
        expected_payoff = cls._extract_number(soup, r"Expected Payoff", 1)

        # Parse survival metrics
        max_dd_pct = cls._extract_number(soup, r"Equity Drawdown Maximal", 1)
        recovery_factor = cls._extract_number(soup, r"Recovery Factor", 1)

        # Parse trade statistics
        total_trades = int(cls._extract_number(soup, r"Total Deals") or 0)
        winning_trades = int(cls._extract_number(soup, r"Profit Trades") or 0)
        losing_trades = total_trades - winning_trades if total_trades > 0 else 0
        win_rate = cls._extract_number(soup, r"Win Rate") or 0.0
        avg_win = cls._extract_number(soup, r"Average profit") or 0.0
        avg_loss = cls._extract_number(soup, r"Average loss") or 0.0
        max_consec_losses = int(cls._extract_number(soup, r"consecutive loss") or 0)

        # Parse risk metrics
        sharpe = cls._extract_number(soup, r"Sharpe Ratio") or -5.0
        margin_level_min = cls._extract_number(soup, r"Margin Level") or 0.0

        # Calculate derived metrics (safe division)
        avg_win_loss_ratio = abs(avg_win / avg_loss) if (avg_loss and avg_loss != 0) else 0.0

        # Create result
        result = BacktestResult(
            strategy_version="",
            symbol=symbol or "EURUSD",
            timeframe=timeframe or "H1",
            date_from=date_from or "2025-01-01",
            date_to=date_to or "2026-03-12",
            initial_capital=initial_capital or 1000,
            report_path=report_path,
            test_bars=cls._parse_number(test_period) or 0,
            test_ticks=cls._parse_number(test_ticks) or 0,
            profit_factor=profit_factor or 0,
            net_profit=net_profit or 0,
            gross_profit=gross_profit or 0,
            gross_loss=gross_loss or 0,
            expected_payoff=expected_payoff or 0,
            max_drawdown_pct=max_dd_pct or 0,
            recovery_factor=recovery_factor or 0,
            total_trades=int(total_trades or 0),
            winning_trades=int(winning_trades or 0),
            losing_trades=int(losing_trades or 0),
            win_rate_pct=win_rate or 0,
            avg_win_usd=avg_win or 0,
            avg_loss_usd=avg_loss or 0,
            avg_win_loss_ratio=avg_win_loss_ratio,
            max_consecutive_losses=int(max_consec_losses or 0),
            sharpe_ratio=sharpe or -5.0,
            margin_level_min_pct=margin_level_min or 0,
        )

        result.check_targets()
        return result

    @staticmethod
    def _extract_text(soup: BeautifulSoup, pattern: str, group: int = 0) -> Optional[str]:
        """Extract text matching pattern from HTML."""
        text_content = soup.get_text()
        match = re.search(pattern, text_content, re.IGNORECASE)
        if match:
            try:
                return match.group(group)
            except IndexError:
                return None
        return None

    @staticmethod
    def _extract_number(soup: BeautifulSoup, pattern: str, group: int = 0) -> Optional[float]:
        """Extract number matching pattern from HTML."""
        text_content = soup.get_text()
        # Find number after pattern (within 300 chars)
        match = re.search(f"{pattern}[^\\d]*?([+-]?\\d+\\.?\\d*)", text_content, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def _parse_number(text: Optional[str]) -> Optional[float]:
        """Parse number from text string."""
        if not text:
            return None
        match = re.search(r'[\d.]+', text)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
        return None
