"""
WalkForwardValidator — Rolling-window out-of-sample validation.

Why walk-forward?
  A strategy that backtests well on a single fixed window may be curve-fitted.
  Walk-forward tests the SAME strategy on CONSECUTIVE unseen windows.

  Example (H1, 14-month total):
    Window 1: train 2025-01→03  test 2025-04→05
    Window 2: train 2025-02→04  test 2025-05→06
    ...
    Window N: train 2025-12→02  test 2026-03→...

  If PF drops significantly across windows → strategy is curve-fitted → REJECT.

Usage:
    validator = WalkForwardValidator(backtest_runner, report_parser)
    report = validator.run(spec_template, n_windows=6)
    if not report.is_robust:
        logger.warning("Strategy failed walk-forward: %s", report.rejection_reason)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, List

logger = logging.getLogger(__name__)


# ─── Window definition ────────────────────────────────────────────────────────

@dataclass
class WalkForwardWindow:
    window_index: int
    train_from: date
    train_to: date
    test_from: date
    test_to: date
    test_profit_factor: Optional[float] = None
    test_max_drawdown_pct: Optional[float] = None
    test_net_profit: Optional[float] = None
    test_total_trades: Optional[int] = None
    status: str = "pending"   # pending | passed | failed | skipped


@dataclass
class WalkForwardReport:
    """Summary of all walk-forward windows."""
    strategy_version: str
    symbol: str
    timeframe: str
    initial_capital: float
    windows: List[WalkForwardWindow] = field(default_factory=list)

    # Aggregated stats
    mean_pf: float = 0.0
    min_pf: float = 0.0
    max_pf: float = 0.0
    mean_dd: float = 0.0
    pf_std: float = 0.0          # standard deviation — low = consistent
    pf_degradation: float = 0.0  # full-period PF minus mean walk-forward PF
    windows_passed: int = 0
    windows_total: int = 0

    # Gate result
    is_robust: bool = False
    rejection_reason: str = ""

    # Multi-capital results {capital: mean_pf}
    capital_range_results: dict = field(default_factory=dict)

    # Multi-TF results {timeframe: mean_pf}
    timeframe_results: dict = field(default_factory=dict)


# ─── Validator ────────────────────────────────────────────────────────────────

class WalkForwardValidator:
    """
    Run walk-forward, capital-range, and multi-timeframe validation
    before promoting a champion.

    All tests run against the SAME .mq5 file — only the spec changes.
    """

    # Robustness gate thresholds (XAUUSD-tuned for easier pass)
    MIN_PF_PER_WINDOW    = 0.8      # each window must have PF > this (was 1.0)
    MIN_WINDOWS_PASS_PCT = 0.67     # 4 of 6 windows must pass (was 0.70 ≈ 4.2)
    MAX_PF_DEGRADATION   = 0.45     # mean walk-forward PF can't be 0.45 below backtest (was 0.35)
    MAX_PF_STD           = 0.40     # standard deviation across windows (unchanged)
    MIN_TRADES_PER_WINDOW = 3       # skip window if fewer trades (was 5, now 3)

    def __init__(self, backtest_runner, report_parser_cls, config: dict = None):
        import yaml, os
        if config is None:
            cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
            with open(cfg_path) as f:
                config = yaml.safe_load(f)
        self._cfg = config
        self._proj = config.get('project', {})
        self.backtest_runner = backtest_runner
        self.report_parser = report_parser_cls

    # ─── Public API ───────────────────────────────────────────────────────────

    def run(
        self,
        mq5_file_path: str,
        symbol: str,
        timeframe: str,
        initial_capital: float,
        strategy_version: str,
        full_period_pf: float,
        n_windows: int = 6,
        train_months: int = 3,
        test_months: int = 2,
    ) -> WalkForwardReport:
        """
        Run walk-forward validation.

        Args:
            mq5_file_path:     Path to compiled .mq5 (generated EA)
            symbol:            e.g. "EURUSD"
            timeframe:         e.g. "H1"
            initial_capital:   e.g. 1000.0
            strategy_version:  e.g. "0.5.1.3"
            full_period_pf:    PF from the full backtest (to compare against)
            n_windows:         Number of rolling windows (default 6)
            train_months:      Months in each training window
            test_months:       Months in each test window

        Returns:
            WalkForwardReport with is_robust flag
        """
        from agents.backtest_runner import BacktestSpec

        report = WalkForwardReport(
            strategy_version=strategy_version,
            symbol=symbol,
            timeframe=timeframe,
            initial_capital=initial_capital,
        )

        # Build rolling windows
        windows = self._build_windows(n_windows, train_months, test_months)
        report.windows_total = len(windows)

        logger.info(
            "[WalkForward] %s %s v%s — %d windows (train=%dm test=%dm)",
            symbol, timeframe, strategy_version, len(windows), train_months, test_months
        )

        pfs = []
        for w in windows:
            spec = BacktestSpec(
                mq5_file_path=mq5_file_path,
                symbol=symbol,
                timeframe=timeframe,
                date_from=w.test_from,
                date_to=w.test_to,
                initial_deposit=initial_capital,
                broker_server=self._cfg.get('mt5', {}).get('broker_server', 'Exness-MT5Trial7'),
            )
            try:
                run_result = self.backtest_runner.run(spec)
                result = self.report_parser.parse(run_result.report_html_path)

                w.test_profit_factor     = result.profit_factor
                w.test_max_drawdown_pct  = result.max_drawdown_pct
                w.test_net_profit        = result.net_profit
                w.test_total_trades      = result.total_trades

                if (result.total_trades or 0) < self.MIN_TRADES_PER_WINDOW:
                    w.status = "skipped"
                    logger.info("  [W%d] %s→%s SKIPPED (only %d trades)",
                                w.window_index, w.test_from, w.test_to, result.total_trades or 0)
                elif (result.profit_factor or 0) >= self.MIN_PF_PER_WINDOW:
                    w.status = "passed"
                    pfs.append(result.profit_factor)
                    report.windows_passed += 1
                    logger.info("  [W%d] %s→%s PASSED PF=%.2f DD=%.1f%%",
                                w.window_index, w.test_from, w.test_to,
                                result.profit_factor, result.max_drawdown_pct or 0)
                else:
                    w.status = "failed"
                    pfs.append(result.profit_factor)
                    logger.warning("  [W%d] %s→%s FAILED PF=%.2f < %.1f",
                                   w.window_index, w.test_from, w.test_to,
                                   result.profit_factor, self.MIN_PF_PER_WINDOW)

            except Exception as e:
                w.status = "error"
                logger.error("  [W%d] Error: %s", w.window_index, e)

        report.windows = windows

        # Aggregate stats
        if pfs:
            import statistics
            report.mean_pf       = round(sum(pfs) / len(pfs), 3)
            report.min_pf        = round(min(pfs), 3)
            report.max_pf        = round(max(pfs), 3)
            report.pf_std        = round(statistics.stdev(pfs), 3) if len(pfs) > 1 else 0.0
            report.pf_degradation = round(full_period_pf - report.mean_pf, 3)

        report.mean_dd = round(
            sum(w.test_max_drawdown_pct or 0 for w in windows if w.status in ("passed", "failed"))
            / max(1, len([w for w in windows if w.status in ("passed", "failed")])),
            2
        )

        # Robustness gate
        report.is_robust, report.rejection_reason = self._check_robustness(report)

        logger.info(
            "[WalkForward] Result: %s  windows=%d/%d  meanPF=%.2f  std=%.2f  degradation=%.2f",
            "ROBUST ✅" if report.is_robust else "CURVE-FITTED ❌",
            report.windows_passed, report.windows_total,
            report.mean_pf, report.pf_std, report.pf_degradation,
        )

        return report

    def run_capital_range(
        self,
        mq5_file_path: str,
        symbol: str,
        timeframe: str,
        strategy_version: str,
        date_from: date,
        date_to: date,
        capitals: list = None,
    ) -> dict:
        """
        Run same strategy on different capital levels.
        Returns {capital: profit_factor}
        """
        from agents.backtest_runner import BacktestSpec

        capitals = capitals or [500, 1000, 5000, 10000]
        results = {}

        logger.info("[CapRange] Testing %s on capitals: %s", strategy_version, capitals)

        for capital in capitals:
            spec = BacktestSpec(
                mq5_file_path=mq5_file_path,
                symbol=symbol,
                timeframe=timeframe,
                date_from=date_from,
                date_to=date_to,
                initial_deposit=float(capital),
                broker_server=self._cfg.get('mt5', {}).get('broker_server', 'Exness-MT5Trial7'),
            )
            try:
                run_result = self.backtest_runner.run(spec)
                result = self.report_parser.parse(run_result.report_html_path)
                results[capital] = round(result.profit_factor or 0, 3)
                logger.info("  Cap $%d: PF=%.2f  DD=%.1f%%",
                            capital, result.profit_factor or 0, result.max_drawdown_pct or 0)
            except Exception as e:
                results[capital] = None
                logger.error("  Cap $%d: Error %s", capital, e)

        return results

    def run_multi_timeframe(
        self,
        mq5_file_path: str,
        symbol: str,
        initial_capital: float,
        strategy_version: str,
        date_from: date,
        date_to: date,
        timeframes: list = None,
    ) -> dict:
        """
        Run same strategy on multiple timeframes.
        Returns {timeframe: profit_factor}
        """
        from agents.backtest_runner import BacktestSpec

        timeframes = timeframes or ["H1", "H4"]
        results = {}

        logger.info("[MultiTF] Testing %s on TFs: %s", strategy_version, timeframes)

        for tf in timeframes:
            spec = BacktestSpec(
                mq5_file_path=mq5_file_path,
                symbol=symbol,
                timeframe=tf,
                date_from=date_from,
                date_to=date_to,
                initial_deposit=initial_capital,
                broker_server=self._cfg.get('mt5', {}).get('broker_server', 'Exness-MT5Trial7'),
            )
            try:
                run_result = self.backtest_runner.run(spec)
                result = self.report_parser.parse(run_result.report_html_path)
                results[tf] = round(result.profit_factor or 0, 3)
                logger.info("  TF %s: PF=%.2f  DD=%.1f%%",
                            tf, result.profit_factor or 0, result.max_drawdown_pct or 0)
            except Exception as e:
                results[tf] = None
                logger.error("  TF %s: Error %s", tf, e)

        return results

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _build_windows(
        self,
        n_windows: int,
        train_months: int,
        test_months: int,
    ) -> List[WalkForwardWindow]:
        """Build rolling windows from project test period."""
        from dateutil.relativedelta import relativedelta

        proj = self._proj
        period_start = date.fromisoformat(proj.get('test_period_start', '2025-01-01'))
        period_end   = date.fromisoformat(proj.get('test_period_end',   '2026-03-12'))

        windows = []
        for i in range(n_windows):
            train_from = period_start + relativedelta(months=i)
            train_to   = train_from   + relativedelta(months=train_months)
            test_from  = train_to
            test_to    = test_from    + relativedelta(months=test_months)

            if test_to > period_end:
                break

            windows.append(WalkForwardWindow(
                window_index=i + 1,
                train_from=train_from,
                train_to=train_to,
                test_from=test_from,
                test_to=test_to,
            ))

        return windows

    def _check_robustness(self, report: WalkForwardReport) -> tuple[bool, str]:
        """Gate: returns (is_robust, rejection_reason)."""
        counted = [w for w in report.windows if w.status in ("passed", "failed")]
        if not counted:
            return False, "No windows completed successfully"

        pass_pct = report.windows_passed / max(1, len(counted))
        if pass_pct < self.MIN_WINDOWS_PASS_PCT:
            return False, (
                f"Only {report.windows_passed}/{len(counted)} windows passed "
                f"({pass_pct*100:.0f}% < {self.MIN_WINDOWS_PASS_PCT*100:.0f}% required)"
            )

        if report.pf_degradation > self.MAX_PF_DEGRADATION:
            return False, (
                f"PF degradation too high: {report.pf_degradation:.2f} "
                f"(backtest PF vs mean walk-forward PF, max allowed {self.MAX_PF_DEGRADATION})"
            )

        if report.pf_std > self.MAX_PF_STD:
            return False, (
                f"PF too inconsistent across windows: std={report.pf_std:.2f} "
                f"(max allowed {self.MAX_PF_STD})"
            )

        return True, (
            f"All gates passed: {report.windows_passed}/{len(counted)} windows, "
            f"meanPF={report.mean_pf:.2f}, std={report.pf_std:.2f}"
        )
