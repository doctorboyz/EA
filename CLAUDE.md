# CLAUDE.md - Aureus AI Trading Bot System

## System Overview

This is an **AI-powered agent orchestration system** that auto-generates, tests, and iteratively improves MQL5 Expert Advisors (trading bots) for MetaTrader 5.

**Goal:** Find XAUUSD champion with clean metrics (PF > 1.3 at Champion tier, walk-forward validated).

**Current State:** Phase 5 complete - Full CrewAI integration, 8-framework XAUUSD rotation, tiered targets (Gate/Champion/Gold), phase-aware dashboard, automated improvement loop ready for extended hunt.

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

### Tiered Target System (XAUUSD-Specific)

| Metric | Gate | Champion | Gold |
|---|---|---|---|
| Profit Factor | > 1.0 | > 1.3 ✓ | > 1.8 |
| Max Drawdown % | < 40% | < 30% | < 20% |
| Recovery Factor | > 0.5 | > 1.0 | > 2.0 |
| Win/Loss Ratio | > 1.0 | > 1.5 | > 2.0 |

**Phase Gates:**
- **Hunt** (Phase 1): Run iterations, use 8 XAUUSD frameworks (80% exploit / 20% explore via ExperienceDB)
- **Walk-Forward** (Phase 2): Triggered when PF ≥ 1.3 (Champion tier). Needs 4/6 windows pass (PF ≥ 0.8 per window, max degradation 0.45)
- **Forward Test** (Phase 3): Triggered after WF passes. Deploy to demo 5+ days, 10+ trades, PF ≥ 1.1, DD ≤ 20%
- **Live** (Phase 4): Manual trigger, auto emergency-stop at DD = 20%

---

## Multi-Agent Orchestration Framework: CrewAI

**Orchestration split into two layers:**

1. **Deterministic Layer** (pure Python, no LLM):
   - BacktestRunner (MT5 subprocess)
   - ReportParser (BeautifulSoup, UTF-16 LE encoding)
   - ConstraintValidator (hard rules, V4 bug detection)

2. **Intelligence Layer** (CrewAI agents via Ollama):
   - CodeGenerator Agent → Renders MQL5 from StrategyConfig
   - ResultAnalyzer Agent → Identifies weaknesses
   - StrategyImprover Agent → Proposes parameter changes

**CrewAI Integration** (`agents/aureus_crew.py`):

```python
from crewai import Agent, Task, Crew, Process

crew = AureusCrewAI(config)
result = crew.analyze_and_improve(backtest_result, market_regime)
# Internally runs: crew.kickoff(inputs={...})
```

### The 5-Step Improvement Loop

```
[1] CodeGenerator.generate(config, framework)
     ↓
[2] BacktestRunner.run() → MT5 backtest
     ↓
[3] ReportParser.parse() → BacktestResult
     ↓
[4-5] AureusCrewAI.analyze_and_improve()
      → crew.kickoff() with 3 agents
      → returns improved config
     ↓
[Loop]
```

### Installation

```bash
pip install crewai crewai-tools langchain-community
```

---

## Architecture at a Glance

```
XAUUSD CHAMPION HUNTER — 4 PHASES
═══════════════════════════════════════════════════════════════════

[PHASE 1: HUNT]  PF iteration until ≥ 1.3
                 ↓
              [PHASE 2: WALK-FORWARD]  4/6 windows pass
                 ↓
              [PHASE 3: FORWARD TEST]  5+ days live demo
                 ↓
              [PHASE 4: LIVE]  Real account (manual enable)

DETERMINISTIC LAYER
───────────────────────────────────────────────────────────────
[CodeGenerator]  [BacktestRunner]  [ReportParser]  [ConstraintValidator]
(Jinja2)         (Wine/MT5)        (BeautifulSoup) (Hard rules)
   ↓                ↓                  ↓                ↓
v0.X.Y.Z.mq5   HTML report         BacktestResult   ✓ Valid / ✗ Reject

INTELLIGENCE LAYER (CrewAI)
───────────────────────────────────────────────────────────────
[CodeGenerator Agent]  →  [ResultAnalyzer Agent]  →  [StrategyImprover Agent]
(qwen2.5-coder:14b)      (qwen3.5:9b)                (qwen3.5:9b)
Generate MQL5            Identify weaknesses        Propose changes
   ↑                                                       ↓
   ←──── crew.kickoff() ────────────────────────────────←

DATABASE
───────────────────────────────────────────────────────────────
PostgreSQL: strategies, backtest_runs, analyses, walk_forward_runs, experiences
```

