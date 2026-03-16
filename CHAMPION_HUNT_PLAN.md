# Champion Hunt System — Keep Improving Until Winner Found

## Current Problem
- Loop stops after `--iterations N` even if no champion found
- Only tweaks parameters (gradient search) → gets stuck locally
- No memory of what worked → repeats failures
- No framework switching → uses same strategy type forever

---

## Solution: 4-Phase Progressive Hunt

### Phase 1: Infinite Mode (READY NOW)
```bash
# Never stops until champion found (or timeout)
python scripts/run_multi.py \
  --continuous \
  --until-champion \
  --max-hours 48 \
  --iterations 10        # per cycle, not total
```

**Changes needed:**
1. Add `--until-champion` + `--max-hours` flags to `run_multi.py`
2. Modify `MultiSymbolOrchestrator` outer loop to check: `while time_elapsed < max_hours and not all_champions_found`
3. Log progress: "Iteration 47 | Best PF: 1.42 | Time: 12h 34m | Est. time to champion: 24h"
4. Dashboard shows: "🔍 HUNTING... 47 iters, best PF 1.42" badge

**Code:**
```python
# run_multi.py
parser.add_argument("--until-champion", action="store_true",
                    help="Keep hunting forever until champion found")
parser.add_argument("--max-hours", type=int, default=72,
                    help="Max hunting time (hours)")

# MultiSymbolOrchestrator
start_time = time.time()
max_seconds = args.max_hours * 3600
cycle = 0

while time.time() - start_time < max_seconds:
    cycle += 1
    logger.info(f"🔍 HUNT CYCLE {cycle}")
    # Run one cycle per symbol
    # Check if all champions found → break
    if all(symbol in self.champions_found for symbol in self.symbols):
        break
```

---

### Phase 2: Framework Generation (NEW)
Instead of parameter tweaking, **generate different strategies**:

**Framework Types:**
```
1. TrendFollowing      — Long on uptrend, short on downtrend (EMA-based)
2. MeanReversion       — Buy oversold, sell overbought (RSI-based)
3. Breakout            — Enter on channel breakout (ATR-based)
4. GridTrading         — Place buys/sells in grid intervals
5. SniperEntry         — Wait for perfect PA pattern, 1 trade per day
6. CandlePattern       — Pin bars, engulfing, hammer (PA recognition)
7. IchimokuCloud       — Kijun cross with cloud filtering
8. MultiTimeframe      — Enter on H4 signal, exit on M15 reversal
```

**Implementation:**
```python
# agents/code_generator.py
class CodeGeneratorAgent:
    def __init__(self):
        self.frameworks = [
            "TrendFollowing", "MeanReversion", "Breakout",
            "GridTrading", "SniperEntry", "CandlePattern"
        ]

    async def generate(self, config, framework=None):
        """Generate code for a specific framework type."""
        if framework is None:
            # Intelligent selection: pick based on market regime
            framework = self._pick_framework_for_regime()

        # Load template for this framework
        template = f"templates/mql5/frameworks/{framework}.mq5.jinja2"
        # Render with config parameters
```

**Templates:**
```
templates/mql5/frameworks/
├── TrendFollowing.mq5.jinja2
├── MeanReversion.mq5.jinja2
├── Breakout.mq5.jinja2
├── GridTrading.mq5.jinja2
└── SniperEntry.mq5.jinja2
```

Each template has different parameter set:
- **TrendFollowing**: ema_fast, ema_slow, trail_pips
- **MeanReversion**: rsi_oversold, rsi_overbought, tp_pips
- **Breakout**: atr_multiplier, lookback_bars, grid_size
- **GridTrading**: grid_level_spacing, max_levels, lot_multiplier
- **SniperEntry**: pattern_type, entry_confirmation, daily_trade_limit

**Rotation Logic:**
```python
# agents/orchestrator.py
iteration_frameworks = [
    "TrendFollowing",   # Iterations 1-10
    "MeanReversion",    # Iterations 11-20
    "Breakout",         # Iterations 21-30
    "GridTrading",      # Iterations 31-40
    "SniperEntry",      # Iterations 41-50
]

framework = iteration_frameworks[(iteration // 10) % len(iteration_frameworks)]
mq5_code = await self.code_gen.generate(config, framework=framework)
```

---

### Phase 3: Experience Database (NEW)
Track what works, avoid repeating failures:

**New Tables:**
```sql
-- What framework+parameters worked in what market condition
CREATE TABLE framework_experiments (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10),
    timeframe VARCHAR(10),
    framework_type VARCHAR(50),      -- TrendFollowing, MeanReversion, etc
    parameter_set JSONB,             -- {ema_fast: 50, ema_slow: 200, ...}
    profit_factor FLOAT,
    max_drawdown_pct FLOAT,
    meets_all_targets BOOLEAN,
    market_regime VARCHAR(20),       -- trending, choppy, ranging, volatile
    tested_at TIMESTAMP
);

-- Aggregate patterns
CREATE TABLE framework_performance (
    symbol VARCHAR(10),
    framework_type VARCHAR(50),
    trending_market_pf FLOAT,        -- avg PF when market was trending
    choppy_market_pf FLOAT,
    success_rate_pct FLOAT,          -- % of attempts that met targets
    recommended BOOLEAN              -- should we try this framework
);

-- Market regime detection
CREATE TABLE market_snapshots (
    symbol VARCHAR(10),
    timeframe VARCHAR(10),
    atr FLOAT,                       -- volatility
    adx FLOAT,                       -- trend strength
    regime VARCHAR(20),              -- trending, choppy, ranging
    best_framework VARCHAR(50),      -- historically best framework for this regime
    timestamp TIMESTAMP
);
```

