# baseline_and_info/ - Baseline & Historical Data Index

**Purpose:** Reference data and original baseline Expert Advisors

**For active documentation, see root:** `/Users/mac/Desktop/EA/`

---

## 📁 Contents

### 🤖 Original Expert Advisors (Never Auto-Modified)

| File | Size | Version | Status | Performance |
|---|---|---|---|---|
| [Aureus_H1_Systematic.mq5](Aureus_H1_Systematic.mq5) | 8.1 KB | V1 | Original | PF 1.24, DD 8.92% |
| [Aureus_H1_Systematic_v2.mq5](Aureus_H1_Systematic_v2.mq5) | 9.3 KB | V2 | Original | PF 0.49, DD 44% |
| [Aureus_H1_Systematic_3.mq5](Aureus_H1_Systematic_3.mq5) | 10 KB | V3 ⭐ | **BASELINE** | **PF 1.24, DD 8.92%** |
| [Aureus_Trend_Hunter_4.mq5](Aureus_Trend_Hunter_4.mq5) | 6.2 KB | V4 ❌ | **FAILURE** | **PF 0.64, DD 101.71%** |

---

## 📊 Backtest Reports & Charts

### V1 Reports
- `ReportTester-433288359.html` (backtest report)
- `ReportTester-433288359.xlsx` (trade log)
- `ReportTester-433288359*.png` (equity charts)
- `1000usdReportTester-433288359.html` (on $1,000)
- `1000usdReportTester-433288359*.png` (charts)

### V2 Reports
- `V2-100usdReportTester-433288359.html`
- `V2-1000usdReportTester-433288359.html`
- `V2-100usdReportTester-*.png`, `V2-1000usdReportTester-*.png`

### V3 Reports
- `V3-100ReportTester-433288359.html`
- `V3-1000ReportTester-433288359.html`
- `V3-100ReportTester-*.png`, `V3-1000ReportTester-*.png`
- `V3-sample-report.html` (test fixture for Phase 1)

### V4 Reports
- `V4-100.html` (blown account: PF 0.64, DD 101.71%)
- `V4-100*.png` (equity charts)
- `V4-sample-report.html` (test fixture for Phase 1)

---

## 📖 How to Use This Folder

### For Code Reference
Study the baseline EAs to understand the original trading logic:
```
V1: Pure RSI entry at structural extremes (no trend filter)
V2: V1 + ATR volatility filter (still no trend)
V3: V2 + EMA200 trend filter (WORKING BASELINE)
V4: V3 + ADX + H4 MTF filters (TOO RESTRICTIVE - FAILURE)
```

### For Backtest Analysis
Compare your generated strategies against these benchmarks:
- **V3** is the target to beat (PF 1.24, DD 8.92%)
- **V4** is a failure case study (shows what NOT to do)

### For Test Fixtures
The HTML reports are parsed by the testing system:
- `V3-sample-report.html` → test_report_parser.py ✓ PASSES
- `V4-sample-report.html` → test_report_parser.py ✓ PASSES

---

## 🎯 Key Metrics Summary

| EA | Period | PF | DD% | RF | Win% | Status |
|---|---|---|---|---|---|---|
| **V1** | Jan-Mar 2026 | 1.24 ✓ | 8.92% ✓ | 0.77 | 43% | Working |
| **V2** | Jan-Mar 2026 | 0.49 | 44.4% | -0.71 | 37% | Failing |
| **V3** ⭐ | Jan-Mar 2026 | 1.24 ✓ | 8.92% ✓ | 0.77 | 43% | **BASELINE** |
| **V4** ❌ | Jan 2025-Mar 2026 | 0.64 | 101.71% ❌ | -0.93 | 42% | **BLOWN** |

---

## ⚠️ V4 Failure Analysis

**Root Cause:** `FixedLossUSD = 10.0` on $100 account = 10% per trade

**Pattern:**
```
Trade 1 Loss: $100 - $10 = $90 (10% loss)
Trade 2 Loss: $90 - $9 = $81 (9% of remaining)
Trade 3 Loss: $81 - $8 = $73 (8% of remaining)
...repeated losses...
Margin Call → Account Blown (DD 101.71%)
```

**Guard:** ConstraintValidator in root system bans `FixedLossUSD` pattern.

---

## 📚 Documentation Location

**All active documentation has been moved to the root directory:**

| Document | Location | Purpose |
|---|---|---|
| **CLAUDE.md** | `/root/` | ⭐ Complete system guide |
| **README.md** | `/root/` | Setup & quick start |
| **QUICK_START.md** | `/root/` | 30-minute orientation |
| **TASK_PROGRESS.md** | `/root/` | Master timeline |
| **ORGANIZATION.md** | `/root/` | File structure guide |
| **INDEX.md** | `/root/` | Master file index |
| **AUREUS_STRATEGY_PLAN.md** | `/root/` | Trading logic |
| **AUREUS_INSPECTION_GUIDELINE.md** | `/root/` | Backtest metrics |
| **PHASE_1_SUMMARY.md** | `/root/` | Phase 1 results |

See `/root/ORGANIZATION.md` for complete project structure.

---

## 🚀 Why This Organization

**Root Directory:** Active documentation, configuration, source code
- Fast access to what you need to read and implement
- Changes frequently during development

**baseline_and_info/:** Historical reference data
- Original EA files (never auto-modified)
- All backtest reports (for comparison)
- Benchmark data (what to beat)
- Stable and unchanged

---

## 📊 File Inventory

### Original EAs
- ✓ 4 MQL5 files (V1-V4, originals preserved)

### Backtest Data
- ✓ ~20 HTML reports (V1-V4 results)
- ✓ ~20 PNG files (equity charts)
- ✓ 6 XLSX files (trade logs)

### Metadata
- ✓ This INDEX.md (folder guide)

---

## Next Steps

To understand the system:
1. Read `/root/CLAUDE.md` (system overview)
2. Read `/root/QUICK_START.md` (30-minute guide)
3. Read `/root/ORGANIZATION.md` (file structure)
4. Reference this folder for baseline EAs and backtest data

To study the baselines:
- Start with `Aureus_H1_Systematic_3.mq5` (V3 - the working one)
- Compare with `Aureus_Trend_Hunter_4.mq5` (V4 - the failure)
- Review backtest reports to understand performance patterns

---

**Status:** Phase 1 Complete, Ready for Phase 2
**Last Updated:** After consolidation (duplicates removed)

For full project context, see **[/root/INDEX.md](/root/INDEX.md)**
