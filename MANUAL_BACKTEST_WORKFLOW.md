# Manual MT5 Backtesting Workflow

## Problem
Automated backtest execution via Wine subprocess doesn't work on macOS. However, **manual backtesting with automatic report parsing does work**.

## Solution: Hybrid Approach
The system is 95% automated. You manually trigger backtests in MT5, and the system automatically:
- Detects the report file
- Parses metrics (Profit Factor, Drawdown, etc.)
- Analyzes results
- Generates improvements
- Continues the loop

## Quick Start (5 min setup, then 1 click per backtest)

### Step 1: Start the Championship Hunt
```bash
source venv/bin/activate
python scripts/run_multi.py --symbols EURUSD --until-champion --max-hours 48
```

**What to expect:**
- System generates EA code
- Copies EA files to MT5 `Experts/` folder
- Waits for backtest report (~180 seconds timeout)
- Dashboard shows "Waiting for report..."

### Step 2: Run Backtest in MT5

**Every time system times out waiting (every ~3 minutes):**

1. **Click** to open MetaTrader 5 application
   ```
   /Applications/MetaTrader 5.app
   ```

2. **Click** Strategy Tester tab (left sidebar below Navigator)

3. **Select** the latest EA file:
   - Look in Expert selector dropdown
   - Should see recent file like: `AureusV0_3_0_EUR_H1_R1_Cap1000_TF`
   - If not visible, refresh (F5)

4. **Configure** (usually already set):
   - Symbol: EURUSD
   - Period: H1 (1 hour)
   - Date From: 2025.01.01
   - Date To: 2026.03.12 (or current date)
   - Model: 1-min OHLC
   - Initial Deposit: 1000 USD

5. **Click** "Start" button

6. **Wait** for backtest to complete (usually 2-5 minutes)
   - Progress bar shows "Testing..."
   - Don't close MT5

### Step 3: System Detects Report

**What happens automatically:**
- System detects new `.htm` file in `/Program Files/MetaTrader 5/`
- Parses metrics automatically
- Shows results in logs:
  ```
  ✅ [Result] PF=1.31 DD=11.2% RF=1.05 - Generated: AureusV0_3_1_EUR_H1_R1_Cap1000_MR.mq5
  ```
- Generates next improved EA
- Repeats from Step 2

### Step 4: Monitor Progress

**While waiting, check dashboard:**
```
streamlit run dashboard.py --server.port 8501
```

Open: http://localhost:8501

View:
- **Run Control** → Status, PID, Uptime
- **Live Logs** → Colored level indicators, JSON parsing
- **Backtest History** → All results from this hunt
- **Metrics** → Profit Factor trends, best EAs

## Tips

### Keep MT5 Always Open
```bash
# In separate Terminal tab:
open /Applications/MetaTrader\ 5.app
```

MT5 stays in background. When system timeout triggers, just click MT5 window and run backtest.

### Keyboard Shortcut (Faster)
1. Once MT5 is open, focus the Strategy Tester tab
2. Click EA selector (usually already showing latest)
3. Press Spacebar or click "Start"
4. Wait for completion (2-5 min)
5. Report automatically detected

### No Manual File Navigation
System automatically:
- Copies EA to correct folder (`MQL5/Experts/Aureus/`)
- Finds latest `.htm` report
- Parses any HTML encoding (UTF-16 LE)
- Extracts all metrics

You don't need to navigate folders or move files.

### Watchdog Files
System monitors this directory for new reports:
```
~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/
```

New `.htm` files here trigger automatic parsing.

## Expected Timeline

For 48-hour champion hunt with manual backtesting:

```
~3-5 min per EA generation + compilation
~3-10 min per backtest (depends on data)
~1 sec per result parsing & analysis
```

If you run ~1 backtest every 10 minutes:
- **48 hours** = ~288 backtests possible
- **Finding champion** = likely within 24 hours (if champion exists)

## Troubleshooting

### "Polling timeout" (180 seconds) appears in logs
→ System waiting for report. Open MT5 and run backtest.

### Report not detected
→ Make sure MT5 is fully visible and backtest completed
→ Check logs for which EA was generated
→ Search for that filename in MT5 window title

### MT5 freezes during backtest  
→ It's normal for 1+ year of data. Just wait 2-5 minutes.
→ Don't force quit - report still generates.

### Can't find EA in selector dropdown
→ Refresh MT5 (F5)
→ Check `/MQL5/Experts/Aureus/` folder in File Manager
→ Restart MT5 if stuck

## Alternative: Leave MT5 in Tester Mode

For truly hands-off operation:
1. Open MT5
2. Go to Strategy Tester
3. Click "Start" on any EA (let it run/fail)
4. Tester window stays ready for next backtest
5. Just keep MT5 running in background
6. When timeouts trigger, tester is ready immediately

## Why This Works Better

✅ **Reliable** — MT5 tester is proven stable
✅ **Fast** — No Wine subprocess overhead  
✅ **Simple** — One click per ~10 minutes
✅ **Debuggable** — Can visually inspect each backtest
✅ **Network-Safe** — No complex subprocess IPC

## Next Steps

1. Open terminal: `source venv/bin/activate`
2. Start hunt: `python scripts/run_multi.py --symbols EURUSD --until-champion --max-hours 48`
3. Open MT5: `open /Applications/MetaTrader\ 5.app`
4. Wait for first timeout, then run first backtest
5. Keep running until champion found (usually 24-48 hours)

Questions? Check logs in dashboard Live Logs tab.
