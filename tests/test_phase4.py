"""Tests for Phase 4 components: BacktestRunner, NewsFilter, Orchestrator."""

import asyncio
import os
import tempfile
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from agents.backtest_runner import BacktestRunnerAgent, BacktestSpec, BacktestRunResult
from agents.news_filter import NewsFilterAgent, NewsEvent, BlockedWindow
from agents.orchestrator import OrchestratorAgent, LoopResult
from core.strategy_config import StrategyConfig, StrategyVersion, BacktestResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
V3_FIXTURE = os.path.join(FIXTURE_DIR, 'V3-sample-report.html')


def _v3_config() -> StrategyConfig:
    return StrategyConfig(
        version=StrategyVersion(major=0, minor=3, iteration=0),
        name="AureusTest",
        stop_loss_pips=30,
        take_profit_pips=90,
        breakeven_pips=15,
    )


def _mock_backtest_result() -> BacktestResult:
    r = BacktestResult(
        strategy_version="0.3.0",
        symbol="EURUSD",
        timeframe="H1",
        date_from="2025-01-01",
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
    r.check_targets()
    return r


# ---------------------------------------------------------------------------
# BacktestRunnerAgent tests
# ---------------------------------------------------------------------------

class TestBacktestRunnerAgent:

    def _agent_config(self, tmp_path: Path) -> dict:
        """Config pointing to temp directories."""
        return {
            "mt5": {
                "mode": "wine",
                "experts_path": str(tmp_path / "experts"),
                "reports_path": str(tmp_path / "reports"),
                "mt5_exe": str(tmp_path / "terminal64.exe"),
                "backtest_timeout_seconds": 30,
                "report_poll_interval_seconds": 1,
                "report_wait_timeout_seconds": 5,
            },
            "project": {
                "symbol": "EURUSD",
                "initial_capital": 1000.0,
            },
        }

    def test_dry_run_returns_fixture_path(self, tmp_path):
        agent = BacktestRunnerAgent(config=self._agent_config(tmp_path))
        spec = BacktestSpec(
            mq5_file_path=V3_FIXTURE,
            symbol="EURUSD",
            date_from=date(2025, 1, 1),
            date_to=date(2026, 3, 12),
        )
        result = agent.dry_run(spec, V3_FIXTURE)
        assert isinstance(result, BacktestRunResult)
        assert result.report_html_path == V3_FIXTURE
        assert result.duration_seconds == 0.0

    def test_missing_mq5_raises(self, tmp_path):
        agent = BacktestRunnerAgent(config=self._agent_config(tmp_path))
        spec = BacktestSpec(
            mq5_file_path="/nonexistent/path.mq5",
            date_from=date(2025, 1, 1),
            date_to=date(2026, 3, 12),
        )
        with pytest.raises(FileNotFoundError):
            agent.run(spec)

    def test_copy_ea_to_experts(self, tmp_path):
        agent = BacktestRunnerAgent(config=self._agent_config(tmp_path))
        # Create a dummy .mq5 file
        mq5_file = tmp_path / "test_ea.mq5"
        mq5_file.write_text("// test EA")
        ea_name = agent._copy_ea_to_experts(str(mq5_file))
        assert ea_name == "test_ea"
        assert (tmp_path / "experts" / "test_ea.mq5").exists()

    def test_write_tester_ini(self, tmp_path):
        # Create fake mt5_exe to get correct ini path
        mt5_exe = tmp_path / "terminal64.exe"
        mt5_exe.touch()
        cfg = self._agent_config(tmp_path)
        cfg["mt5"]["mt5_exe"] = str(mt5_exe)
        agent = BacktestRunnerAgent(config=cfg)
        spec = BacktestSpec(
            mq5_file_path=str(tmp_path / "test.mq5"),
            symbol="EURUSD",
            timeframe="H1",
            date_from=date(2025, 1, 1),
            date_to=date(2026, 3, 12),
            initial_deposit=1000.0,
        )
        ini_path = agent._write_tester_ini(spec, "AureusTest")
        assert os.path.exists(ini_path)
        content = open(ini_path).read()
        assert "Symbol=EURUSD" in content
        assert "Deposit=1000" in content
        assert "FromDate=2025.01.01" in content
        assert "Expert=Aureus\\AureusTest" in content
        assert "ShutdownTerminal=true" in content

    def test_wait_for_report_finds_new_file(self, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        cfg = self._agent_config(tmp_path)
        cfg["mt5"]["reports_path"] = str(reports_dir)
        cfg["mt5"]["report_wait_timeout_seconds"] = 3
        agent = BacktestRunnerAgent(config=cfg)
        existing = set()

        # Write a new report file after a short delay
        def write_report():
            import time
            time.sleep(0.5)
            (reports_dir / "ReportTest.html").write_text("<html>test</html>")

        import threading
        t = threading.Thread(target=write_report)
        t.start()
        path = agent._wait_for_report(existing)
        t.join()
        assert path.endswith("ReportTest.html")

    def test_wait_for_report_timeout(self, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        cfg = self._agent_config(tmp_path)
        cfg["mt5"]["reports_path"] = str(reports_dir)
        cfg["mt5"]["report_wait_timeout_seconds"] = 1
        cfg["mt5"]["report_poll_interval_seconds"] = 1
        agent = BacktestRunnerAgent(config=cfg)
        with pytest.raises(TimeoutError):
            agent._wait_for_report(set())


# ---------------------------------------------------------------------------
# NewsFilterAgent tests
# ---------------------------------------------------------------------------

class TestNewsFilterAgent:

    def test_no_events_when_fetch_fails(self):
        agent = NewsFilterAgent()
        # Force fetch to fail
        with patch.object(agent, '_fetch_events', return_value=[]):
            windows = agent.get_blocked_windows()
        assert windows == []

    def test_blocks_high_impact_eur_event(self):
        agent = NewsFilterAgent(block_hours_before=1, block_hours_after=2)
        now = datetime.now(tz=timezone.utc)
        event_dt = now + timedelta(hours=1)

        mock_events = [
            NewsEvent(
                event_datetime=event_dt,
                currency="EUR",
                impact="High",
                title="ECB Rate Decision",
            )
        ]
        with patch.object(agent, '_get_events', return_value=mock_events):
            windows = agent.get_blocked_windows()

        assert len(windows) == 1
        assert "ECB Rate Decision" in windows[0].reason
        assert windows[0].start <= event_dt <= windows[0].end

    def test_blocks_high_impact_usd_event(self):
        agent = NewsFilterAgent(block_hours_before=1, block_hours_after=2)
        now = datetime.now(tz=timezone.utc)
        nfp_dt = now + timedelta(hours=2)

        mock_events = [
            NewsEvent(
                event_datetime=nfp_dt,
                currency="USD",
                impact="High",
                title="Non-Farm Payrolls",
            )
        ]
        with patch.object(agent, '_get_events', return_value=mock_events):
            windows = agent.get_blocked_windows()

        assert len(windows) == 1
        assert "Non-Farm" in windows[0].reason

    def test_is_blocked_during_window(self):
        agent = NewsFilterAgent(block_hours_before=1, block_hours_after=2)
        now = datetime.now(tz=timezone.utc)
        event_dt = now  # event is NOW

        mock_events = [
            NewsEvent(
                event_datetime=event_dt,
                currency="USD",
                impact="High",
                title="FOMC Statement",
            )
        ]
        with patch.object(agent, '_get_events', return_value=mock_events):
            blocked, reason = agent.is_blocked(now)

        assert blocked
        assert "FOMC" in reason

    def test_not_blocked_outside_window(self):
        agent = NewsFilterAgent(block_hours_before=1, block_hours_after=2)
        now = datetime.now(tz=timezone.utc)
        future_event = now + timedelta(days=5)

        mock_events = [
            NewsEvent(
                event_datetime=future_event,
                currency="USD",
                impact="High",
                title="CPI",
            )
        ]
        with patch.object(agent, '_get_events', return_value=mock_events):
            blocked, _ = agent.is_blocked(now)

        assert not blocked

    def test_caches_events(self):
        agent = NewsFilterAgent()
        call_count = 0

        def mock_fetch():
            nonlocal call_count
            call_count += 1
            return []

        with patch.object(agent, '_fetch_events', side_effect=mock_fetch):
            agent._get_events()
            agent._get_events()  # Should use cache

        assert call_count == 1


# ---------------------------------------------------------------------------
# OrchestratorAgent tests (dry-run, no DB)
# ---------------------------------------------------------------------------

class TestOrchestratorAgent:
    """Tests for orchestrator loop logic — mocks DB and MT5."""

    def _make_orchestrator(self) -> OrchestratorAgent:
        return OrchestratorAgent(
            max_iterations=2,
            dry_run=True,
            dry_run_fixture=V3_FIXTURE,
            use_llm=False,
            config_override={
                "mt5": {
                    "mode": "wine",
                    "experts_path": "/tmp/experts",
                    "reports_path": "/tmp/reports",
                    "mt5_exe": "/tmp/terminal64.exe",
                    "backtest_timeout_seconds": 30,
                    "report_poll_interval_seconds": 1,
                    "report_wait_timeout_seconds": 5,
                },
                "project": {
                    "symbol": "EURUSD",
                    "timeframe": "H1",
                    "initial_capital": 1000.0,
                    "max_iterations": 2,
                    "test_period_start": "2025-01-01",
                    "test_period_end": "2026-03-12",
                },
                "ollama": {
                    "base_url": "http://localhost:11434",
                    "timeout_seconds": 30,
                    "code_gen_model": "qwen2.5-coder:7b",
                    "analysis_model": "llama3.2:3b",
                    "retry_attempts": 1,
                    "retry_backoff_factor": 1.0,
                },
                "database": {"url": "postgresql://postgres:password@localhost:5432/aureus"},
            },
        )

    @pytest.mark.asyncio
    async def test_dry_run_loop_completes(self, tmp_path):
        """Dry-run loop should complete without MT5 or DB."""
        orchestrator = self._make_orchestrator()

        # Mock database calls to avoid needing PostgreSQL
        async def mock_upsert(*args, **kwargs):
            m = MagicMock()
            m.id = 1
            return m

        async def mock_save_run(*args, **kwargs):
            m = MagicMock()
            m.id = 1
            return m

        async def mock_save_analysis(*args, **kwargs):
            pass

        with patch.object(orchestrator, '_upsert_strategy', side_effect=mock_upsert), \
             patch.object(orchestrator, '_save_backtest_run', side_effect=mock_save_run), \
             patch.object(orchestrator, '_save_analysis', side_effect=mock_save_analysis):
            result = await orchestrator.run()

        assert isinstance(result, LoopResult)
        assert result.iterations_run > 0
        assert result.champion_pf > 0

    @pytest.mark.asyncio
    async def test_champion_promoted_when_pf_improves(self, tmp_path):
        orchestrator = self._make_orchestrator()

        async def mock_upsert(*args, **kwargs):
            m = MagicMock(); m.id = 1; return m

        async def mock_save_run(*args, **kwargs):
            m = MagicMock(); m.id = 1; return m

        async def mock_save_analysis(*args, **kwargs): pass

        with patch.object(orchestrator, '_upsert_strategy', side_effect=mock_upsert), \
             patch.object(orchestrator, '_save_backtest_run', side_effect=mock_save_run), \
             patch.object(orchestrator, '_save_analysis', side_effect=mock_save_analysis), \
             patch('os.makedirs'), patch('shutil.copy2'), patch('json.dump'):
            result = await orchestrator.run()

        # V3 fixture has PF 1.24, so champion should be promoted
        assert result.champion_pf > 0

    @pytest.mark.asyncio
    async def test_loop_history_recorded(self, tmp_path):
        orchestrator = self._make_orchestrator()

        async def mock_upsert(*args, **kwargs):
            m = MagicMock(); m.id = 1; return m

        async def mock_save_run(*args, **kwargs):
            m = MagicMock(); m.id = 1; return m

        async def mock_save_analysis(*args, **kwargs): pass

        with patch.object(orchestrator, '_upsert_strategy', side_effect=mock_upsert), \
             patch.object(orchestrator, '_save_backtest_run', side_effect=mock_save_run), \
             patch.object(orchestrator, '_save_analysis', side_effect=mock_save_analysis):
            result = await orchestrator.run()

        assert len(result.history) == result.iterations_run
        for entry in result.history:
            assert "iteration" in entry
            assert "profit_factor" in entry
            assert "meets_all_targets" in entry

    def test_load_v3_baseline(self):
        orchestrator = self._make_orchestrator()
        config = orchestrator._load_v3_baseline()
        assert isinstance(config, StrategyConfig)
        assert config.risk_percent == 1.0
        assert config.stop_loss_pips == 30
        assert config.take_profit_pips == 90
        assert config.ema_period == 200


if __name__ == "__main__":
    # Quick smoke test for BacktestRunner dry_run
    agent = BacktestRunnerAgent(config={
        "mt5": {
            "mode": "wine",
            "experts_path": "/tmp/experts",
            "reports_path": "/tmp/reports",
            "mt5_exe": "/tmp/terminal64.exe",
            "backtest_timeout_seconds": 30,
            "report_poll_interval_seconds": 1,
            "report_wait_timeout_seconds": 5,
        },
        "project": {"symbol": "EURUSD", "initial_capital": 1000.0},
    })
    spec = BacktestSpec(
        mq5_file_path=V3_FIXTURE,
        date_from=date(2025, 1, 1),
        date_to=date(2026, 3, 12),
    )
    result = agent.dry_run(spec, V3_FIXTURE)
    print(f"✓ BacktestRunner dry_run: {result.report_html_path}")

    # NewsFilter smoke test
    news = NewsFilterAgent()
    windows = news.get_blocked_windows()
    print(f"✓ NewsFilter: {len(windows)} blocked windows (live fetch)")
