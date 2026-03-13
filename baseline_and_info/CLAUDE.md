# CLAUDE.md - Aureus AI Trading Bot System

## System Overview

This is an **AI-powered agent orchestration system** that auto-generates, tests, and iteratively improves MQL5 Expert Advisors (trading bots) for MetaTrader 5.

**Goal:** Reach target metrics (Profit Factor > 1.5, Max DD < 15%, Recovery Factor > 3.0, Win/Loss Ratio > 2.0) on EURUSD.

**Current State:** Phase 1 Foundation - core models, validators, and report parser implemented. Ready to parse existing backtest HTML reports into database.

---

## Critical Domain Knowledge (READ FIRST)

### Why V4 Failed — The 10% Risk Bug

V4 (Aureus_Trend_Hunter_4.mq5) blew the account due to:

```
FixedLossUSD = 10.0 (line ~12)
Initial Capital = $100
Risk per trade = $10 / $100 = 10% per trade
```

This is catastrophic. A single losing trade = 10% loss. Four consecutive losses = 34% drawdown. Happened repeatedly → 101.71% drawdown → account blown.

**The Hard Rule:** `core/constraint_validator.py` bans "FixedLossUSD" pattern. Any generated code with this word is **REJECTED** before it ever runs.

**The Fix:** Use percentage-based risk (V3 logic):
```
lot_size = (balance * risk_percent / 100) / (stop_loss_pips * 10 * tick_value)
```

### Target Metrics (from AUREUS_INSPECTION_GUIDELINE.md)

| Metric | Target | V3 Actual | V4 Actual | Status |
|---|---|---|---|---|
| Profit Factor | > 1.5 | 1.24 | 0.64 | V3 closest |
| Max Drawdown % | < 15% | 8.92% | 101.71% | V3 passing |
| Recovery Factor | > 3.0 | 0.77 | -0.93 | Both failing |
| Win/Loss Ratio | > 2.0 | 0.87 | 0.87 | Both failing |

**V3 is the baseline to beat.** It works on Jan-Mar 2026 (PF 1.24, DD 8.92%) but hasn't been tested on the full 14-month period like V4.

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (run_loop.py)              │
│  Main loop: Generate → Test → Parse → Analyze → Improve   │
└─────────────────────────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ Agent 1: CodeGenerator      → Agent 2: BacktestRunner → Agent 3: Parser │
│ (qwen2.5-coder:7b)          │ (subprocess/Wine)       │ (BeautifulSoup)  │
│ Render MQL5 templates        │ Runs MT5 Strategy       │ Parses UTF-16    │
│                              │ Tester                  │ HTML reports     │
└──────────────────────────────────────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ Agent 4: ResultAnalyzer     → Agent 5: StrategyImprover → Back to Gen   │
│ (llama3.2:3b)               │ (Rule-based + LLM)                         │
│ Identifies weaknesses       │ Proposes parameter changes                 │
└──────────────────────────────────────────────────────────────────────────┘
           ↓
        PostgreSQL Database (stores all history for correlation analysis)
