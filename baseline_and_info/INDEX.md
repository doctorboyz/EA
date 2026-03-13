# Baseline & Info Folder - Complete Index

**Purpose:** Centralized repository for all baseline EAs, documentation, and reference information.

**Location:** `/Users/mac/Desktop/EA/baseline_and_info/`

---

## 📚 Documentation Files

### System Documentation

| File | Size | Purpose |
|---|---|---|
| [CLAUDE.md](CLAUDE.md) | 15 KB | **START HERE** — Complete system documentation (400+ lines) |
| [README.md](README.md) | 6.7 KB | Quick start guide, setup instructions |
| [PHASE_1_SUMMARY.md](PHASE_1_SUMMARY.md) | 11 KB | Phase 1 completion report and test results |
| [TASK_PROGRESS.md](TASK_PROGRESS.md) | 11 KB | Master task tracker (all phases, milestones, timeline) |

### Strategy Documentation

| File | Size | Purpose |
|---|---|---|
| [AUREUS_STRATEGY_PLAN.md](AUREUS_STRATEGY_PLAN.md) | 1.2 KB | Strategy overview: 3.0 Sniper-Trend Framework |
| [AUREUS_INSPECTION_GUIDELINE.md](AUREUS_INSPECTION_GUIDELINE.md) | 1.4 KB | Target metrics and backtest analysis guidelines |

### Configuration

| File | Size | Purpose |
|---|---|---|
| [.env.example](.env.example) | — | Template for environment variables |

---

## 🤖 Baseline Expert Advisors (Never Auto-Modified)

### V1: Aureus_H1_Systematic (Original)

| File | Size | Status |
|---|---|---|
| [Aureus_H1_Systematic.mq5](Aureus_H1_Systematic.mq5) | 8.1 KB | ✓ Original V1 |

**Characteristics:**
- Pure RSI 30/70 at 5-day structural highs/lows
- No trend filter (trades both directions)
- Risk: 1.0% per trade

**Results (Jan-Mar 2026):**
- Net Profit: +$7.22 (on $100)
- Profit Factor: 1.24 ✓ (closest to target)
- Max DD: 8.92% ✓ (below 15% target)
- Trades: 37

---

### V2: Aureus_H1_Systematic_v2

| File | Size | Status |
|---|---|---|
| [Aureus_H1_Systematic_v2.mq5](Aureus_H1_Systematic_v2.mq5) | 9.3 KB | ✓ Original V2 |

**Characteristics:**
- Added ATR 14 volatility filter
- Still no trend filter
- Same RSI logic as V1

**Results (Jan-Mar 2026):**
- Net Profit: -$34.58 (on $100)
- Profit Factor: 0.49 (worse than V1)
- Reason: ATR filter without trend alignment = undertrading

---

### V3: Aureus_H1_Systematic_3 ⭐ BEST PERFORMER

| File | Size | Status |
|---|---|---|
| [Aureus_H1_Systematic_3.mq5](Aureus_H1_Systematic_3.mq5) | 10 KB | ⭐ **BASELINE TO BEAT** |

**Characteristics:**
- **EMA 200** (H1) — Trend filter (buy above, sell below)
- **RSI 14** (30/70) — Mean reversion entry
- **ATR 14** — Volatility filter
- **5-day structure** — Precision entry timing
- **1% risk** (percentage-based, not fixed USD)

**Results (Jan-Mar 2026, 11 weeks):**
- ✓ Profit Factor: **1.24** (closest to target > 1.5)
- ✓ Max Drawdown: **8.92%** (below target < 15%)
- ✗ Recovery Factor: 0.77 (below target > 3.0)
- ✗ Win/Loss Ratio: 0.87 (below target > 2.0)
- Total Trades: 74
- Win Rate: 43%
- Net Profit: +$7.22 (on $100)

**V3 Philosophy:**
> "Precision beats power. Timing beats speed."
> — Aureus Trading Team, 2026

---

### V4: Aureus_Trend_Hunter_4 ❌ FAILURE

| File | Size | Status |
|---|---|---|
| [Aureus_Trend_Hunter_4.mq5](Aureus_Trend_Hunter_4.mq5) | 6.2 KB | ❌ **BLOWN ACCOUNT** |

**Characteristics:**
- Added ADX 14 trend strength filter
- Added H4 EMA 50 multi-timeframe filter
- Fixed $10 loss (instead of %)
- Wider SL (40 pips), wider TP (120 pips)

