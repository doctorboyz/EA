# Aureus AI Trading Bot - Task Progress Tracker

**Project Start:** March 13, 2026
**Current Phase:** 4 - Full Loop (COMPLETE ✓)

---

## Phase 1: Foundation ✓ COMPLETE

**Status:** Ready for Phase 2

### Phase 1 Milestones

| Task | Status | Details |
|---|---|---|
| Pydantic Models | ✓ | StrategyConfig, BacktestResult, Weakness, AnalysisReport |
| Constraint Validator | ✓ | Bans FixedLossUSD, enforces R/R ≥ 2.0, risk ≤ 2%, SL ≥ 20 pips |
| Metrics Calculator | ✓ | PF, DD%, RF, Sharpe, consecutive losses, expected payoff |
| Report Parser | ✓ | Parses MT5 HTML (UTF-16 LE), tested on V3/V4 files |
| Configuration System | ✓ | system.yaml, strategy_defaults.yaml, trading_rules.yaml, pairs.yaml |
| Unit Tests | ✓ | test_constraint_validator.py, test_report_parser.py |
| Documentation | ✓ | CLAUDE.md (400+ lines), README.md, PHASE_1_SUMMARY.md |
| Project Structure | ✓ | Organized directories with clear separation of concerns |

### Phase 1 Test Results

```
Report Parser:
  ✓ V3 parsed: PF=1.24, DD=9.33%, Trades=74
  ✓ V4 parsed: PF=0.64, DD=107.97%, Status=BLOWN

Constraint Validator:
  ✓ V3 config passes all constraints
  ✓ FixedLossUSD pattern rejected (V4 bug)
  ✓ Risk percent clamped to 0.5-2.0%
  ✓ R/R ratio enforced ≥ 2.0
  ✓ RSI thresholds validated
  ✓ Stop loss minimum enforced (≥ 20 pips)
  ✓ Breakeven sanity checked
```

---

## Phase 2: Analysis Loop ✓ COMPLETE

**Goal:** Implement database persistence and LLM analysis
**Completed:** March 13, 2026

### Phase 2 Tasks

| Task | Status | Files | Details |
|---|---|---|---|
| PostgreSQL Database Setup | ✓ | `core/database.py` | SQLAlchemy ORM models (Strategy, BacktestRun, Analysis, Improvement, NewsEvent) |
| Alembic Migrations | ✓ | `alembic.ini`, `database/migrations/` | env.py + 0001_initial_schema.py |
| OllamaClient Wrapper | ✓ | `core/ollama_client.py` | httpx + tenacity retry, health_check(), analyze(), generate_code() |
| ResultAnalyzerAgent | ✓ | `agents/result_analyzer.py` | 2-stage: rule-based + llama3.2:3b, graceful Ollama fallback |
| StrategyImproverAgent | ✓ | `agents/strategy_improver.py` | Rule-based fixes + LLM tuning + ConstraintValidator check |
| LLM Prompt Templates | ✓ | `templates/prompts/` | analysis_system.txt + improve_system.txt |
| Tests | ✓ | `tests/test_result_analyzer.py` | 12 new tests (24 total, all passing) |
| **Phase 2 Milestone** | ✓ | | **All 24 tests pass** |

### Phase 2 New Files
- `core/database.py` — 5 ORM tables with JSONB, async session factory
- `core/ollama_client.py` — Retry wrapper, health check, typed helpers
- `agents/result_analyzer.py` — Weakness detection + LLM root cause analysis
- `agents/strategy_improver.py` — Rule-based + LLM param changes, constraint-validated
- `alembic.ini` — Alembic config (loads URL from system.yaml)
- `database/migrations/env.py` — Alembic environment setup
- `database/migrations/versions/0001_initial_schema.py` — Initial DDL
- `templates/prompts/analysis_system.txt` — llama3.2:3b system prompt for analysis
- `templates/prompts/improve_system.txt` — llama3.2:3b system prompt for improvement
- `tests/test_result_analyzer.py` — 12 tests for agents + rule-based logic

