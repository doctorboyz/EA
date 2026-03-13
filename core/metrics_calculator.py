"""Pure math calculations for backtest metrics. No LLM, just math."""

from typing import List, Tuple


class MetricsCalculator:
    """Calculate trading metrics from raw trade data."""

    @staticmethod
    def profit_factor(gross_profit: float, gross_loss: float) -> float:
        """
        Profit Factor = Gross Profit / |Gross Loss|

        Target: > 1.5
        - PF < 1.0: losing system
        - PF 1.0-1.5: marginal edge
        - PF 1.5-2.5: strong edge
        - PF > 2.5: excellent edge
        """
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0
        return gross_profit / abs(gross_loss)

    @staticmethod
    def recovery_factor(net_profit: float, max_drawdown: float) -> float:
        """
        Recovery Factor = Net Profit / Max Drawdown (in USD)

        Target: > 3.0
        - RF < 1.0: losing system
        - RF 1.0-3.0: recovering slowly
        - RF > 3.0: strong recovery
        """
        if max_drawdown == 0:
            return float('inf') if net_profit > 0 else 0
        return net_profit / max(abs(max_drawdown), 0.01)  # Avoid divide by zero

    @staticmethod
    def win_loss_ratio(avg_win: float, avg_loss: float) -> float:
        """
        Win/Loss Ratio = Average Win / |Average Loss|

        Target: > 2.0

        This is the edge from R/R ratio. Even with 40% win rate:
        Expected Payoff = (0.4 * avg_win) - (0.6 * avg_loss)
        With 2.0 ratio: (0.4 * 2) - (0.6 * 1) = 0.8 - 0.6 = +0.2 = +20% edge per trade
        """
        if avg_loss == 0:
            return float('inf') if avg_win > 0 else 0
        return avg_win / abs(avg_loss)

    @staticmethod
    def sharpe_ratio(equity_curve: List[float]) -> float:
        """
        Sharpe Ratio = (Average Return - Risk-Free Rate) / Std Dev of Returns

        Simplified: (Mean Daily Return) / (Std Dev Daily Return)

        Benchmark:
        - Sharpe > 1.0: good
        - Sharpe > 2.0: excellent
        - Sharpe < 0: losing period

        MT5 returns -5.0 as floor value for negative/undefined periods.
        """
        if len(equity_curve) < 2:
            return -5.0

        # Calculate daily returns
        returns = []
        for i in range(1, len(equity_curve)):
            daily_ret = (equity_curve[i] - equity_curve[i-1]) / max(equity_curve[i-1], 0.01)
            returns.append(daily_ret)

        if not returns:
            return -5.0

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)

        if variance == 0:
            return -5.0

        std_dev = variance ** 0.5
        if std_dev == 0:
            return -5.0

        # Assume risk-free rate ~0% (we're measuring excess return vs no trading)
        sharpe = mean_ret / std_dev if std_dev != 0 else -5.0

        return max(sharpe, -5.0)

    @staticmethod
    def consecutive_losses(trades: List[Tuple[str, float]]) -> int:
        """
        Find maximum consecutive losing trades.

        trades: List of (direction, profit) tuples
        """
        max_consecutive = 0
        current_consecutive = 0

        for direction, profit in trades:
            if profit < 0:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0

        return max_consecutive

    @staticmethod
    def expected_payoff(total_profit: float, total_trades: int) -> float:
        """
        Expected Payoff = Total Profit / Total Trades

        This is the average profit per trade in currency units.

        - > 0: positive expectancy
        - < 0: negative expectancy
        """
        if total_trades == 0:
            return 0
        return total_profit / total_trades

    @staticmethod
    def max_drawdown_pct(equity_curve: List[float], initial_capital: float) -> float:
        """
        Max Drawdown % = (Lowest Equity - Peak Equity) / Peak Equity * 100

        Target: < 15%
        """
        if not equity_curve or initial_capital == 0:
            return 0

        peak = equity_curve[0]
        max_dd = 0

        for equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        return max_dd

    @staticmethod
    def max_drawdown_usd(equity_curve: List[float]) -> float:
        """
        Max Drawdown in USD = Lowest Equity - Peak Equity
        """
        if not equity_curve:
            return 0

        peak = equity_curve[0]
        max_dd = 0

        for equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = peak - equity
            max_dd = max(max_dd, dd)

        return max_dd


# V3 baseline metrics (from AUREUS_INSPECTION_GUIDELINE.md targets)
V3_TARGET_METRICS = {
    'profit_factor': 1.5,
    'max_drawdown_pct': 15.0,
    'recovery_factor': 3.0,
    'win_loss_ratio': 2.0,
}

# V3 actual metrics from best report (PF 1.24, DD 8.92%)
V3_ACTUAL_METRICS = {
    'profit_factor': 1.24,
    'max_drawdown_pct': 8.92,
    'recovery_factor': 0.77,  # Below target
    'win_loss_ratio': 0.87,  # Below target (10.65 / 12.22)
}

# V4 failure metrics (blown account)
V4_FAILURE_METRICS = {
    'profit_factor': 0.64,
    'max_drawdown_pct': 101.71,
    'recovery_factor': -0.93,
    'win_loss_ratio': 0.87,
}
