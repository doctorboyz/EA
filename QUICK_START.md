# Quick Start Guide - Aureus AI Trading Bot

**Phase:** 1 (Foundation) ✓ COMPLETE
**Status:** Ready for Phase 2

---

## 📖 Read This First (in order)

1. **[CLAUDE.md](CLAUDE.md)** (400+ lines) — Complete system guide
2. **[README.md](README.md)** — Setup & installation
3. **[ORGANIZATION.md](ORGANIZATION.md)** — File structure guide
4. **[TASK_PROGRESS.md](TASK_PROGRESS.md)** — Timeline for all phases

**Time:** ~30 min to understand the full system

---

## 🎯 What This Project Does

1. **Analyzes** your trading strategy (Aureus 3.0 - EMA200 + RSI + ATR)
2. **Tests** strategies via MetaTrader 5 backtests
3. **Learns** what works and what doesn't using AI (Ollama)
4. **Improves** parameters automatically in a loop
5. **Generates** new trading code and re-tests

**Goal:** Find strategy parameters that hit:
- Profit Factor > 1.5
- Max Drawdown < 15%
- Recovery Factor > 3.0
- Win/Loss Ratio > 2.0

**Baseline:** V3 (PF 1.24, DD 8.92%) — best performer so far

---

## 🚀 Phase 1: Foundation (Done ✓)