```

---

## Project Structure

```
aureus-ai/
├── config/
│   ├── system.yaml              # MT5 paths, Ollama URL, DB connection
│   ├── strategy_defaults.yaml   # Parameter ranges (min/max/default/step)
│   ├── trading_rules.yaml       # IMMUTABLE hard constraints
│   └── pairs.yaml               # EURUSD/GBPUSD/USDJPY characteristics
│
├── core/
│   ├── strategy_config.py       # Pydantic models (StrategyConfig, BacktestResult, etc.)
│   ├── constraint_validator.py  # Hard rules enforcement (NEVER relax)
│   ├── metrics_calculator.py    # Pure math: PF, DD, RF, Sharpe, etc.
│   ├── database.py              # SQLAlchemy ORM (PostgreSQL)
│   ├── ollama_client.py         # Ollama API wrapper (retry, timeout)
│   └── mt5_bridge.py            # MT5 subprocess/Wine path translator
│
├── agents/
│   ├── orchestrator.py          # Main improvement loop
│   ├── code_generator.py        # Agent 1: MQL5 via Ollama qwen2.5-coder:7b
│   ├── backtest_runner.py       # Agent 2: Runs MT5 Strategy Tester
│   ├── report_parser.py         # Agent 3: Parses HTML (UTF-16 LE)
│   ├── result_analyzer.py       # Agent 4: Weaknesses via llama3.2:3b
│   ├── strategy_improver.py     # Agent 5: Rule-based + LLM improvements
│   └── news_filter.py           # Agent 6: ForexFactory calendar
│
├── templates/
│   ├── mql5/
│   │   ├── base_ea.mq5.jinja2
│   │   ├── risk_management.mql5.jinja2  # % risk lot sizing
│   │   ├── entry_logic.mql5.jinja2
│   │   └── exit_logic.mql5.jinja2
│   └── prompts/
│       ├── code_gen_system.txt
│       ├── analysis_system.txt
│       └── improve_system.txt
│
├── strategies/
│   ├── baseline/                # V1, V2, V3, V4 originals (never modified)
│   ├── generated/               # LLM output .mq5 files
│   ├── validated/               # Passed ConstraintValidator
│   ├── champion/                # Current best performer
│   └── archive/                 # All historical (timestamped)
│
├── reports/
│   ├── raw/                     # MT5 HTML reports
│   ├── parsed/                  # JSON extracted metrics
│   └── analysis/                # LLM analysis text
│
├── database/
│   └── migrations/              # Alembic migration files
│
├── tests/
│   ├── test_report_parser.py    # Parse V3/V4 HTML fixtures
│   ├── test_constraint_validator.py  # Verify hard rules work
│   ├── test_metrics_calculator.py
│   └── fixtures/
│       ├── V3-sample-report.html  # Best performer (PF 1.24)
│       └── V4-sample-report.html  # Catastrophic failure (DD 101.71%)
│
├── scripts/
│   ├── run_loop.py              # Entry point: starts improvement loop
│   ├── run_single_backtest.py   # Test one strategy manually
│   ├── check_ollama.py          # Health check
│   └── export_results.py        # Export to CSV/Excel
│
├── logs/
│   ├── orchestrator.log
│   ├── agent_calls.log
│   └── mt5_bridge.log
│
└── pyproject.toml
```

---

## Key Files & Their Purpose

### Core Models

- **[core/strategy_config.py](core/strategy_config.py)** — Pydantic models with field validation
  - `StrategyConfig` — all parameters with bounds (prevents invalid configs)
  - `BacktestResult` — parsed metrics + target evaluation
  - `Weakness`, `AnalysisReport` — LLM output structures

- **[core/constraint_validator.py](core/constraint_validator.py)** — IMMUTABLE rules
  - `validate_config()` — check StrategyConfig bounds
  - `validate_mql5_code()` — check generated code (bans "FixedLossUSD")
  - `enforce()` — raises `ConstraintViolation` if anything fails
  - **NEVER RELAX THESE RULES.** V4 failure is encoded here.

- **[core/metrics_calculator.py](core/metrics_calculator.py)** — Pure math
  - `profit_factor()` — Gross Profit / Gross Loss
  - `recovery_factor()` — Net Profit / Max DD
  - `win_loss_ratio()` — Avg Win / Avg Loss
  - V3/V4 metrics embedded for reference

### Agents (Phase 1 Complete)

- **[agents/report_parser.py](agents/report_parser.py)** — Agent 3
  - Parses MT5 HTML reports (UTF-16 LE encoded)
  - Handles real files from `tests/fixtures/`
  - Returns `BacktestResult` Pydantic object
  - **Note:** UTF-16 LE encoding required (not UTF-8)

### Tests

- **[tests/test_constraint_validator.py](tests/test_constraint_validator.py)** — V4 bug detection
  - V3 config passes all constraints ✓
  - V4 FixedLossUSD pattern rejected ✓
  - R/R ratio, RSI thresholds, SL minimum all enforced

- **[tests/test_report_parser.py](tests/test_report_parser.py)** — HTML parsing
  - Parses real V3 and V4 HTML fixture files
  - Extracts all metrics correctly

---

## How to Use This System

### 1. Parse Existing Reports (Phase 1 Complete)

```bash
# Test report parser on real files
python -m pytest tests/test_report_parser.py -v

