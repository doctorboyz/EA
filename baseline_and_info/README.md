# Aureus AI Trading Bot - Phase 1: Foundation

**Status:** Phase 1 Foundation - Core models, validators, and report parser complete.

An AI-powered agent orchestration system that auto-generates, tests, and iteratively improves MQL5 Expert Advisors for MetaTrader 5.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Test Core Components

```bash
# Test report parser (parse real V3/V4 HTML files)
python tests/test_report_parser.py

# Test constraint validator (verify V4 bug is caught)
python -m pytest tests/test_constraint_validator.py -v

# Test all
python -m pytest tests/ -v
```

### 3. View Configuration

```bash
cat config/system.yaml        # System paths and Ollama URL
cat config/strategy_defaults.yaml  # Parameter search space
cat config/trading_rules.yaml  # Immutable hard constraints
```

## What's Built (Phase 1)

### ✓ Core Models
- `core/strategy_config.py` — Pydantic models with validation
  - `StrategyConfig` — strategy parameters (all bounds enforced)
  - `BacktestResult` — parsed metrics + target evaluation
  - `Weakness`, `AnalysisReport` — LLM output structures

### ✓ Hard Constraints
- `core/constraint_validator.py` — NEVER relaxed rules
  - Bans `FixedLossUSD` pattern (V4 failure guard)
  - Enforces R/R ratio >= 2.0, SL >= 20 pips, risk <= 2%
  - Validates RSI thresholds, breakeven sanity, etc.

### ✓ Metrics Calculator
- `core/metrics_calculator.py` — Pure math (no LLM)
  - Profit Factor, Recovery Factor, Win/Loss Ratio, Sharpe Ratio
  - V3/V4 benchmark metrics embedded

### ✓ Report Parser
- `agents/report_parser.py` — Agent 3 (complete)
  - Parses MT5 HTML reports (UTF-16 LE encoded)
  - Extracts all metrics: PF, DD%, RF, win_rate, avg_win_loss, etc.
  - Returns `BacktestResult` Pydantic object
  - **Test fixtures:** V3 (best, PF 1.24) and V4 (blown, DD 101.71%)

### ✓ Configuration
- `config/system.yaml` — DB, MT5, Ollama paths
- `config/strategy_defaults.yaml` — Parameter ranges
- `config/trading_rules.yaml` — Hard constraints + target metrics
- `config/pairs.yaml` — EURUSD/GBPUSD/USDJPY characteristics

### ✓ Tests
- `tests/test_report_parser.py` — Parse real HTML fixture files
- `tests/test_constraint_validator.py` — Verify constraints work
- `tests/fixtures/` — Real V3 and V4 HTML reports

### ✓ Documentation
- `CLAUDE.md` — Complete system documentation (read first)
- This README

## What's Not Built Yet (Phases 2-5)

- [ ] Phase 2: Database (PostgreSQL) + Ollama client + ResultAnalyzer
- [ ] Phase 3: Jinja2 MQL5 templates + CodeGenerator
- [ ] Phase 4: Orchestrator + NewsFilter + full improvement loop
- [ ] Phase 5: Multi-pair testing, walk-forward validation, champion system

## Test Results

### Report Parser
```
✓ V3 parsed: PF=1.24, DD=9.33%, Trades=74
✓ V4 parsed: PF=0.64, DD=107.97%, Status=BLOWN
```

### Constraint Validator
```
✓ V3 config passes all constraints
✓ FixedLossUSD pattern correctly rejected
✓ R/R ratio >= 2.0 enforced
✓ RSI thresholds clamped to safe range
```

## Key Files

| File | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | **READ FIRST** — Full system documentation |
| [core/strategy_config.py](core/strategy_config.py) | Pydantic models with validation |
| [core/constraint_validator.py](core/constraint_validator.py) | Hard rules (anti-V4 guards) |
| [agents/report_parser.py](agents/report_parser.py) | Parse MT5 HTML reports |
| [config/trading_rules.yaml](config/trading_rules.yaml) | Immutable constraints |
| [tests/test_constraint_validator.py](tests/test_constraint_validator.py) | Verify V4 bug is caught |