### Phase 2 Test Results
```
✓ V3 weaknesses correctly identified (RF, Win/Loss, PF failing)
✓ V4 all 4 metrics flagged as failing (DD critical severity)
✓ Perfect strategy → no weaknesses
✓ Ollama unavailable → falls back to rule-based analysis
✓ V4 analysis identifies all 4 critical failures
✓ StrategyImproverAgent increases TP for low win/loss
✓ Every improved config passes ConstraintValidator
✓ Version bumped after every improvement
Total: 24/24 tests passing
```

### Phase 2 Database Setup (Run Once)
```bash
# Install psycopg2 driver for Alembic
pip install psycopg2-binary

# Create database (PostgreSQL must be running)
createdb aureus

# Run migrations
alembic upgrade head

# Verify
alembic current
```

**Phase 2 Goals:**
- [x] PostgreSQL database with JSONB config storage
- [x] Alembic migrations for schema management
- [x] OllamaClient with retry logic and structured output
- [x] ResultAnalyzerAgent identifies weaknesses via llama3.2:3b
- [x] StrategyImproverAgent proposes parameter changes
- [x] Milestone: System correctly diagnoses V4 failure (4 weaknesses detected)

---

## Phase 3: Code Generation ✓ COMPLETE

**Goal:** Generate valid MQL5 code from StrategyConfig
**Completed:** March 13, 2026

### Phase 3 Tasks

| Task | Status | Files | Details |
|---|---|---|---|
| Jinja2 MQL5 Template | ✓ | `templates/mql5/base_ea.mq5.jinja2` | Full EA: OnInit/OnTick/ExecuteTrade/CalculateLotSize/ManagePositions/etc |
| CodeGeneratorAgent | ✓ | `agents/code_generator.py` | Template render + optional LLM enrichment + ConstraintValidator gate |
| Code Gen Prompt | ✓ | `templates/prompts/code_gen_system.txt` | qwen2.5-coder:7b system prompt |
| Template Testing | ✓ | `tests/test_code_generator.py` | 27 tests (51 total, all passing) |
| **Phase 3 Milestone** | ✓ | | **V3-equivalent generated, 51/51 tests pass** |

**Phase 3 Goals:**
- [x] Jinja2 template for MQL5 (all sections: risk management, entry, exit, BE/trail)
- [x] CodeGeneratorAgent renders templates + optional LLM comment enrichment
- [x] Generated code passes ConstraintValidator (51/51 tests)
- [x] Regenerate V3-equivalent code from config
- [x] Milestone: Generated code passes all constraints with correct structure

---

## Phase 4: Full Loop ✓ COMPLETE

**Goal:** End-to-end automation with 10 self-improvement iterations
**Completed:** March 13, 2026

### Phase 4 Tasks

| Task | Status | Files | Details |
|---|---|---|---|
| BacktestRunnerAgent | ✓ | `agents/backtest_runner.py` | Wine subprocess, tester.ini writer, file poller, dry-run mode |
| NewsFilterAgent | ✓ | `agents/news_filter.py` | ForexFactory XML calendar, EUR/USD high-impact, 6h cache, blocked windows |
| OrchestratorAgent | ✓ | `agents/orchestrator.py` | Full loop: Generate→Test→Parse→Save DB→Analyze→Champion→Improve |
| CLI Entry Point | ✓ | `scripts/run_loop.py` | Pre-flight checks, --dry-run, --no-llm, --iterations, --output flags |
| Tests | ✓ | `tests/test_phase4.py` | 16 tests (67 total, all passing) |
| **Phase 4 Milestone** | ✓ | | **67/67 tests pass, full loop operational** |