---

## Project Structure

```
aureus-ai/
├── dashboard.py                 # Single-page Streamlit UI (4 sections)
├── config/
│   ├── system.yaml              # MT5, Ollama, DB, tiered targets, walk-forward
│   ├── strategy_defaults.yaml   # Parameter ranges (min/max/default/step)
│   └── trading_rules.yaml       # IMMUTABLE hard constraints
│
├── core/
│   ├── strategy_config.py       # Pydantic models + tiered targets (Gate/Champion/Gold)
│   ├── constraint_validator.py  # Hard rules enforcement (NEVER relax)
│   ├── champion_manager.py      # DB-backed per-symbol champion tracking
│   ├── walk_forward.py          # Walk-forward validator (4/6 windows, PF ≥ 0.8)
│   ├── database.py              # SQLAlchemy ORM (PostgreSQL)
│   ├── ollama_client.py         # Ollama API wrapper (retry, timeout)
│   └── experience_db.py         # ExperienceDB (80/20 exploit/explore)
│
├── agents/
│   ├── orchestrator.py          # Main XAUUSD hunt loop (phase tracking)
│   ├── aureus_crew.py           # CrewAI crew (3 agents, 4 tools)
│   ├── code_generator.py        # Agent 1: MQL5 via qwen2.5-coder:14b
│   ├── backtest_runner.py       # Agent 2: Runs MT5 Strategy Tester
│   ├── report_parser.py         # Agent 3: Parses HTML (UTF-16 LE)
│   ├── result_analyzer.py       # Agent 4: Weaknesses (Champion-tier targets)
│   ├── strategy_improver.py     # Agent 5: Rule-based + LLM improvements
│   ├── news_filter.py           # Agent 6: ForexFactory calendar
│   ├── market_regime_detector.py # Regime classification (Trend/Range/Volatile)
│   ├── forward_test_manager.py  # Forward test deployment
│   └── live_trade_agent.py      # Live trade monitoring + safety
│
├── scripts/
│   ├── run_multi.py             # Entry point: XAUUSD hunt (all modes)
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

### Quick Start

```bash
cd /Users/doctorboyz/EA
source venv/bin/activate

# 1. Pre-flight
ollama serve                          # (separate terminal)
python scripts/check_ollama.py
python -m pytest tests/ -v

# 2. Start dashboard (separate terminal)
streamlit run dashboard.py            # → http://localhost:8501

# 3. Start hunt (click a button in dashboard, or run below)
python scripts/run_multi.py --symbols XAUUSD --iterations 20
```

### All Hunt Commands

```bash
# Always run first:
cd /Users/doctorboyz/EA && source venv/bin/activate

# ⚡ Quick Test (5 iterations, ~10 min)
python scripts/run_multi.py --symbols XAUUSD --iterations 5

# 🔍 Normal Hunt (20 iterations, ~30-60 min)
python scripts/run_multi.py --symbols XAUUSD --iterations 20

# 🏃 Long Hunt (50 iterations, ~1.5-3 hours)
python scripts/run_multi.py --symbols XAUUSD --iterations 50

# 🔄 Continuous (runs forever, restarts every 5 min)
python scripts/run_multi.py --symbols XAUUSD --continuous --iterations 20 --restart-delay 300

# 👑 Until Champion (stops when PF ≥ 1.3, max 48 hours)
python scripts/run_multi.py --symbols XAUUSD --until-champion --iterations 100 --max-hours 48
```

### Stop Commands

```bash
# Normal stop
kill $(cat logs/run_multi.pid)

# Force stop
pkill -9 -f "run_multi.py"

# Disable auto-start daemon
launchctl unload ~/Library/LaunchAgents/com.aureus.trading.plist

# Enable auto-start daemon
launchctl load ~/Library/LaunchAgents/com.aureus.trading.plist