### What Was Built
- ✓ Pydantic models for strategy configuration
- ✓ Hard constraint validator (guards against V4's 10% risk bug)
- ✓ MT5 report parser (reads UTF-16 HTML)
- ✓ Configuration system (YAML files)
- ✓ Unit tests (V4 bug detection proven)

### Test It
```bash
# Parse real MT5 reports
python tests/test_report_parser.py
# Output: ✓ V3 parsed: PF=1.24, DD=9.33%

# Test constraints
python -m pytest tests/test_constraint_validator.py -v
# Output: ✓ V3 config passes, ✓ FixedLossUSD rejected
```

### Key Files
- `CLAUDE.md` — Full documentation
- `core/strategy_config.py` — Pydantic models
- `core/constraint_validator.py` — Hard rules
- `agents/report_parser.py` — HTML parser
- `config/trading_rules.yaml` — Immutable constraints

---

## 🔒 Critical: The V4 Bug (and How We Guard It)

**V4 Failed:** 10% risk per trade on $100 account
```
FixedLossUSD = 10.0
Initial Balance = $100
Risk = $10 / $100 = 10% per trade
→ 4 consecutive losses → $65.61 balance (65% loss)
→ Continued losses → margin call → blown account
```

**Our Guard:** ConstraintValidator bans `FixedLossUSD` pattern
- Any generated code with this word is **REJECTED**
- Never allowed to execute
- Enforced automatically in Phase 3+

---

## 📁 File Organization

### Root (Read These First)
```
CLAUDE.md               ← System documentation
README.md               ← Quick setup
TASK_PROGRESS.md        ← Master timeline
ORGANIZATION.md         ← File structure guide
INDEX.md                ← Master file index
```

### Core System
```
core/                   ← Models, validators, calculators
agents/                 ← AI agents (report parser ✓)
config/                 ← YAML configuration
templates/              ← MQL5 generation templates (Phase 3)
```

### Baseline & Reference
```
baseline_and_info/      ← All baseline EAs, reports, history
  ├── Aureus_H1_Systematic_3.mq5   (V3 baseline ⭐)
  ├── Aureus_Trend_Hunter_4.mq5    (V4 failure ❌)
  ├── V3-sample-report.html         (test fixture)
  └── V4-sample-report.html         (test fixture)
```

---

## 🎯 Next Steps (Phase 2)

**Phase 2 Goal:** Database + LLM Analysis

1. **Set up PostgreSQL**
   ```bash
   createdb aureus
   ```

2. **Create Alembic migrations**
   ```bash
   alembic upgrade head
   ```

3. **Implement agents:**
   - OllamaClient (retry, timeout, structured output)
   - ResultAnalyzerAgent (identify weaknesses via llama3.2:3b)
   - StrategyImproverAgent (propose parameter changes)

4. **Store all results in database**
   - Strategies table (JSONB config)
   - Backtest runs table (all metrics)
   - Analyses table (LLM outputs)

---

## 💻 Development Setup

### Install Dependencies
```bash
pip install -r requirements.txt  # From pyproject.toml
```

### Run Tests
```bash
python -m pytest tests/ -v
```

### Parse Real Backtest
```bash
python -c "
from agents.report_parser import ReportParser
result = ReportParser.parse('baseline_and_info/V3-sample-report.html')
print(f'PF={result.profit_factor}, DD={result.max_drawdown_pct}%')
"
```

### Check V3 Config Validation
```bash
python -c "
from core.strategy_config import StrategyConfig, StrategyVersion
from core.constraint_validator import ConstraintValidator

config = StrategyConfig(version=StrategyVersion(major=0, minor=3, iteration=0))
is_valid, violations = ConstraintValidator.validate_config(config)
print(f'V3 Config Valid: {is_valid}')
"
```

---

## 📊 Key Metrics at a Glance

### V3 Baseline (Working)
| Metric | Value | Target | Status |
|---|---|---|---|
| Profit Factor | 1.24 | > 1.5 | ⚠️ Close |
| Max Drawdown | 8.92% | < 15% | ✓ Pass |
| Recovery Factor | 0.77 | > 3.0 | ✗ Fail |
| Win/Loss Ratio | 0.87 | > 2.0 | ✗ Fail |

### V4 Failure (Blown Account)
| Metric | Value | Status |
|---|---|---|
| Profit Factor | 0.64 | ✗ Losing |
| Max Drawdown | 101.71% | ✗ BLOWN |
| Cause | FixedLossUSD = 10.0 = 10% risk | ✗ FORBIDDEN |

---

## 🔧 Hard Constraints (Never Relax)

These rules are **IMMUTABLE** in the system:

1. ✓ **No FixedLossUSD** — Only percentage-based risk allowed
2. ✓ **Max 2% Risk** — Never > 2.0% per trade
3. ✓ **Min 2:1 R/R** — Take Profit ≥ 2 × Stop Loss
4. ✓ **Min 20 pip SL** — Broker spread eats tighter
5. ✓ **RSI Bounds** — oversold ≤ 35, overbought ≥ 65
6. ✓ **Breakeven < TP** — Logical sanity
7. ✓ **EMA ≥ 150** — Avoid H1 noise
8. ✓ **Spread 1-3 pips** — Exness typical range

See `config/trading_rules.yaml` for full details.

---

## 🎮 Ollama Models Needed (Phase 2+)

```bash
# Install Ollama from https://ollama.ai
ollama pull qwen2.5-coder:7b      # MQL5 code generation (~5GB)
ollama pull llama3.2:3b            # Result analysis (~2.5GB)
ollama serve                        # Runs on http://localhost:11434
```

---

## 📚 Documentation Map

| Need | File |
|---|---|
| System overview | CLAUDE.md |
| Setup & installation | README.md |
| Trading logic | AUREUS_STRATEGY_PLAN.md |
| Backtest metrics | AUREUS_INSPECTION_GUIDELINE.md |
| Project timeline | TASK_PROGRESS.md |
| File organization | ORGANIZATION.md |
| Master index | INDEX.md |
| Phase 1 results | PHASE_1_SUMMARY.md |
| Baseline data | baseline_and_info/INDEX.md |

---

## ❓ Common Questions

**Q: Why did V4 fail?**
A: FixedLossUSD = 10.0 on $100 = 10% risk per trade. System guards against this.

**Q: What's the baseline to beat?**
A: V3 (Profit Factor 1.24, DD 8.92%). It's the best performer so far.

**Q: What are the target metrics?**
A: PF > 1.5, DD < 15%, RF > 3.0, Win/Loss > 2.0. V3 meets 1 of 4.

**Q: Can I relax the hard constraints?**
A: No. They're designed to prevent failures like V4.

**Q: When does the improvement loop start?**
A: Phase 4 (after database + LLM analysis in Phase 2 & 3).

**Q: How do I understand the code?**
A: Read CLAUDE.md (system overview), then explore core/ and agents/.

---

## ✅ Phase 1 Checklist

- ✓ Project structure created
- ✓ Core models implemented (Pydantic)
- ✓ Constraint validator working (V4 bug detection)
- ✓ Report parser tested on real files
- ✓ Configuration system in place
- ✓ Unit tests passing
- ✓ Documentation complete
- ✓ Files organized (root + baseline_and_info/)

**Status:** Ready for Phase 2 🚀

---

## 🎯 One-Minute Overview

```
Aureus = AI trading bot system
├── Reads your trading strategy (Aureus 3.0)
├── Tests it via MetaTrader 5 backtests
├── Analyzes results with AI (Ollama)
├── Improves parameters in a loop
└── Finds better strategy

Current Status:
├── Phase 1: Foundation ✓ DONE
├── Phase 2: Database + LLM (PENDING)
├── Phase 3: Code Generation (PENDING)
├── Phase 4: Improvement Loop (PENDING)
└── Phase 5: Multi-Pair (PENDING)

Baseline: V3 (PF 1.24, DD 8.92%) → Goal: PF > 1.5, DD < 15%, RF > 3.0

Guard: V4's 10% risk bug forever blocked by constraints
```

---

**Time to Understand:** 30 minutes
**Files to Read:** CLAUDE.md, README.md, ORGANIZATION.md
**Status:** Phase 1 Complete, Ready for Phase 2

👉 **Start here:** [CLAUDE.md](CLAUDE.md)
