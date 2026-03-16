# Pair Management System

**Purpose:** Centralize symbol metadata (leverage, spread, volatility, trading hours, correlation) in database for dynamic, easily-manageable symbol configurations.

---

## Architecture

### 1. Source of Truth: `config/pairs.yaml`

```yaml
pairs:
  EURUSD:
    broker_leverage: 1:2000
    typical_spread_pips: 1.0
    typical_volatility_pips_h1: 40.0
    correlation: 1.0
    trading_hours: "Asia+London+NY"
    description: "Lowest spread, most liquid, best for testing."
    recommended: true

  USDJPY:
    broker_leverage: 1:2000
    typical_spread_pips: 2.0
    typical_volatility_pips_h1: 35.0
    correlation: -0.65
    trading_hours: "Asia+London+NY"
    description: "Strong trend, safe haven."
    recommended: true
```

### 2. Database Layer: `pairs` Table

| Column | Type | Purpose |
|---|---|---|
| `symbol` | String(10) | EURUSD, GBPUSD, etc. (unique key) |
| `broker_leverage` | String(20) | 1:2000, etc. |
| `typical_spread_pips` | Float | Historical average spread |
| `typical_volatility_pips_h1` | Float | H1 volatility in pips |
| `trading_hours` | String(50) | Asia+London+NY or 24/5 |
| `correlation_vs_eurusd` | Float | -1.0 to +1.0 |
| `description` | Text | User-friendly description |
| `recommended` | Boolean | Whether to include in trading |
| `loaded_at` | DateTime | Timestamp of last sync |

### 3. Python Layer: `PairRegistry` Class

**Dashboard (dashboard.py):**
```python
class PairRegistry:
    def get_all_symbols() -> list[str]
    def get_recommended_symbols() -> list[str]
    def get_spread(symbol) -> float
    def get_volatility_h1(symbol) -> float
    def get_leverage(symbol) -> str
    def get_trading_hours(symbol) -> str
    def get_description(symbol) -> str
    def get_correlation_vs_eurusd(symbol) -> float
    def get_metadata(symbol) -> dict
```

---

## Setup Instructions

### Step 1: Run Alembic Migration

```bash
cd /Users/doctorboyz/EA
alembic upgrade head
```

This creates the `pairs` table in PostgreSQL.

### Step 2: Load Pairs from YAML

```bash
python scripts/init_pairs_db.py
```

Output:
```
Loading pairs from config/pairs.yaml into database...
✓ Pairs loaded successfully
```

### Step 3: Verify in Dashboard

- Open Run Control → expand **"Pair Characteristics"**
- Should see all pairs (EURUSD, GBPUSD, USDJPY, XAUUSD) with metadata

---

## Adding a New Symbol

### Step 1: Update `config/pairs.yaml`

```yaml
pairs:
  # ... existing pairs ...
  AUDUSD:
    broker_leverage: 1:2000
    typical_spread_pips: 1.2
    typical_volatility_pips_h1: 45.0
    correlation: 0.72
    trading_hours: "Asia+London+NY"
    description: "Commodity-linked, liquid during Asian hours."
    recommended: true
```

### Step 2: Reload Pairs into DB

```bash
python scripts/init_pairs_db.py
```

### Step 3: Multi-Symbol Form Updates Automatically

- Dashboard `PAIR_REGISTRY.get_all_symbols()` now includes AUDUSD
- Multi-symbol form shows AUDUSD in dropdown
- Characteristics display includes AUDUSD metadata

---

## Usage in Code

### Dashboard (Form Dropdowns)

```python
# Multi-symbol selection
available = PAIR_REGISTRY.get_all_symbols()  # [AUDUSD, EURUSD, GBPUSD, ...]
symbols = st.multiselect("Symbols", available, default=recommended)

# Single symbol
sym = st.selectbox("Symbol", PAIR_REGISTRY.get_all_symbols())
```

### Constraints & Validation

```python
# Check if symbol is recommended
if not PAIR_REGISTRY.get_metadata(symbol).get("recommended"):
    st.warning(f"{symbol} is not recommended for trading")

# Get pair properties
spread = PAIR_REGISTRY.get_spread(symbol)
vol = PAIR_REGISTRY.get_volatility_h1(symbol)
```

### Database Queries

```python
# Direct database query (from agents/experience_db.py or analysis scripts)
async with get_session() as session:
    result = await session.execute(
        select(Pair).where(Pair.recommended == True)
    )
    recommended_pairs = result.scalars().all()

    for pair in recommended_pairs:
        print(f"{pair.symbol}: spread={pair.typical_spread_pips}")
```

---

## Disabling a Symbol (Blacklist)

Instead of deleting from `pairs.yaml`, set `recommended: false`:

```yaml
XAUUSD:
  # ... metadata ...
  recommended: false  # ← System will skip this
```

Then reload:
```bash
python scripts/init_pairs_db.py
```

Dashboard will exclude it from dropdowns (or show warning if selected).

---

## Migration Workflow

When adding new pair-related columns in the future:

1. Update `core/database.py` — add field to `Pair` class
2. Create Alembic migration: `alembic revision --autogenerate -m "description"`
3. Run: `alembic upgrade head`
4. Reload: `python scripts/init_pairs_db.py`

---

## Current Pairs

| Symbol | Spread | H1 Vol | Correlation | Recommended |
|---|---|---|---|---|
| EURUSD | 1.0 | 40 | 1.00 | ✅ |
| GBPUSD | 1.5 | 60 | 0.85 | ✅ |
| USDJPY | 2.0 | 35 | -0.65 | ✅ |
| XAUUSD | 0.5 | 200 | -0.80 | ❌ |