# Check status
ps aux | grep run_multi | grep -v grep       # Running processes
cat logs/system_status.json | python -m json.tool  # Phase status
launchctl list | grep aureus                  # Daemon status
tail -f logs/orchestrator.log                 # Live logs
```

### Cleanup Commands

```bash
# Kill all + clean status
pkill -9 -f "run_multi.py"
rm -f logs/run_multi.pid logs/system_status.json
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```

### 8 XAUUSD Frameworks (Auto-Rotated)

| Framework | Strength | ExperienceDB Picks |
|---|---|---|
| XAUBreakout | ATR-channel for gold volatility | Primary (80% exploit) |
| TrendFollowing | EMA-based, proven PF=2.85 | Primary (80% exploit) |
| Breakout | Generic breakout | Explore (20%) |
| MeanReversion | RSI mean reversion | Explore (20%) |
| SniperEntry | Low-frequency, high-precision | Explore (20%) |
| CandlePattern | Pattern recognition | Explore (20%) |
| IchimokuCloud | Cloud + trend confirmation | Explore (20%) |
| GridTrading | For choppy/ranging markets | Explore (20%) |

---

## Configuration Files Explained

### [config/system.yaml](config/system.yaml)

**Key sections for XAUUSD hunt:**

```yaml
project:
  symbol: "XAUUSD"
  risk_percent: 0.5         # Conservative for high volatility

targets:
  gate:
    profit_factor: 1.0      # Minimum to save iteration
  champion:
    profit_factor: 1.3      # Triggers walk-forward
  gold:
    profit_factor: 1.8      # Production target

forward_test:
  symbols: ["XAUUSD"]       # Single symbol only
  min_profit_factor: 1.1    # Demo account minimum
  max_drawdown_pct: 20.0    # Forward test limit

walk_forward:
  enabled: true
  n_windows: 6              # 6 rolling windows
  # MIN_PF_PER_WINDOW = 0.8 (easier: was 1.0)
  # MIN_WINDOWS_PASS_PCT = 0.67 (4 of 6: was 0.70)
  # MAX_PF_DEGRADATION = 0.45 (was 0.35)

multi_symbol:
  symbols: ["XAUUSD"]       # XAUUSD only
```

### [core/strategy_config.py](core/strategy_config.py)

**New tiered target flags** in `BacktestResult`:

```python
result.meets_gate      # PF > 1.0, DD < 40%, RF > 0.5, W/L > 1.0
result.meets_champion  # PF > 1.3, DD < 30%, RF > 1.0, W/L > 1.5
result.meets_gold      # PF > 1.8, DD < 20%, RF > 2.0, W/L > 2.0
```

Call `result.check_targets(tier_config)` after parsing.

### [config/trading_rules.yaml](config/trading_rules.yaml)

**IMMUTABLE constraints:**

```yaml
- name: "no_fixed_usd_risk"
  mql5_banned_patterns:
    - "FixedLossUSD"      # V4 failure — always banned
  severity: "CRITICAL"

- name: "min_rr_ratio"
  formula: "take_profit_pips / stop_loss_pips >= 2.0"
  severity: "CRITICAL"
```

All hard rules are encoded in `core/constraint_validator.py` — they are **never relaxed**.

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
| `qwen2.5-coder:14b` | ~9GB | Generate MQL5 code (C++ syntax awareness) |
| `qwen3.5:9b` | ~6GB | Analyze results, propose improvements |

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

## What to do Next

**Immediate:**
1. Run extended hunt: `python scripts/run_multi.py --symbols XAUUSD --iterations 100 --continuous`
2. Monitor dashboard: `streamlit run dashboard.py`
3. Wait for Champion tier result (PF ≥ 1.3) to trigger walk-forward validation

**If hunt succeeds (PF ≥ 1.3):**
1. Walk-forward validation auto-triggers, needs 4/6 windows (PF ≥ 0.8 per window)
2. If WF passes, forward test on demo account for 5+ days
3. If forward test passes (PF ≥ 1.1, DD ≤ 20%), ready for live trading

**Troubleshooting:**
- If no improvements after 50 iterations: check framework diversity, review failed constraints
- If walk-forward fails: strategy is curve-fitted, loop continues trying other configs
- If CrewAI slow: ensure Ollama models are loaded (`ollama ps`)

**Research improvements:**
- Add news filter to avoid high-impact events
- Test different capital levels (scalability)
- Analyze what frameworks perform best in current regime
- Consider parameter cooling schedule (smaller steps as hunt progresses)

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