## V3 vs V4 Comparison

| Metric | V3 Baseline | V4 Failure | Target |
|---|---|---|---|
| Profit Factor | 1.24 | 0.64 | > 1.5 |
| Max Drawdown % | 8.92% | 101.71% | < 15% |
| Recovery Factor | 0.77 | -0.93 | > 3.0 |
| Win/Loss Ratio | 0.87 | 0.87 | > 2.0 |
| Net Profit | +$7.22 | -$100.05 | > 0 |

**V4 Failed Because:** `FixedLossUSD = 10.0` on $100 account = 10% risk per trade. Four consecutive losses = blown account.

**Guard:** `ConstraintValidator` bans "FixedLossUSD" pattern.

## Database Setup (Phase 2)

```bash
# Create PostgreSQL database
createdb aureus

# Run migrations
cd database
alembic upgrade head
```

Connection string in `config/system.yaml`:
```yaml
database:
  url: "postgresql://postgres:password@localhost:5432/aureus"
```

## MT5 Integration (macOS Wine/Whisky)

MetaTrader5 pip package only works on Windows. On macOS:

1. Copy `.mq5` to `mt5:experts_path`
2. Launch MT5: `wine terminal64.exe /config:tester.ini`
3. Poll `mt5:reports_path` for HTML report
4. Parse with `ReportParser`

Configuration in `config/system.yaml`:
```yaml
mt5:
  mode: "wine"
  whisky_bottle: "/Users/mac/.wine/drive_c"
  experts_path: ".../MetaTrader 5/MQL5/Experts/Aureus/"
  reports_path: ".../MetaTrader 5/tester/reports/"
  mt5_exe: ".../MetaTrader 5/terminal64.exe"
```

## Ollama Models Required (Phase 2+)

```bash
ollama pull qwen2.5-coder:7b   # Code generation (~5GB)
ollama pull llama3.2:3b        # Analysis (~2.5GB)
ollama serve                   # Start server on http://localhost:11434
```

## Next Steps

1. **Phase 2:** PostgreSQL database + migrations (Alembic)
2. **Phase 3:** MQL5 Jinja2 templates + CodeGeneratorAgent
3. **Phase 4:** Full improvement loop + NewsFilterAgent
4. **Phase 5:** Multi-pair testing + walk-forward validation

See `/Users/mac/.claude/plans/partitioned-gliding-anchor.md` for detailed plan.

## Hard Constraints (NEVER Relax)

From `config/trading_rules.yaml`:

```yaml
- "FixedLossUSD" pattern is BANNED        # V4 failure cause
- risk_percent <= 2.0%                    # No fixed USD risk
- take_profit / stop_loss >= 2.0          # Minimum 2:1 R/R
- rsi_oversold <= 35, overbought >= 65    # V4 used too loose 35/65
- stop_loss >= 20 pips                    # Broker spread eats tight SL
- breakeven < take_profit                 # Logical sanity
```

See `CLAUDE.md` for full philosophy.

## Development

```bash
# Run tests with coverage
python -m pytest tests/ -v --cov=core --cov=agents

# Test specific module
python -m pytest tests/test_constraint_validator.py::TestConstraintValidator::test_v3_config_passes -v

# Debug report parsing
python -c "
from agents.report_parser import ReportParser
result = ReportParser.parse('tests/fixtures/V3-sample-report.html')
print(f'PF={result.profit_factor}, DD={result.max_drawdown_pct}%')
"
```

## Model Recommendation

Use **Claude Sonnet 4.6** (`claude-sonnet-4-6`) for all implementation work:
- Strong MQL5 code generation
- Good multi-file refactoring
- Sufficient for agent orchestration
- Better than Haiku for this domain

Switch: Settings → Model, or `--model claude-sonnet-4-6`

---

**Last Updated:** Phase 1 Foundation Complete
**Status:** Ready for Phase 2 (Database + Ollama)
