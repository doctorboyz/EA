# Project Organization Guide

**Status:** Phase 1 Complete + Files Reorganized for Clarity

---

## 📁 Directory Structure

```
/Users/mac/Desktop/EA/
│
├── 📄 Core Documentation (Read These First)
│   ├── CLAUDE.md                    ⭐ START HERE - Full system guide (400+ lines)
│   ├── README.md                    Quick start & setup instructions
│   ├── TASK_PROGRESS.md             Master timeline (all 5 phases)
│   ├── INDEX.md                     Master file guide (this repository)
│   ├── ORGANIZATION.md              This file - directory structure guide
│
├── 📋 Strategy & Analysis References
│   ├── AUREUS_STRATEGY_PLAN.md       Trading logic & framework
│   ├── AUREUS_INSPECTION_GUIDELINE.md  Backtest metrics & targets
│   ├── PHASE_1_SUMMARY.md            Phase 1 results & tests
│
├── ⚙️ Configuration
│   ├── config/                       YAML configuration files
│   │   ├── system.yaml              (MT5, Ollama, database paths)
│   │   ├── strategy_defaults.yaml   (parameter ranges)
│   │   ├── trading_rules.yaml       (hard constraints)
│   │   └── pairs.yaml               (EURUSD/GBPUSD/USDJPY)
│   │
│   ├── .env.example                  Environment variables template
│   ├── pyproject.toml                Python dependencies
│
├── 🔧 Source Code (Core System)
│   ├── core/                         Core modules
│   │   ├── strategy_config.py       (Pydantic models)
│   │   ├── constraint_validator.py  (Hard rules, anti-V4 guards)
│   │   ├── metrics_calculator.py    (Pure math: PF, DD%, RF, etc.)
│   │   └── __init__.py
│   │
│   ├── agents/                       AI agents
│   │   ├── report_parser.py         ✓ Phase 1: Parses MT5 HTML
│   │   └── __init__.py
│   │
│   ├── templates/                    MQL5 generation templates
│   │   ├── mql5/                     (Jinja2 MQL5 templates - Phase 3)
│   │   └── prompts/                  (LLM system prompts)
│
├── 📝 Strategies & Results
│   ├── strategies/
│   │   ├── baseline/                 (Original V1-V4 EAs - see baseline_and_info/)
│   │   ├── generated/                (LLM-generated .mq5 files - Phase 3+)
│   │   ├── validated/                (Passed constraint validation)
│   │   ├── champion/                 (Current best performer)
│   │   └── archive/                  (Historical versions)
│   │
│   ├── reports/
│   │   ├── raw/                      (MT5 HTML reports - phase 4+)
│   │   ├── parsed/                   (Extracted JSON metrics)
│   │   └── analysis/                 (LLM analysis text)
│
├── 🧪 Testing & Validation
│   ├── tests/
│   │   ├── test_constraint_validator.py  ✓ V4 bug detection tests
│   │   ├── test_report_parser.py        ✓ HTML parsing tests
│   │   ├── fixtures/
│   │   │   ├── V3-sample-report.html   (Real V3 data - see baseline_and_info/)
│   │   │   └── V4-sample-report.html   (Real V4 data - see baseline_and_info/)
│   │   └── __init__.py
│
├── 📚 Database (Phase 2+)
│   └── database/
│       └── migrations/                (Alembic SQL migrations)
│
├── 🚀 Automation Scripts (Phase 4+)
│   └── scripts/
│       ├── run_loop.py               (Main improvement loop)
│       ├── run_single_backtest.py    (Manual backtest)
│       ├── check_ollama.py           (Ollama health check)
│       └── export_results.py         (CSV/Excel export)
│
├── 📖 Logging
│   └── logs/
│       ├── orchestrator.log
│       ├── agent_calls.log
│       └── mt5_bridge.log
│
└── 📦 Baseline & Historical Data
    └── baseline_and_info/            ← ALL BASELINE DATA (See below)
        ├── INDEX.md                  (Complete baseline folder guide)
        │
        ├── 📄 Documentation (Copies for reference)
        │   ├── CLAUDE.md
        │   ├── README.md
        │   ├── TASK_PROGRESS.md
        │   ├── PHASE_1_SUMMARY.md
        │   ├── AUREUS_STRATEGY_PLAN.md
        │   ├── AUREUS_INSPECTION_GUIDELINE.md
        │   └── .env.example
        │
        ├── 🤖 Original Expert Advisors (Never Auto-Modified)
        │   ├── Aureus_H1_Systematic.mq5           (V1 - original)
        │   ├── Aureus_H1_Systematic_v2.mq5        (V2 - original)
        │   ├── Aureus_H1_Systematic_3.mq5         (V3 - baseline ⭐)
        │   └── Aureus_Trend_Hunter_4.mq5          (V4 - failure ❌)
        │
        └── 📊 Backtest Results & Charts
            ├── ReportTester-433288359.html       (V1 reports)
            ├── 1000usdReportTester-*.html
            ├── V2-100usdReportTester-*.html       (V2 reports)
            ├── V2-1000usdReportTester-*.html
            ├── V3-100ReportTester-*.html          (V3 reports)
            ├── V3-1000ReportTester-*.html
            ├── V3-sample-report.html              (Test fixture)
            ├── V4-100.html                        (V4 failure)
            ├── V4-sample-report.html              (Test fixture)
            │
            └── *.png, *.xlsx files                (Equity charts, trade logs)
```

---

## 🎯 Where to Find Things

### "I need to understand the system"
→ Read **[CLAUDE.md](CLAUDE.md)** (start here!)

### "I need quick setup instructions"
→ Read **[README.md](README.md)**

