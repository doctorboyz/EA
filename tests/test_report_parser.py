"""Unit tests for ReportParser with real HTML fixtures."""

import pytest
from pathlib import Path
from agents.report_parser import ReportParser, ReportParserError
from core.strategy_config import BacktestResult


class TestReportParser:
    """Test HTML report parsing against real V3/V4 reports."""

    @pytest.fixture
    def v3_report_path(self) -> str:
        """Path to V3 sample report (best performer, PF 1.24)."""
        return str(Path("tests/fixtures/V3-sample-report.html"))

    @pytest.fixture
    def v4_report_path(self) -> str:
        """Path to V4 sample report (blown account, DD 101.71%)."""
        return str(Path("tests/fixtures/V4-sample-report.html"))

    def test_parse_v3_report(self, v3_report_path: str) -> None:
        """Test parsing of V3 (good) report."""
        result = ReportParser.parse(v3_report_path)

        assert isinstance(result, BacktestResult)
        assert result.symbol == "EURUSD"
        assert result.timeframe == "H1"

        # V3 metrics (PF 1.24, DD 8.92%)
        assert result.profit_factor > 1.0, "V3 should have positive PF"
        assert result.max_drawdown_pct > 0, "V3 should have some drawdown"
        assert result.total_trades > 0, "V3 should have trades"

    def test_parse_v4_report(self, v4_report_path: str) -> None:
        """Test parsing of V4 (catastrophic failure) report."""
        result = ReportParser.parse(v4_report_path)

        assert isinstance(result, BacktestResult)
        assert result.symbol == "EURUSD"

        # V4 failure metrics
        assert result.net_profit < 0, "V4 should have negative profit (blown account)"
        assert result.max_drawdown_pct > 100, "V4 should blow account (DD > 100%)"
        assert result.recovery_factor < 0, "V4 recovery factor should be negative"

    def test_target_checking(self, v3_report_path: str) -> None:
        """Test that target metrics are correctly evaluated."""
        result = ReportParser.parse(v3_report_path)

        # V3 slightly below targets
        if result.profit_factor < 1.5:
            assert not result.meets_pf_target
        if result.max_drawdown_pct > 15.0:
            assert not result.meets_dd_target

    def test_missing_file(self) -> None:
        """Test error handling for missing file."""
        with pytest.raises(ReportParserError):
            ReportParser.parse("/nonexistent/file.html")


if __name__ == "__main__":
    # Quick smoke test
    v3_path = "tests/fixtures/V3-sample-report.html"
    v4_path = "tests/fixtures/V4-sample-report.html"

    print("Testing V3 report parsing...")
    try:
        v3_result = ReportParser.parse(v3_path)
        print(f"✓ V3 parsed: PF={v3_result.profit_factor:.2f}, DD={v3_result.max_drawdown_pct:.2f}%")
    except Exception as e:
        print(f"✗ V3 parsing failed: {e}")

    print("\nTesting V4 report parsing...")
    try:
        v4_result = ReportParser.parse(v4_path)
        print(f"✓ V4 parsed: PF={v4_result.profit_factor:.2f}, DD={v4_result.max_drawdown_pct:.2f}%")
    except Exception as e:
        print(f"✗ V4 parsing failed: {e}")