**Learning Queries:**
```python
# Before generating next framework, query database:
SELECT best_framework FROM market_snapshots
WHERE symbol='EURUSD' AND regime='trending'
ORDER BY timestamp DESC LIMIT 1;
# → Try TrendFollowing if market is trending

SELECT * FROM framework_performance
WHERE symbol='EURUSD' AND success_rate_pct > 30
ORDER BY success_rate_pct DESC;
# → List frameworks with >30% success rate, pick top one
```

---

### Phase 4: Adaptive Strategy Selection (FUTURE)
```python
# agents/orchestrator.py
async def _pick_next_framework(self):
    """Pick framework based on past success + current market regime."""

    # 1. Detect current regime
    regime = await self._detect_market_regime()  # trending, choppy, etc

    # 2. Query database: best frameworks for this regime
    best = db.query(FrameworkPerformance)\
        .filter(symbol=self.symbol, regime=regime)\
        .order_by(FrameworkPerformance.success_rate_pct.desc())\
        .limit(5)

    # 3. Apply exploration/exploitation
    if random.random() < 0.2:  # 20% explore
        return random.choice(all_frameworks)
    else:  # 80% exploit
        return best[0].framework_type

async def _detect_market_regime(self):
    """Analyze recent bars to classify market."""
    recent_atr = calculate_atr(lookback=20)
    recent_adx = calculate_adx(lookback=14)

    if recent_adx > 25:
        return "trending"
    elif recent_atr > recent_atr_avg * 1.5:
        return "volatile"
    else:
        return "choppy"
```

---

## Implementation Order

### Week 1: Phase 1 (Infinite Mode)
- [ ] Add `--until-champion` + `--max-hours` to `run_multi.py`
- [ ] Update `MultiSymbolOrchestrator` loop logic
- [ ] Add hunting progress log
- [ ] Dashboard badge: "🔍 HUNTING" state

### Week 2: Phase 2 (Frameworks)
- [ ] Create 6 framework templates (MQL5 Jinja2)
- [ ] Modify `CodeGeneratorAgent.generate()` to accept framework param
- [ ] Implement framework rotation in `OrchestratorAgent`
- [ ] Test each framework works

### Week 3: Phase 3 (Experience DB)
- [ ] Create 3 new tables
- [ ] Add insert logic after each backtest
- [ ] Implement query helpers
- [ ] Backfill with existing test results

### Week 4: Phase 4 (Adaptive)
- [ ] Market regime detector
- [ ] Intelligent framework picker
- [ ] A/B test: random rotation vs adaptive

---

## Expected Results

**Current (Fixed Parameters):**
```
Iteration 50, best PF: 1.24, cycles to champion: ∞
```

**With Phase 1+2 (Infinite + Frameworks):**
```
Iteration 18: TrendFollowing, PF 0.98
Iteration 28: MeanReversion, PF 1.41 ← getting close
Iteration 38: Breakout, PF 1.52 ✅ CHAMPION!
Time to champion: ~2 hours
```

**With Phase 3+4 (Learning + Adaptive):**
```
Market regime detected: CHOPPY (ADX=18, ATR=0.45)
Querying best frameworks for choppy...
→ MeanReversion (75% success)
→ GridTrading (68% success)
Pick: MeanReversion
Iteration 8: MeanReversion, PF 1.53 ✅ CHAMPION!
Time to champion: ~30 minutes
```

---

## Code Pointers

**Files to modify:**
- `scripts/run_multi.py` — Add flags, main loop logic
- `agents/multi_symbol_orchestrator.py` — Outer loop condition
- `agents/orchestrator.py` — Framework iteration, logging
- `agents/code_generator.py` — Framework param support
- `core/database.py` — New tables
- `templates/mql5/frameworks/` — New (create directory)

**Files to create:**
- `templates/mql5/frameworks/TrendFollowing.mq5.jinja2`
- `templates/mql5/frameworks/MeanReversion.mq5.jinja2`
- `templates/mql5/frameworks/Breakout.mq5.jinja2`
- `agents/market_regime_detector.py` — Regime classification

---

## Safety Guards

```python
# Don't hunt forever
MAX_HUNT_TIME = 72  # hours
MAX_ITERATIONS_PER_HUNT = 5000
BACKOFF_SLEEP = 30  # minutes between cycles

# Prevent duplicate attempts
SKIP_IF_TESTED_BEFORE = True  # Don't test same params twice

# Timeout per iteration
ITERATION_TIMEOUT = 15  # minutes per backtest

# Emergency: if DD > 20% ever, skip that framework for this symbol
FRAMEWORK_BLACKLIST = {}  # {symbol: [blacklisted_frameworks]}
```

---

## Dashboard Changes

**New Status:**
```
🏠 Overview page shows:
  ┌─ EURUSD ────────────────┐
  │ 🔍 HUNTING (Cycle 23)    │
  │ Best: v0.5.1.18 PF 1.42  │
  │ Time: 18h 45m / 72h      │
  │ Current: TrendFollowing  │
  │ Frameworks tested: 4/6   │
  └──────────────────────────┘
```

**Logs page:**
```
Iteration 47 | v0.5.1.18 | TrendFollowing  | PF 1.42 | DD 9.8% | ⏳ improving
Iteration 46 | v0.5.1.17 | MeanReversion   | PF 1.11 | DD 14%  | ✅ passed
Iteration 45 | v0.5.1.16 | Breakout        | PF 0.87 | DD 18%  | ❌ failed
```

---

## Next Steps

Pick one:
1. **Start Phase 1 now** (easiest, gives infinite hunting immediately)
2. **Start Phase 2 now** (harder, but frameworks = game-changer)
3. **Do both** (full stack)

Recommend: **Start Phase 1 + Phase 2 together** because Phase 2 is where real improvement happens.