### Phase 4 New Files
- `agents/backtest_runner.py` — MT5 via Wine subprocess + HTML report file polling
- `agents/news_filter.py` — ForexFactory XML calendar, blocked trading windows
- `agents/orchestrator.py` — Main improvement loop (7 steps per iteration)
- `scripts/run_loop.py` — CLI entry point with pre-flight checks
- `tests/test_phase4.py` — 16 tests for all Phase 4 components

### Phase 4 Fixes Applied
- `core/database.py`: Added `@asynccontextmanager` to `get_session()` so `async with get_session()` works in orchestrator
- `tests/test_phase4.py`: Changed `patch('builtins.open')` to `patch('json.dump')` in champion test to avoid interfering with Jinja2 template loading

**Phase 4 Goals:**
- [x] BacktestRunnerAgent copies .mq5 to MT5, runs tester, waits for HTML
- [x] NewsFilterAgent fetches ForexFactory calendar, blocks high-impact hours
- [x] Orchestrator manages full loop: Generate → Test → Parse → Analyze → Improve
- [x] CLI entry point with dry-run, health check, and results export
- [x] Milestone: 67/67 tests pass — full loop operational in dry-run mode

### Phase 4 Usage
```bash
# Dry-run (no MT5 needed — uses V3 fixture HTML)
python scripts/run_loop.py --dry-run --iterations 5 --no-llm

# Health check only
python scripts/run_loop.py --check

# Full live run (requires Wine + MT5 + Ollama + PostgreSQL)
python scripts/run_loop.py --iterations 10

# Save results to JSON
python scripts/run_loop.py --dry-run --output results.json
```

---

## Phase 5: Optimization (PENDING)

**Goal:** Multi-pair testing, walk-forward validation, champion system

### Phase 5 Tasks

| Task | Status | Assigned To | Est. Days |
|---|---|---|---|
| Parameter Correlation Analysis | ⏳ | Phase 5 | 2 |
| Multi-Pair Support | ⏳ | Phase 5 | 2 |
| Walk-Forward Validation | ⏳ | Phase 5 | 3 |
| Champion Promotion System | ⏳ | Phase 5 | 1 |
| Excel/CSV Export | ⏳ | Phase 5 | 1 |
| **Phase 5 Milestone** | ⏳ | | **9 days** |

**Phase 5 Goals:**
- [ ] Analyze parameter correlations in database
- [ ] Test strategies on GBPUSD and USDJPY
- [ ] Implement walk-forward validation (out-of-sample Q1 2026 test)
- [ ] Champion notification system
- [ ] Milestone: Strategy meets all 4 targets on EURUSD, tested on GBPUSD

---

## Critical Success Factors

### Hard Constraints (NEVER Relax)

1. ✓ **No Fixed USD Risk** — Bans "FixedLossUSD" (V4 guard)
2. ✓ **Max 2% Risk** — risk_percent ≤ 2.0%
3. ✓ **Min 2:1 R/R** — TP/SL ≥ 2.0
4. ✓ **Min 20 pip SL** — Broker spread eats tighter SL
5. ✓ **RSI Thresholds** — oversold ≤ 35, overbought ≥ 65
6. ✓ **Breakeven Sanity** — breakeven < take_profit
7. ✓ **EMA Not Noisy** — ema_period ≥ 150
8. ✓ **Spread Check** — max_spread_pips 1-3 pips

### Target Metrics

| Metric | Target | V3 Actual | V4 Actual |
|---|---|---|---|
| Profit Factor | > 1.5 | 1.24 | 0.64 |
| Max Drawdown % | < 15% | 8.92% | 101.71% |
| Recovery Factor | > 3.0 | 0.77 | -0.93 |
| Win/Loss Ratio | > 2.0 | 0.87 | 0.87 |

---

## Completed Artifacts

### Code Files
- ✓ `core/strategy_config.py` (285 lines)
- ✓ `core/constraint_validator.py` (150 lines)
- ✓ `core/metrics_calculator.py` (145 lines)
- ✓ `agents/report_parser.py` (155 lines)

