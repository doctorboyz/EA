"""
Aureus AI Dashboard — Clean 4-section single-page UI with Hunt Mode Controls.

Sections:
  1. Header Bar — Phase pipeline, status, controls
  2. Hunt Mode Selector — Choose hunt mode and parameters
  3. Champion Section — Current champion metrics
  4. Hunt Log & Logs — Recent iterations + live tail
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
CFG_PATH = BASE_DIR / "config" / "system.yaml"
STATUS_FILE = BASE_DIR / "logs" / "system_status.json"
PID_FILE = BASE_DIR / "logs" / "run_multi.pid"
LOG_DIR = BASE_DIR / "logs"
PYTHON = BASE_DIR / "venv" / "bin" / "python"

LOG_DIR.mkdir(parents=True, exist_ok=True)

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Aureus AI",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none; }
    body { margin: 0; padding: 0; }
    .header-bar { background: linear-gradient(90deg, #1f77b4, #ff7f0e); padding: 15px; border-radius: 8px; color: white; }
    .metric-card { background: #f0f0f0; padding: 15px; border-radius: 8px; margin: 5px 0; }
    .phase-box { background: #e8f5e9; border-left: 4px solid #4caf50; padding: 10px; border-radius: 4px; }
    .champion-box { background: #fff3e0; border-left: 4px solid #ff9800; padding: 15px; border-radius: 4px; }
    .mode-selector { background: #f5f5f5; padding: 15px; border-radius: 8px; border: 2px solid #ddd; }
    .alert { background: #ffebee; border-left: 4px solid #f44336; padding: 10px; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)


# ─── Helper functions ─────────────────────────────────────────────────────────

def load_status() -> dict:
    """Load live status from JSON file."""
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE) as f:
                return json.load(f)
        except Exception as e:
            st.warning(f"Could not load status: {e}")
    return {}


def load_champion_data() -> dict:
    """Load champion info from database."""
    try:
        import yaml
        from core.champion_manager import ChampionManager

        with open(CFG_PATH) as f:
            cfg = yaml.safe_load(f)

        db_url = cfg.get("database", {}).get("url")
        if not db_url:
            return {}

        manager = ChampionManager(db_url)
        champ = manager.get_global_champion("XAUUSD")
        return champ or {}
    except Exception as e:
        st.warning(f"Could not load champion: {e}")
        return {}


def is_running() -> bool:
    """Check if run_multi.py is currently running."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError):
        return False
    except Exception:
        return False


def get_running_pid() -> int:
    """Get the PID of running hunt, or 0 if not running."""
    if not PID_FILE.exists():
        return 0
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return 0


def start_hunt(mode: str, iterations: int, extra_args: list = None):
    """Start hunt with given mode and parameters."""
    if is_running():
        st.error("❌ Hunt already running! Stop it first.")
        return False

    args = [str(PYTHON), "scripts/run_multi.py", "--symbols", "XAUUSD", "--iterations", str(iterations)]

    # Add mode-specific arguments
    if mode == "continuous":
        args.append("--continuous")
    elif mode == "until-champion":
        args.append("--until-champion")

    if extra_args:
        args.extend(extra_args)

    try:
        subprocess.Popen(
            args,
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)  # Give process time to start
        st.success(f"✅ Hunt started: {mode} mode, {iterations} iterations")
        st.rerun()
        return True
    except Exception as e:
        st.error(f"❌ Failed to start hunt: {e}")
        return False