**Results (Jan 2025 - Mar 2026, 14 months):**
- ❌ Profit Factor: 0.64 (losing system)
- ❌ Max Drawdown: **101.71%** (ACCOUNT BLOWN)
- ❌ Net Profit: -$100.05 (total wipeout)
- Reason: **FixedLossUSD = 10.0 on $100 = 10% risk per trade**

**V4 Failure Pattern:**
```
Trade 1 Loss: $100 - $10 = $90 (10% loss)
Trade 2 Loss: $90 - $9 = $81 (9% of remaining)
Trade 3 Loss: $81 - $8 = $73 (8% of remaining)
Trade 4 Loss: $73 - $7 = $66 (7% of remaining)
→ Repeated consecutive losses → Margin call → Blown account
```

**Guard:** ConstraintValidator bans "FixedLossUSD" pattern

---

## 📊 Backtest Reports (Real Data)

### V3 Report (Best Performer)

| File | Size | Format | Status |
|---|---|---|---|
| [V3-sample-report.html](V3-sample-report.html) | 95 KB | MT5 HTML (UTF-16 LE) | ✓ Parsed successfully |

**Extracted Metrics:**
- Symbol: EURUSD
- Timeframe: H1
- Period: Jan-Mar 2026
- Bars: 4,617
- Ticks Modeled: 13.7M
- **Profit Factor: 1.24**
- **Max DD: 9.33%**
- Total Trades: 74
- Win Rate: 43%

**Notes:**
- Actual V3 EA (`Aureus_H1_Systematic_3.mq5`)
- Real MT5 Strategy Tester output
- Used for test fixtures in Phase 1

---

### V4 Report (Catastrophic Failure)

| File | Size | Format | Status |
|---|---|---|---|
| [V4-sample-report.html](V4-sample-report.html) | 100 KB | MT5 HTML (UTF-16 LE) | ✓ Parsed successfully |

**Extracted Metrics:**
- Symbol: EURUSD
- Timeframe: H1
- Period: Jan 2025 - Mar 2026 (14 months)
- Bars: 4,617
- Ticks: 13.7M
- **Profit Factor: 0.64**
- **Max DD: 107.97%** ← BLOWN
- **Net Profit: -$100.05** ← Total loss
- Total Trades: 40
- Win Rate: 42.5%

**Notes:**
- V4 EA: `Aureus_Trend_Hunter_4.mq5`
- FixedLossUSD = 10.0 on $100 account
- Shows exact failure pattern
- Used to verify ConstraintValidator works

---

## 🎯 Key Comparisons

### V3 vs V4 Head-to-Head

| Metric | V3 (11 weeks) | V4 (14 months) | Target | Winner |
|---|---|---|---|---|
| **Profit Factor** | 1.24 | 0.64 | > 1.5 | V3 ✓ |
| **Max Drawdown %** | 8.92% | 101.71% | < 15% | V3 ✓ |
| **Recovery Factor** | 0.77 | -0.93 | > 3.0 | V3 ✓ |
| **Win/Loss Ratio** | 0.87 | 0.87 | > 2.0 | Tie |
| **Net Profit** | +$7.22 | -$100.05 | > 0 | V3 ✓ |
| **Trade Count** | 74 | 40 | High | V3 ✓ |
| **Status** | Working | Broken | Improvement | V3 ✓ |

**Conclusion:** V3 is significantly better than V4. V3 is the baseline to improve from.

---

## 📈 Improvement Targets

**Starting Point:** V3 (PF 1.24)
**Targets:**

| Metric | Current (V3) | Target | Improvement Needed |
|---|---|---|---|
| Profit Factor | 1.24 | > 1.5 | +21% |
| Max Drawdown % | 8.92% | < 15% | ✓ Already met |
| Recovery Factor | 0.77 | > 3.0 | +290% |
| Win/Loss Ratio | 0.87 | > 2.0 | +130% |

**Challenge:** V3 meets 1 of 4 targets. AI system must improve PF by 21%, RF by 290%, and Win/Loss by 130%.

---

## 🔒 Hard Constraints (From System)

These rules are **IMMUTABLE** and encoded in the AI system:

1. ✓ **No FixedLossUSD** — Bans the V4 bug pattern
2. ✓ **Max 2% Risk** — risk_percent ≤ 2.0%
3. ✓ **Min 2:1 R/R** — take_profit / stop_loss ≥ 2.0
4. ✓ **Min 20 pip SL** — Broker spread eats tighter
5. ✓ **RSI Thresholds** — oversold ≤ 35, overbought ≥ 65
6. ✓ **Breakeven < TP** — Logical sanity
7. ✓ **EMA ≥ 150 period** — Avoid H1 noise
8. ✓ **Spread 1-3 pips** — Exness typical range