### Configuration Files
- ✓ `config/system.yaml`
- ✓ `config/strategy_defaults.yaml`
- ✓ `config/trading_rules.yaml`
- ✓ `config/pairs.yaml`

### Test Files
- ✓ `tests/test_constraint_validator.py` (160 lines)
- ✓ `tests/test_report_parser.py` (95 lines)
- ✓ `tests/fixtures/V3-sample-report.html` (real data)
- ✓ `tests/fixtures/V4-sample-report.html` (real data)

### Documentation
- ✓ `CLAUDE.md` (400+ lines)
- ✓ `README.md` (250+ lines)
- ✓ `PHASE_1_SUMMARY.md` (350+ lines)
- ✓ `.env.example`

### Baseline Strategies
- ✓ `strategies/baseline/Aureus_H1_Systematic.mq5` (V1)
- ✓ `strategies/baseline/Aureus_H1_Systematic_v2.mq5` (V2)
- ✓ `strategies/baseline/Aureus_H1_Systematic_3.mq5` (V3 - best)
- ✓ `strategies/baseline/Aureus_Trend_Hunter_4.mq5` (V4 - failure)

---

## Known Issues & Resolutions

### Issue 1: V4's 10% Risk Bug
**Status:** ✓ RESOLVED
- **Root Cause:** `FixedLossUSD = 10.0` on $100 = 10% per trade
- **Solution:** ConstraintValidator bans "FixedLossUSD" pattern
- **Verification:** Test case in test_constraint_validator.py

### Issue 2: HTML Report Encoding
**Status:** ✓ RESOLVED
- **Root Cause:** MT5 reports are UTF-16 LE (not UTF-8)
- **Solution:** ReportParser uses `encoding='utf-16'`
- **Verification:** Successfully parses real V3/V4 HTML files

### Issue 3: V3 Baseline Never Tested on Full Period
**Status:** ⏳ TODO (Phase 2)
- **Issue:** V3 only tested Jan-Mar 2026, not full 14-month period
- **Action:** Run V3 on 2025-01-01 to 2026-03-12 with $1,000 capital
- **Target:** Establish fair baseline before improvement loop

---

## Key Metrics & Baselines

### V3 Baseline (Best Performer)
- **Profit Factor:** 1.24 (target > 1.5) ⚠️ Below target
- **Max Drawdown:** 8.92% (target < 15%) ✓ Below target
- **Total Trades:** 74
- **Win Rate:** 43%
- **Net Profit:** +$7.22 (on $100)
- **Period:** Jan-Mar 2026 (11 weeks)

### V4 Failure (Blown Account)
- **Profit Factor:** 0.64 (losing)
- **Max Drawdown:** 101.71% (catastrophic)
- **Net Profit:** -$100.05 (total wipeout)
- **Failure Cause:** FixedLossUSD = 10.0 = 10% risk per trade

### Improvement Target
To reach all 4 targets from V3 baseline (PF 1.24 → 1.5+):
- Improve PF by 21% (1.24 → 1.5)
- Improve RF by 290% (0.77 → 3.0+)
- Improve Win/Loss ratio by 130% (0.87 → 2.0+)
- Maintain DD < 15% (currently 8.92% ✓)

---

## Database Schema (Phase 2)