def stop_hunt():
    """Stop running hunt gracefully."""
    pid = get_running_pid()
    if pid == 0:
        st.warning("⚠️ No hunt running")
        return False

    try:
        import signal

        os.kill(pid, signal.SIGTERM)
        time.sleep(1)

        # Verify it stopped
        if not is_running():
            st.success("✅ Hunt stopped gracefully")
            st.rerun()
            return True
        else:
            st.warning("⚠️ Hunt didn't stop immediately, retrying with SIGKILL...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
            st.success("✅ Hunt force-stopped")
            st.rerun()
            return True
    except ProcessLookupError:
        st.info("ℹ️ Hunt already stopped")
        st.rerun()
        return True
    except Exception as e:
        st.error(f"❌ Failed to stop hunt: {e}")
        return False


# ─── Layout ───────────────────────────────────────────────────────────────────

# Load data
status = load_status()
champion = load_champion_data()
running = is_running()

# ─── HEADER BAR ────────────────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns([2, 2, 1, 2])

with col1:
    st.markdown("### 💰 AUREUS AI")
    st.markdown("**XAUUSD Champion Hunter**")

with col2:
    if running:
        st.markdown("### ● HUNTING")
    else:
        st.markdown("### ○ STOPPED")

with col3:
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    st.markdown(f"**{now}** UTC")

with col4:
    if running:
        if st.button("■ STOP NOW", key="stop_btn_header", use_container_width=True):
            stop_hunt()
    else:
        st.markdown("*Ready*")

st.divider()

# ─── PHASE PIPELINE ────────────────────────────────────────────────────────────

st.markdown("## Phase Pipeline")

phase = status.get("phase", "hunt")
phase_detail = status.get("phase_detail", "Initializing...")
phase_gate = status.get("phase_gate", "Waiting for champion...")

cols = st.columns(4)
with cols[0]:
    badge = "✓" if phase == "hunt" else ("▶" if champion else "○")
    st.markdown(f"### [{badge}] Hunt")
    st.caption("PF ≥ 1.3 needed")

with cols[1]:
    badge = "✓" if phase == "walk_forward" else ("▶" if phase in ["forward_test", "live"] else "○")
    st.markdown(f"### [{badge}] Walk-Forward")
    st.caption("4/6 windows pass")

with cols[2]:
    badge = "✓" if phase == "forward_test" else ("▶" if phase == "live" else "○")
    st.markdown(f"### [{badge}] Forward Test")
    st.caption("5d / 10tr / PF 1.1")

with cols[3]:
    badge = "✓" if phase == "live" else "○"
    st.markdown(f"### [{badge}] Live")
    st.caption("5d + / DD ≤ 20%")

st.markdown(f"**Current:** {phase_detail}")
st.markdown(f"**Next:** {phase_gate}")

st.divider()

# ─── MARKETS SECTION ───────────────────────────────────────────────────────────

st.markdown("## 🌍 Markets & Trading Pairs")

# Market information
markets_info = {
    "XAUUSD": {
        "name": "Gold (Spot)",
        "currency": "USD",
        "session": "24/5 (Mon-Fri)",
        "volatility": "High",
        "status": "🟢 ACTIVE",
        "description": "Gold futures, highest volatility, best for breakouts",
        "hours": "22:00 Sun - 21:00 Fri UTC",
        "characteristics": ["High volatility", "Strong trends", "News-driven", "Best for ATR strategies"],
    },
    "EURUSD": {
        "name": "Euro / US Dollar",
        "currency": "Forex",
        "session": "24/5 (Mon-Fri)",
        "volatility": "Medium",
        "status": "⚪ AVAILABLE",
        "description": "Most traded forex pair, good for trending strategies",
        "hours": "22:00 Sun - 21:00 Fri UTC",
        "characteristics": ["Medium volatility", "Liquid", "Predictable trends", "News sensitive"],
    },
    "GBPUSD": {
        "name": "British Pound / US Dollar",
        "currency": "Forex",
        "session": "24/5 (Mon-Fri)",
        "volatility": "Medium-High",
        "status": "⚪ AVAILABLE",
        "description": "GBP pair, good liquidity, strong movements",
        "hours": "22:00 Sun - 21:00 Fri UTC",
        "characteristics": ["Medium-High volatility", "Trending", "Brexit sensitive", "Good for scalping"],
    },
    "USDJPY": {
        "name": "US Dollar / Japanese Yen",
        "currency": "Forex",
        "session": "24/5 (Mon-Fri)",
        "volatility": "Medium",
        "status": "⚪ AVAILABLE",
        "description": "Safe-haven pair, useful for risk-off trading",
        "hours": "22:00 Sun - 21:00 Fri UTC",
        "characteristics": ["Medium volatility", "Safe-haven", "BoJ sensitive", "Carry trade pair"],
    },
    "BTCUSD": {
        "name": "Bitcoin / US Dollar",
        "currency": "Crypto",
        "session": "24/7",
        "volatility": "Very High",
        "status": "⚪ AVAILABLE",
        "description": "Cryptocurrency, extreme volatility, trendy but risky",
        "hours": "24/7/365",
        "characteristics": ["Very high volatility", "No correlation", "Crypto-driven", "Weekend trading"],
    },
}

# Show current market and available markets
col_current, col_available = st.columns(2)

with col_current:
    st.markdown("### 📌 Currently Active Market")
    current_market = "XAUUSD"
    market_data = markets_info[current_market]

    # XAUUSD is 24/5, so show green light during weekdays
    from datetime import datetime
    now = datetime.utcnow()
    is_weekday = now.weekday() < 5  # Monday=0, Friday=4
    market_status = "🟢 OPEN" if is_weekday else "🔴 CLOSED (Weekend)"

    st.markdown(f"#### {market_status} {current_market}")
    st.markdown(f"**{market_data['name']}**")
    st.caption(market_data['description'])

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Volatility", market_data['volatility'])
    with col_b:
        st.metric("Session", market_data['session'])
    with col_c:
        st.metric("Trading", market_data['hours'])

    st.markdown("**Key Characteristics:**")
    for char in market_data['characteristics']:
        st.markdown(f"  • {char}")

with col_available:
    st.markdown("### 🌐 Available Markets")
    st.markdown("*Future expansion markets (currently XAUUSD focus)*")

    for symbol, info in markets_info.items():
        if symbol != current_market:
            col1, col2, col3 = st.columns([1, 2, 2])
            with col1:
                st.markdown(f"**{symbol}**")
            with col2:
                st.caption(info['name'])
            with col3:
                st.caption(f"{info['status']} • {info['volatility']}")

st.divider()

# ─── MARKET SESSIONS ───────────────────────────────────────────────────────────

st.markdown("### 📅 Market Sessions (UTC)")

def is_market_open(open_hour: int, close_hour: int) -> bool:
    """Check if market is open based on current UTC time. Handles overnight sessions."""
    from datetime import datetime

    now = datetime.utcnow()
    current_hour = now.hour

    if open_hour < close_hour:
        # Normal session (e.g., London 7:00-16:00)
        return open_hour <= current_hour < close_hour
    else:
        # Overnight session (e.g., Sydney 22:00-07:00)
        return current_hour >= open_hour or current_hour < close_hour

session_data = {
    "Sydney": {"open": 22, "close": 7, "flag": "🇦🇺", "display_open": "22:00", "display_close": "07:00"},
    "Tokyo": {"open": 0, "close": 9, "flag": "🇯🇵", "display_open": "00:00", "display_close": "09:00"},
    "London": {"open": 7, "close": 16, "flag": "🇬🇧", "display_open": "07:00", "display_close": "16:00"},
    "New York": {"open": 12, "close": 21, "flag": "🇺🇸", "display_open": "12:00", "display_close": "21:00"},
}

sess_cols = st.columns(4)
for idx, (session, times) in enumerate(session_data.items()):
    with sess_cols[idx]:
        is_open = is_market_open(times['open'], times['close'])
        status_icon = "🟢" if is_open else "🔴"
        status_text = "OPEN" if is_open else "CLOSED"

        st.markdown(f"#### {status_icon} {times['flag']} {session}")
        st.markdown(f"**{status_text}**", unsafe_allow_html=True)
        st.caption(f"{times['display_open']} - {times['display_close']} UTC")

st.divider()

# ─── HUNT MODE SELECTOR ────────────────────────────────────────────────────────

st.markdown("## 🎯 Hunt Mode Selector")

if running:
    st.warning("⚠️ Hunt is currently running. Stop it first to change mode.")
    if st.button("🛑 STOP HUNT NOW", use_container_width=True, key="stop_main"):
        stop_hunt()
else:
    # Create 3 columns for hunt modes
    col_quick, col_normal, col_long = st.columns(3)

    # QUICK TEST MODE
    with col_quick:
        st.markdown("### ⚡ Quick Test")
        st.caption("5 iterations, fast feedback")
        if st.button("Start Quick Test", use_container_width=True, key="quick"):
            start_hunt("single", 5)

    # NORMAL HUNT MODE
    with col_normal:
        st.markdown("### 🔍 Normal Hunt")
        st.caption("20 iterations, standard")
        if st.button("Start Normal Hunt", use_container_width=True, key="normal"):
            start_hunt("single", 20)

    # LONG HUNT MODE
    with col_long:
        st.markdown("### 🏃 Long Hunt")
        st.caption("50 iterations, thorough")
        if st.button("Start Long Hunt", use_container_width=True, key="long"):
            start_hunt("single", 50)

    st.markdown("---")

    # ADVANCED MODES
    col_cont, col_champ = st.columns(2)

    with col_cont:
        st.markdown("### 🔄 Continuous Hunt")
        st.caption("Runs forever, restarts every 5 min")
        iterations_cont = st.slider(
            "Iterations per cycle", min_value=5, max_value=50, value=20, key="cont_iter"
        )
        if st.button("Start Continuous", use_container_width=True, key="continuous"):
            start_hunt("continuous", iterations_cont)

    with col_champ:
        st.markdown("### 👑 Hunt Until Champion")
        st.caption("Stops when PF ≥ 1.3 found")
        iterations_champ = st.slider(
            "Max iterations", min_value=20, max_value=200, value=100, key="champ_iter"
        )
        if st.button("Start Champion Hunt", use_container_width=True, key="until_champion"):
            start_hunt("until-champion", iterations_champ)

st.divider()

# ─── CHAMPION & HUNT LOG (2-column) ────────────────────────────────────────────

col_champ, col_log = st.columns(2)

# Champion section
with col_champ:
    st.markdown("## 🏆 Champion")

    if champion:
        version = champion.get("version", "none")
        pf = champion.get("profit_factor", 0.0)
        dd = champion.get("max_drawdown_pct", 0.0)
        rf = champion.get("recovery_factor", 0.0)
        wl = champion.get("avg_win_loss_ratio", 0.0)

        st.markdown(f"**v{version}**")

        # Metrics with progress bars
        st.metric("Profit Factor", f"{pf:.2f}", delta="≥ 1.3 ✓" if pf >= 1.3 else f"{pf - 1.3:.2f}")
        st.progress(min(pf / 2.0, 1.0), text=f"PF {pf:.2f}")

        st.metric("Max Drawdown %", f"{dd:.1f}%", delta="≤ 30% ✓" if dd <= 30 else f"+{dd - 30:.1f}%")
        st.progress(max(1.0 - (dd / 50.0), 0.0), text=f"DD {dd:.1f}%")

        st.metric("Recovery Factor", f"{rf:.2f}", delta="≥ 1.0 ✓" if rf >= 1.0 else f"{rf - 1.0:.2f}")
        st.progress(min(rf / 2.0, 1.0), text=f"RF {rf:.2f}")

        st.metric("Win/Loss Ratio", f"{wl:.2f}", delta="≥ 1.5 ✓" if wl >= 1.5 else f"{wl - 1.5:.2f}")
        st.progress(min(wl / 3.0, 1.0), text=f"W/L {wl:.2f}")
    else:
        st.info("📊 No champion yet — start a hunt to begin!")

# Hunt log section
with col_log:
    st.markdown("## 📈 Hunt Log (Last 20)")

    hunt_log = status.get("hunt_log", [])
    if hunt_log:
        # Convert to DataFrame for nice display
        df_log = pd.DataFrame(hunt_log)
        # Keep only key columns
        if "version" in df_log.columns:
            df_log = df_log[["iteration", "version", "profit_factor", "max_drawdown_pct", "avg_win_loss_ratio"]]
            df_log.columns = ["#", "Version", "PF", "DD%", "W/L"]
            df_log = df_log.astype({"PF": "float", "DD%": "float", "W/L": "float"})
            df_log = df_log.round(2)

            # Highlight best PF row
            def highlight_best(row):
                if row["PF"] == df_log["PF"].max():
                    return ["background-color: #fff9c4"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_log.style.apply(highlight_best, axis=1),
                use_container_width=True,
                height=400,
            )
        else:
            st.json(hunt_log)
    else:
        st.info("📊 No hunt data yet")

st.divider()

# ─── LOGS & CONTROLS ───────────────────────────────────────────────────────────

st.markdown("## ⚙️ Logs & Controls")

col_fw, col_risk, col_actions = st.columns(3)

with col_fw:
    st.markdown("### Frameworks (All 8)")
    frameworks = [
        "🎯 XAUBreakout",
        "📈 TrendFollowing",
        "💥 Breakout",
        "🔄 MeanReversion",
        "🎯 SniperEntry",
        "🕯️ CandlePattern",
        "☁️ IchimokuCloud",
        "📊 GridTrading",
    ]
    st.markdown("\n".join(frameworks))

with col_risk:
    st.markdown("### Status")
    status_text = "🟢 Running" if running else "🔴 Stopped"
    st.markdown(f"**{status_text}**")

    if running:
        pid = get_running_pid()
        st.markdown(f"PID: `{pid}`")

with col_actions:
    st.markdown("### Quick Actions")
    if st.button("🔄 Refresh Now", use_container_width=True):
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 View Logs", use_container_width=True):
            st.session_state.show_logs = True

    with col2:
        if st.button("📊 JSON Status", use_container_width=True):
            st.json(status)

# Live log tail
st.markdown("### 📜 Live Log Output")
log_file = LOG_DIR / "orchestrator.log"
if log_file.exists():
    try:
        with open(log_file) as f:
            lines = f.readlines()
        # Show last 30 lines
        tail = "".join(lines[-30:])
        st.code(tail, language="text")
    except Exception as e:
        st.warning(f"Could not read log: {e}")
else:
    st.info("ℹ️ Waiting for hunt to start (logs will appear here)...")

# Auto-refresh every 5 seconds
st.markdown("""
<script>
setTimeout(function() {
    window.location.reload();
}, 5000);
</script>
""", unsafe_allow_html=True)
