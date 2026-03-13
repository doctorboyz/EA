# Aureus AI Trading Bot - Task Progress Tracker

**Project Start:** March 13, 2026
**Current Phase:** 1 - Foundation (COMPLETE ✓)

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

## Phase 2: Analysis Loop (PENDING)

**Goal:** Implement database persistence and LLM analysis

### Phase 2 Tasks

| Task | Status | Assigned To | Est. Days |
|---|---|---|---|
| PostgreSQL Database Setup | ⏳ | Phase 2 | 1 |
| Alembic Migrations | ⏳ | Phase 2 | 1 |
| OllamaClient Wrapper | ⏳ | Phase 2 | 2 |
| ResultAnalyzerAgent | ⏳ | Phase 2 | 2 |
| StrategyImproverAgent | ⏳ | Phase 2 | 2 |
| Database Integration Tests | ⏳ | Phase 2 | 1 |
| **Phase 2 Milestone** | ⏳ | | **9 days** |

**Phase 2 Goals:**
- [ ] PostgreSQL database with JSONB config storage
- [ ] Alembic migrations for schema management
- [ ] OllamaClient with retry logic and structured output
- [ ] ResultAnalyzerAgent identifies weaknesses via llama3.2:3b
- [ ] StrategyImproverAgent proposes parameter changes
- [ ] Store all backtest results in database
- [ ] Milestone: System correctly diagnoses V4 failure from stored data

---

## Phase 3: Code Generation (PENDING)

**Goal:** Generate valid MQL5 code from StrategyConfig

### Phase 3 Tasks

| Task | Status | Assigned To | Est. Days |
|---|---|---|---|
| Jinja2 MQL5 Templates | ⏳ | Phase 3 | 3 |
| CodeGeneratorAgent | ⏳ | Phase 3 | 3 |
| Template Testing | ⏳ | Phase 3 | 2 |
| **Phase 3 Milestone** | ⏳ | | **8 days** |

**Phase 3 Goals:**
- [ ] Jinja2 templates for MQL5 (risk management, entry, exit)
- [ ] CodeGeneratorAgent renders templates + LLM fills logic
- [ ] Generated code passes ConstraintValidator
- [ ] Regenerate V3-equivalent code from config
- [ ] Milestone: Generated code compiles and passes all constraints

---

## Phase 4: Full Loop (PENDING)

**Goal:** End-to-end automation with 10 self-improvement iterations

### Phase 4 Tasks

| Task | Status | Assigned To | Est. Days |
|---|---|---|---|
| BacktestRunnerAgent | ⏳ | Phase 4 | 2 |
| MT5 Subprocess Handling | ⏳ | Phase 4 | 2 |
| NewsFilterAgent | ⏳ | Phase 4 | 2 |
| OrchestratorAgent | ⏳ | Phase 4 | 3 |
| 10-Iteration Test Run | ⏳ | Phase 4 | 2 |
| **Phase 4 Milestone** | ⏳ | | **11 days** |

**Phase 4 Goals:**
- [ ] BacktestRunnerAgent copies .mq5 to MT5, runs tester, waits for HTML
- [ ] NewsFilterAgent fetches ForexFactory calendar, blocks high-impact hours
- [ ] Orchestrator manages full loop: Generate → Test → Parse → Analyze → Improve
- [ ] Run 10 iterations unattended
- [ ] Milestone: System produces strategy with PF > 1.3

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
| Phase 2 | 9 | ⏳ In queue |
| Phase 3 | 8 | ⏳ In queue |
| Phase 4 | 11 | ⏳ In queue |
| Phase 5 | 9 | ⏳ In queue |
| **Total** | **44** | |

---

## Next Immediate Actions

1. **Phase 2 Start:** PostgreSQL database + migrations
2. **Quick Win:** Run V3 on full 2025-01-01 to 2026-03-12 period (establish fair baseline)
3. **Database Integration:** Store all results in PostgreSQL for correlation analysis
4. **Ollama Integration:** Implement OllamaClient wrapper with retry logic

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

**Last Updated:** Phase 1 Complete - Ready for Phase 2
**Next Review:** After Phase 2 milestone (database + analyzer working)