### PostgreSQL Tables (To Be Created)
```
strategies
├── id (SERIAL PK)
├── version_str (TEXT UNIQUE)
├── config (JSONB) -- queryable parameters
├── code_hash (TEXT)
├── code_path (TEXT)
├── parent_id (FK)
├── change_rationale (JSONB)
├── created_at (TIMESTAMPTZ)

backtest_runs
├── id (SERIAL PK)
├── strategy_id (FK)
├── symbol, timeframe, date_from, date_to
├── profit_factor, net_profit, max_drawdown_pct
├── recovery_factor, win_rate_pct, sharpe_ratio
├── meets_all_targets (BOOLEAN)
├── is_champion (BOOLEAN)
├── run_at (TIMESTAMPTZ)

analyses
├── id (SERIAL PK)
├── backtest_run_id (FK)
├── model_used (TEXT)
├── weaknesses_json (JSONB)
├── recommendations_json (JSONB)
├── created_at (TIMESTAMPTZ)

improvements
├── id (SERIAL PK)
├── analysis_id (FK)
├── from_strategy_id (FK)
├── to_strategy_id (FK)
├── improvement_type (TEXT)
├── param_changes_json (JSONB)
├── applied_at (TIMESTAMPTZ)

news_events
├── id (SERIAL PK)
├── event_datetime (DATETIME)
├── currency (TEXT)
├── impact (TEXT)
├── event_name (TEXT)
├── fetched_at (TIMESTAMPTZ)

parameter_correlations (materialized view)
├── parameter_name (TEXT)
├── parameter_value (REAL)
├── avg_profit_factor (REAL)
├── avg_drawdown_pct (REAL)
├── sample_count (INTEGER)
```

---

## Ollama Models to Use (Phase 2+)

| Model | Purpose | RAM | Status |
|---|---|---|---|
| qwen2.5-coder:7b | MQL5 code generation | ~5GB | ⏳ To be integrated Phase 3 |
| llama3.2:3b | Backtest analysis, improvement reasoning | ~2.5GB | ⏳ To be integrated Phase 2 |

Setup:
```bash
ollama pull qwen2.5-coder:7b
ollama pull llama3.2:3b
ollama serve  # Runs on http://localhost:11434
```

---

## Timeline Estimate

| Phase | Days | Status |
|---|---|---|
| **Phase 1** | **7** | ✓ **COMPLETE** |
| **Phase 2** | **9** | ✓ **COMPLETE** |
| **Phase 3** | **8** | ✓ **COMPLETE** |
| **Phase 4** | **11** | ✓ **COMPLETE** |
| Phase 5 | 9 | ⏳ In queue |
| **Total** | **44** | |

---

## Next Immediate Actions (Phase 5)

1. **Parameter Correlation Analysis** — SQL query to find which RSI/TP/SL values correlate with highest PF across backtest_runs
2. **Multi-Pair Support** — Extend StrategyConfig + Orchestrator to accept GBPUSD, USDJPY alongside EURUSD
3. **Walk-Forward Validation** — Split test period: train on 2025-01-01→2025-12-31, validate on 2026-01-01→2026-03-12
4. **Champion Notification** — Log/alert when a strategy meets all 4 targets (PF>1.5, DD<15%, RF>3.0, WL>2.0)
5. **CSV/Excel Export** — `scripts/export_results.py` dumps backtest_runs to Excel for manual review

---

## Git Commit History

| Commit | Message | Files |
|---|---|---|
| 4f79496 | Phase 1: Foundation - Core models, validators, and report parser | 44 files |

---

## Useful Commands

```bash
# Test report parser
python tests/test_report_parser.py

# Test constraints
python -m pytest tests/test_constraint_validator.py -v

# Run all tests
python -m pytest tests/ -v

# Check V3 config validation
python -c "
from core.strategy_config import StrategyConfig, StrategyVersion
from core.constraint_validator import ConstraintValidator

config = StrategyConfig(version=StrategyVersion(major=0, minor=3, iteration=0))
is_valid, violations = ConstraintValidator.validate_config(config)
print(f'V3 Valid: {is_valid}')
"

# Parse a report
python -c "
from agents.report_parser import ReportParser
result = ReportParser.parse('tests/fixtures/V3-sample-report.html')
print(f'PF={result.profit_factor}, DD={result.max_drawdown_pct}%')
"
```

---

**Last Updated:** Phase 4 Complete - Ready for Phase 5
**Next Review:** After Phase 5 milestone (all 4 targets met on EURUSD)