### "I need to see the project timeline"
→ Check **[TASK_PROGRESS.md](TASK_PROGRESS.md)**

### "I need to understand Phase 1 results"
→ Read **[PHASE_1_SUMMARY.md](PHASE_1_SUMMARY.md)**

### "I need to see all baseline files and historical data"
→ Go to **[baseline_and_info/](baseline_and_info/)** folder

### "I need to see the master file index"
→ Read **[INDEX.md](INDEX.md)**

### "I need to study the trading logic"
→ See **[AUREUS_STRATEGY_PLAN.md](AUREUS_STRATEGY_PLAN.md)**

### "I need to know how to evaluate backtests"
→ Check **[AUREUS_INSPECTION_GUIDELINE.md](AUREUS_INSPECTION_GUIDELINE.md)**

### "I need the V3 code to understand the baseline"
→ Find **[baseline_and_info/Aureus_H1_Systematic_3.mq5](baseline_and_info/Aureus_H1_Systematic_3.mq5)**

### "I need to see what V4 failed on"
→ Study **[baseline_and_info/Aureus_Trend_Hunter_4.mq5](baseline_and_info/Aureus_Trend_Hunter_4.mq5)**

### "I need to understand the V4 failure"
→ Read **[baseline_and_info/V4-100.html](baseline_and_info/V4-100.html)** report

---

## 📊 File Organization Principles

### Root Level (Fast Access)
Files in the **root directory** are:
- **Documentation** that you read first
- **Active & frequently referenced**
- **Implementation context** for the current phase
- **Configuration templates**

### baseline_and_info/ (Reference & History)
Files in **baseline_and_info/** are:
- **Original EA source code** (never modified automatically)
- **Historical backtest reports** (for reference)
- **Strategy benchmarks** (V3 = best, V4 = failure case)
- **Complete documentation** (copies of root docs)

---

## 🔄 Workflow: How Files Are Used

### Phase 1: Foundation (COMPLETE ✓)
```
Read: CLAUDE.md, README.md, AUREUS_STRATEGY_PLAN.md
Use: core/ (models, validators), agents/report_parser.py
Test: tests/test_constraint_validator.py, tests/test_report_parser.py
Reference: baseline_and_info/Aureus_H1_Systematic_3.mq5 (V3 baseline)
```

### Phase 2: Database + Analysis (PENDING)
```
Use: config/ (YAML settings)
Create: database/migrations/ (Alembic SQL)
Implement: agents/result_analyzer.py, agents/strategy_improver.py
Reference: baseline_and_info/V3-sample-report.html, V4-100.html
```

### Phase 3: Code Generation (PENDING)
```
Create: templates/mql5/ (Jinja2 MQL5 templates)
Implement: agents/code_generator.py
Reference: baseline_and_info/Aureus_H1_Systematic_3.mq5 (CalculateLotSize)
Output: strategies/generated/
```

### Phase 4: Full Loop (PENDING)
```
Implement: agents/backtest_runner.py, agents/news_filter.py
Create: scripts/run_loop.py (orchestrator)
Output: strategies/champion/, reports/raw/
Reference: TASK_PROGRESS.md (milestones)
```

### Phase 5: Multi-Pair & Optimization (PENDING)
```
Extend: strategies/champion/ (GBPUSD, USDJPY)
Analyze: database/ (correlations)
Export: scripts/export_results.py
Reference: TASK_PROGRESS.md (complete timeline)
```

---

## 📋 Key Files by Purpose

| Purpose | File | Location |
|---|---|---|
| System overview | CLAUDE.md | Root |
| Quick start | README.md | Root |
| Task timeline | TASK_PROGRESS.md | Root |
| Master index | INDEX.md | Root |
| Trading logic | AUREUS_STRATEGY_PLAN.md | Root |
| Metrics targets | AUREUS_INSPECTION_GUIDELINE.md | Root |
| Configuration | config/*.yaml | config/ |
| Models | core/strategy_config.py | core/ |
| Constraints | core/constraint_validator.py | core/ |
| Report parsing | agents/report_parser.py | agents/ |
| V1 source | Aureus_H1_Systematic.mq5 | baseline_and_info/ |
| V2 source | Aureus_H1_Systematic_v2.mq5 | baseline_and_info/ |
| V3 source ⭐ | Aureus_H1_Systematic_3.mq5 | baseline_and_info/ |
| V4 source ❌ | Aureus_Trend_Hunter_4.mq5 | baseline_and_info/ |
| V3 results | V3-sample-report.html | baseline_and_info/ |
| V4 failure | V4-sample-report.html | baseline_and_info/ |

---

## 🧹 Keeping It Clean

### What Changes Frequently (Development)
- `core/` source code
- `agents/` implementations
- `tests/` test files
- `scripts/` automation
- `config/` parameters (tuning)

### What Never Changes (Reference)
- `baseline_and_info/` (original EAs, reports, history)
- Root documentation (only updated at phase completion)

### What Gets Created (Output)
- `strategies/generated/` (new EAs, Phase 3+)
- `strategies/champion/` (best performer, Phase 4+)
- `reports/raw/` (backtest HTML, Phase 4+)
- `database/` (backtest results, Phase 2+)

---

## 🎯 Summary

**Root Directory:** Quick-access active documentation and current work
**baseline_and_info/:** Complete baseline references, historical data, benchmarks

This organization ensures:
- ✓ Fast navigation to system docs (root)
- ✓ Safe preservation of baseline data (baseline_and_info/)
- ✓ Clear separation between active dev and historical reference
- ✓ Easy onboarding (read CLAUDE.md → README.md → dive in)

---

**Last Updated:** After Phase 1 - File Reorganization Complete
**Status:** Ready for Phase 2 Implementation