See `CLAUDE.md` for philosophy on why these cannot be relaxed.

---

## 🛠 How to Use These Files

### For Reference
```bash
# Read documentation
cat CLAUDE.md                    # Full system guide
cat README.md                    # Quick start
cat TASK_PROGRESS.md             # Master timeline

# Check strategy documents
cat AUREUS_STRATEGY_PLAN.md      # Trading logic
cat AUREUS_INSPECTION_GUIDELINE.md  # Metrics to check
```

### For Testing (Phase 1)
```bash
# The HTML reports are used as test fixtures
# Located at: /Users/mac/Desktop/EA/tests/fixtures/
# - V3-sample-report.html (best performer, PF 1.24)
# - V4-sample-report.html (blown account, DD 101.71%)

# ReportParser successfully extracts metrics from these
python tests/test_report_parser.py
```

### For Strategy Generation (Phase 3+)
```bash
# V3 MQL5 code serves as reference for Jinja2 templates
# Location: strategies/baseline/Aureus_H1_Systematic_3.mq5

# Specifically, the CalculateLotSize() function shows
# correct percentage-based risk model to replicate
```

### For Improvement Loop (Phase 4+)
```bash
# When AI generates new strategies, it must:
# 1. Follow the trading logic from V3 (EMA+RSI+ATR)
# 2. Use percentage risk (never FixedLossUSD like V4)
# 3. Meet all hard constraints
# 4. Target improving PF 1.24 → 1.5+

# Generated strategies are tested and compared against
# V3 baseline metrics from this folder
```

---

## 📋 File Manifest

| File | Type | Lines | Status |
|---|---|---|---|
| CLAUDE.md | Markdown | 400+ | Documentation |
| README.md | Markdown | 250+ | Documentation |
| PHASE_1_SUMMARY.md | Markdown | 350+ | Documentation |
| TASK_PROGRESS.md | Markdown | 400+ | Documentation |
| AUREUS_STRATEGY_PLAN.md | Markdown | 30 | Reference |
| AUREUS_INSPECTION_GUIDELINE.md | Markdown | 42 | Reference |
| .env.example | Config | 20 | Template |
| Aureus_H1_Systematic.mq5 | MQL5 | 280+ | Original V1 |
| Aureus_H1_Systematic_v2.mq5 | MQL5 | 300+ | Original V2 |
| Aureus_H1_Systematic_3.mq5 | MQL5 | 320+ | Original V3 ⭐ |
| Aureus_Trend_Hunter_4.mq5 | MQL5 | 250+ | Original V4 ❌ |
| V3-sample-report.html | HTML | Large | Test Fixture |
| V4-sample-report.html | HTML | Large | Test Fixture |

---

## 🚀 Quick Navigation

**Need to understand the system?**
→ Start with [CLAUDE.md](CLAUDE.md)

**Need quick setup instructions?**
→ Read [README.md](README.md)

**Need to see Phase 1 results?**
→ Check [PHASE_1_SUMMARY.md](PHASE_1_SUMMARY.md)

**Need to see task timeline?**
→ Review [TASK_PROGRESS.md](TASK_PROGRESS.md)

**Need the trading logic?**
→ See [AUREUS_STRATEGY_PLAN.md](AUREUS_STRATEGY_PLAN.md)

**Need to know how to evaluate results?**
→ Consult [AUREUS_INSPECTION_GUIDELINE.md](AUREUS_INSPECTION_GUIDELINE.md)

**Need the baseline code?**
→ Study [Aureus_H1_Systematic_3.mq5](Aureus_H1_Systematic_3.mq5) (V3 — best)

**Need to understand failures?**
→ Analyze [Aureus_Trend_Hunter_4.mq5](Aureus_Trend_Hunter_4.mq5) (V4 — blown account)

---

## 📝 Notes

- **All baseline EAs are original versions** — Never auto-modified by the system
- **HTML reports are UTF-16 LE encoded** — Not UTF-8
- **V3 is the target baseline** — 14 months untested, but best performer in short window
- **V4 failure is documented and guarded** — ConstraintValidator prevents FixedLossUSD
- **All documentation is complete** — Ready for Phase 2 implementation

---

**Last Updated:** Phase 1 Complete (March 13, 2026)
**Status:** Ready for Phase 2 (Database + Ollama Integration)

For implementation progress, see [TASK_PROGRESS.md](TASK_PROGRESS.md)