# Quick smoke test
python tests/test_report_parser.py
```

Expected output:
```
Testing V3 report parsing...
✓ V3 parsed: PF=1.24, DD=8.92%

Testing V4 report parsing...
✓ V4 parsed: PF=0.64, DD=101.71%
```

### 2. Validate Constraints

```bash
python -m pytest tests/test_constraint_validator.py -v
```

### 3. Database Setup (Phase 2)

```sql
-- Create database
createdb aureus

-- Run migrations
alembic upgrade head
```

### 4. Run Improvement Loop (Phase 4+)

```bash
python scripts/run_loop.py \
  --iterations 50 \
  --symbol EURUSD \
  --capital 1000
```

### 5. Export Results

```bash
python scripts/export_results.py --output results.csv
```

---

## Configuration Files Explained

### [config/system.yaml](config/system.yaml)

- **database.url** — PostgreSQL connection string
- **mt5.mode** — "wine" (macOS Whisky) | "vm_shared_folder" | "remote"
- **ollama.base_url** — Usually `http://localhost:11434`
- **ollama.code_gen_model** — `qwen2.5-coder:7b` for MQL5 generation
- **ollama.analysis_model** — `llama3.2:3b` for results analysis

### [config/strategy_defaults.yaml](config/strategy_defaults.yaml)

Parameter search space. Each parameter has:
- **default** — starting value
- **min, max, step** — bounds and granularity
- **immutable** — can LLM change it? (usually false)

V3 defaults:
```yaml
risk_percent: 1.0        # 1% per trade (not 10% like V4!)
ema_period: 200          # Trend filter
rsi_oversold: 30.0       # Mean reversion entry
rsi_overbought: 70.0
stop_loss_pips: 30
take_profit_pips: 90     # 3:1 R/R ratio
```

### [config/trading_rules.yaml](config/trading_rules.yaml)

**IMMUTABLE constraints.** Examples:

```yaml
- name: "no_fixed_usd_risk"
  mql5_banned_patterns:
    - "FixedLossUSD"      # V4 failure
  enforcement: "REJECT_AND_RETRY"
  severity: "CRITICAL"

- name: "min_rr_ratio"
  formula: "take_profit_pips / stop_loss_pips >= 2.0"
  enforcement: "REJECT_AND_RETRY"
  severity: "CRITICAL"
```

---

## MT5 Integration on macOS (Wine/Whisky)

The MetaTrader5 pip package only works on Windows. On macOS with Wine:

1. **BacktestRunnerAgent** copies `.mq5` files to `mt5:experts_path`
2. Launches MT5 via subprocess: `wine terminal64.exe /config:tester.ini`
3. Polls `mt5:reports_path` for new HTML report (5-second intervals, 5-minute timeout)
4. Passes HTML path to ReportParser

**Path Setup in [config/system.yaml](config/system.yaml):**
```yaml
mt5:
  mode: "wine"
  whisky_bottle: "/Users/mac/.wine/drive_c"  # Or Whisky container path
  experts_path: ".../MetaTrader 5/MQL5/Experts/Aureus/"
  reports_path: ".../MetaTrader 5/tester/reports/"
  mt5_exe: ".../MetaTrader 5/terminal64.exe"
```

---

## HTML Report Parsing Details

MT5 exports HTML reports in **UTF-16 LE** encoding (not UTF-8).

```python
# Correct way
with open(report_path, 'r', encoding='utf-16') as f:
    html = f.read()

# Wrong way (will fail)
with open(report_path, 'r', encoding='utf-8') as f:  # ❌
    html = f.read()
```

[agents/report_parser.py](agents/report_parser.py) handles this automatically.

---

## Hard Constraints Philosophy

These rules are **never negotiable** and encoded in two places:

1. **[core/constraint_validator.py](core/constraint_validator.py)** — Python validation at generation time
2. **[config/trading_rules.yaml](config/trading_rules.yaml)** — Human-readable documentation

If you think a constraint should be relaxed, **do not modify the code.** Instead:
1. Document the reason
2. Create an exception handler in the improver agent
3. Log why the exception was made (for learning)

Example: If ADX filtering would help, enable it in `config/strategy_defaults.yaml` but keep `use_adx_filter: false` by default (V4 over-filtered).

---

## Ollama Models Required

| Model | RAM | Purpose |
|---|---|---|
| `qwen2.5-coder:7b` | ~5GB | Generate MQL5 code (C++ syntax awareness) |
| `llama3.2:3b` | ~2.5GB | Analyze results, propose improvements |

**Setup:**
```bash
ollama pull qwen2.5-coder:7b
ollama pull llama3.2:3b
ollama serve  # Start server on http://localhost:11434
```

Check availability:
```bash
python scripts/check_ollama.py
```

---

## Development Workflow

### Adding a New Constraint

1. Add rule to `[config/trading_rules.yaml](config/trading_rules.yaml)`
2. Implement check in `core/constraint_validator.py`
3. Add test case in `tests/test_constraint_validator.py`
4. Document in CLAUDE.md

### Debugging Report Parsing

```bash
# Test fixture parsing
python tests/test_report_parser.py

# Debug specific report
python -c "
from agents.report_parser import ReportParser
result = ReportParser.parse('tests/fixtures/V3-sample-report.html')
print(f'PF={result.profit_factor}, DD={result.max_drawdown_pct}%')
"
```

### Testing Improvements

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test
python -m pytest tests/test_constraint_validator.py::TestConstraintValidator::test_v3_config_passes -v
```

---

## Next Steps (Phases 2-5)

- **Phase 2:** Database + Ollama client + ResultAnalyzer
- **Phase 3:** Jinja2 templates + CodeGenerator
- **Phase 4:** Orchestrator + NewsFilter + full loop
- **Phase 5:** Multi-pair testing, walk-forward validation

See `/Users/mac/.claude/plans/partitioned-gliding-anchor.md` for full implementation plan.

---

## Quick Reference

| Term | Definition |
|---|---|
| **Profit Factor** | Gross Profit / Gross Loss. Target > 1.5 |
| **Max Drawdown %** | Worst peak-to-trough decline. Target < 15% |
| **Recovery Factor** | Net Profit / Max Drawdown. Target > 3.0 |
| **Win/Loss Ratio** | Avg Win USD / Avg Loss USD. Target > 2.0 |
| **R/R Ratio** | TP pips / SL pips. Must be >= 2.0 |
| **V3** | Best EA so far (PF 1.24, DD 8.92%). Baseline to beat. |
| **V4** | Failed EA (PF 0.64, DD 101.71%). Uses FixedLossUSD bug. |
| **ConstraintValidator** | Guards against V4 failures. NEVER relax rules. |
| **UTF-16 LE** | MT5 HTML report encoding. Not UTF-8. |

---

## Model Recommendation

Use **Claude Sonnet 4.6** (`claude-sonnet-4-6`) for all implementation work on this project:
- Strong code generation and MQL5 syntax understanding
- Good multi-file refactoring
- Sufficient for agent orchestration design
- Better than Haiku for this domain

Switch: Settings → Model, or `--model claude-sonnet-4-6`
