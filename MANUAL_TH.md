# คู่มือการใช้งาน Aureus AI Trading Bot
**ภาษาไทย | สำหรับผู้ใช้ทั่วไป | XAUUSD Champion Hunter**

---

## 📌 ระบบนี้คืออะไร?

**Aureus AI** คือระบบที่ใช้ปัญญาประดิษฐ์ (AI) สร้างและปรับปรุง **Expert Advisor (EA)** สำหรับ MetaTrader 5 โดยอัตโนมัติ

ระบบจะทำงานวนซ้ำดังนี้:

```
สร้างโค้ด EA → ทดสอบ Backtest → วิเคราะห์ผล → ปรับปรุง → วนซ้ำ
```

**เป้าหมาย:** หา EA ที่ผ่านเกณฑ์ Champion tier บน **XAUUSD (ทองคำ)** เท่านั้น

---

## 🎯 เกณฑ์เป้าหมาย (3 ระดับ)

| ตัวชี้วัด | Gate (ขั้นต่ำ) | Champion (เลื่อนชั้น) | Gold (ใช้จริง) |
|---|---|---|---|
| **Profit Factor** | > 1.0 | > 1.3 | > 1.8 |
| **Max Drawdown %** | < 40% | < 30% | < 20% |
| **Recovery Factor** | > 0.5 | > 1.0 | > 2.0 |
| **Win/Loss Ratio** | > 1.0 | > 1.5 | > 2.0 |

- **Gate** = ขั้นต่ำที่จะบันทึกผลลัพธ์
- **Champion** = ผ่านแล้วจะทดสอบ Walk-Forward
- **Gold** = พร้อมสำหรับการเทรดจริง

---

## 🔄 Phase Pipeline (ระบบ 4 เฟส)

```
[1] HUNT ──→ [2] WALK-FORWARD ──→ [3] FORWARD TEST ──→ [4] LIVE
```

| เฟส | เงื่อนไขผ่าน | อะไรเกิดขึ้น |
|---|---|---|
| **1. Hunt** | PF ≥ 1.3 | AI หมุน 8 frameworks สร้างและปรับปรุง EA |
| **2. Walk-Forward** | 4/6 windows ผ่าน (PF ≥ 0.8) | ทดสอบ EA ซ้ำใน 6 ช่วงเวลาย่อย |
| **3. Forward Test** | 5 วัน + 10 เทรด + PF ≥ 1.1 + DD ≤ 20% | Deploy บัญชี Demo |
| **4. Live** | เปิดเอง (manual) | เทรดจริง, Emergency stop ที่ DD = 20% |

---

## 🖥️ การติดตั้งและตั้งค่า (ครั้งแรก)

### ขั้นที่ 1: เปิด Terminal
กด `Cmd + Space` แล้วพิมพ์ `Terminal`

### ขั้นที่ 2: ไปยังโฟลเดอร์โปรเจกต์
```bash
cd /Users/doctorboyz/EA
```

### ขั้นที่ 3: เปิดใช้งาน Python Environment
```bash
source venv/bin/activate
```
> ⚠️ ต้องรันทุกครั้งที่เปิด Terminal ใหม่

### ขั้นที่ 4: ติดตั้ง Dependencies (ครั้งแรก)
```bash
pip install crewai crewai-tools langchain-community
ollama pull qwen2.5-coder:14b
ollama pull qwen3.5:9b
```

### ขั้นที่ 5: ตรวจสอบระบบ
```bash
ollama serve              # เปิด AI server (terminal แยก)
python scripts/check_ollama.py
python -m pytest tests/ -v
```

---

## 🚀 การเริ่มใช้งาน

### วิธีที่ 1: เปิด Dashboard (แนะนำ)

```bash
cd /Users/doctorboyz/EA
source venv/bin/activate
streamlit run dashboard.py
```

จากนั้นเปิดเบราว์เซอร์ไปที่: **http://localhost:8501**

กดปุ่ม Hunt Mode ที่ต้องการใน Dashboard

---

### วิธีที่ 2: รัน Command Line

#### ⚡ Quick Test — ทดสอบเร็ว (5 รอบ)
```bash
cd /Users/doctorboyz/EA
source venv/bin/activate
python scripts/run_multi.py --symbols XAUUSD --iterations 5
```
> เวลา: ~10-15 นาที | ใช้สำหรับทดสอบว่าระบบทำงานได้

#### 🔍 Normal Hunt — ล่ามาตรฐาน (20 รอบ)
```bash
python scripts/run_multi.py --symbols XAUUSD --iterations 20
```
> เวลา: ~30-60 นาที | โหมดเริ่มต้นที่แนะนำ

#### 🏃 Long Hunt — ล่ายาว (50 รอบ)
```bash
python scripts/run_multi.py --symbols XAUUSD --iterations 50
```
> เวลา: ~1.5-3 ชั่วโมง | สำหรับเมื่อมีเวลาเหลือ

#### 🔄 Continuous — ล่าต่อเนื่อง (ไม่หยุด)
```bash
python scripts/run_multi.py --symbols XAUUSD --continuous --iterations 20 --restart-delay 300
```
> รันไม่หยุด | รีสตาร์ททุก 5 นาที | เหมาะสำหรับเปิดค้างคืน

#### 👑 Hunt Until Champion — ล่าจนเจอ Champion
```bash
python scripts/run_multi.py --symbols XAUUSD --until-champion --iterations 100 --max-hours 48
```
> หยุดเมื่อ PF ≥ 1.3 | Timeout 48 ชั่วโมง | เหมาะที่สุดสำหรับหา Champion

---

## 🛑 การหยุดระบบ

### จาก Dashboard
- กดปุ่ม **"■ STOP NOW"** ด้านบนขวา
- หรือกดปุ่ม **"🛑 STOP HUNT NOW"** ใน Hunt Mode Selector

### จาก Terminal
```bash
# หยุดด้วย PID
kill $(cat logs/run_multi.pid)

# ถ้าไม่หยุด — Force kill
pkill -9 -f "run_multi.py"

# ถ้ามี Auto-start daemon ที่ keep respawn
launchctl unload ~/Library/LaunchAgents/com.aureus.trading.plist
pkill -9 -f "run_multi.py"
```

### ตรวจสอบว่าหยุดแล้ว
```bash
ps aux | grep run_multi | grep -v grep
# ถ้าไม่มี output = หยุดแล้ว
```

---

## ♻️ การเปิด Auto-start daemon

### เปิดใช้ (Auto-restart เมื่อ login หรือ crash)
```bash
launchctl load ~/Library/LaunchAgents/com.aureus.trading.plist
```

### ปิดใช้
```bash
launchctl unload ~/Library/LaunchAgents/com.aureus.trading.plist
```

### ตรวจสอบสถานะ
```bash
launchctl list | grep aureus
# ถ้ามี output = daemon กำลังทำงาน
```

---

## 📊 การใช้งาน Dashboard

เปิด **http://localhost:8501** ในเบราว์เซอร์

### ส่วนที่ 1: Header Bar
- แสดงสถานะ: **● HUNTING** หรือ **○ STOPPED**
- ปุ่มหยุด: **■ STOP NOW**
- เวลาปัจจุบัน UTC

### ส่วนที่ 2: Phase Pipeline
- แสดงเฟสปัจจุบัน: Hunt → Walk-Forward → Forward Test → Live
- บอกว่า "ต้องทำอะไรถึงจะผ่านเฟสถัดไป"

### ส่วนที่ 3: 🌍 Markets
- ตลาดที่เปิดอยู่ (🟢 OPEN / 🔴 CLOSED)
- **XAUUSD** = ตลาดที่กำลัง Hunt
- Sessions: Sydney / Tokyo / London / New York

### ส่วนที่ 4: 🎯 Hunt Mode Selector
- **⚡ Quick Test** — 5 รอบ
- **🔍 Normal Hunt** — 20 รอบ
- **🏃 Long Hunt** — 50 รอบ
- **🔄 Continuous** — รันไม่หยุด (ตั้ง iterations per cycle ได้)
- **👑 Until Champion** — หยุดเมื่อเจอ Champion (ตั้ง max iterations ได้)

### ส่วนที่ 5: 🏆 Champion + 📈 Hunt Log
- แสดง Champion ปัจจุบัน (PF / DD / RF / W/L พร้อม progress bar)
- Hunt Log: ผล 20 รอบล่าสุด (ไฮไลต์ PF ดีที่สุด)

### ส่วนที่ 6: ⚙️ Logs & Controls
- 8 Frameworks ที่ใช้
- ปุ่ม Refresh / View Logs / JSON Status
- Live Log Output (30 บรรทัดล่าสุด)

---

## 🔧 8 Frameworks ที่ใช้

| Framework | จุดแข็ง | ใช้เมื่อ |
|---|---|---|
| **XAUBreakout** | ATR-channel breakout สำหรับทอง | ตลาดกำลัง breakout |
| **TrendFollowing** | EMA crossover, PF=2.85 | ตลาด trending |
| **Breakout** | Generic breakout | ตลาด breakout ทั่วไป |
| **MeanReversion** | RSI mean reversion | ตลาด sideway/ranging |
| **SniperEntry** | เข้าเทรดแม่นยำ ไม่บ่อย | จำนวนเทรดน้อย |
| **CandlePattern** | แท่งเทียนจีน | pattern recognition |
| **IchimokuCloud** | Trend + cloud confirmation | ตลาด trending ชัด |
| **GridTrading** | Grid ซื้อขาย | ตลาด sideway/choppy |

ExperienceDB จะเลือก framework ให้อัตโนมัติ: **80% ใช้ตัวที่ดี** / **20% ลองตัวใหม่**

---

## 🗂️ โครงสร้างโฟลเดอร์

```
EA/
├── dashboard.py          ← หน้าเว็บ Dashboard (single page, 6 ส่วน)
├── config/
│   ├── system.yaml       ← ตั้งค่าระบบ (DB, MT5, Ollama, targets, walk-forward)
│   └── forward_test.yaml ← เกณฑ์ Promotion Demo → Real
├── strategies/
│   ├── baseline/         ← EA ต้นฉบับ (V3, V4)
│   ├── generated/        ← EA ที่ AI สร้าง
│   ├── champion/         ← EA ที่ดีที่สุด
│   └── archive/          ← EA เก่าทั้งหมด
├── agents/
│   ├── orchestrator.py   ← ควบคุม Hunt loop (XAUUSD only)
│   ├── aureus_crew.py    ← CrewAI crew (3 agents, 4 tools)
│   ├── code_generator.py ← สร้างโค้ด MQL5
│   ├── backtest_runner.py ← รัน MT5 Strategy Tester
│   ├── report_parser.py  ← อ่าน HTML report
│   ├── result_analyzer.py ← วิเคราะห์ผล (LLM)
│   ├── strategy_improver.py ← ปรับปรุงพารามิเตอร์ (LLM)
│   ├── news_filter.py    ← ดึงข่าวจาก ForexFactory
│   ├── market_regime_detector.py ← ตรวจสภาวะตลาด
│   ├── forward_test_manager.py ← บริหาร Demo deployment
│   └── live_trade_agent.py ← มอนิเตอร์บัญชีจริง
├── core/
│   ├── strategy_config.py ← Pydantic models + tiered targets
│   ├── constraint_validator.py ← กฎห้ามละเมิด
│   ├── champion_manager.py ← จัดการ Champion (DB-backed)
│   ├── walk_forward.py   ← Walk-Forward Validator
│   ├── database.py       ← SQLAlchemy ORM
│   └── ollama_client.py  ← Ollama API wrapper
├── scripts/
│   ├── run_multi.py      ← Entry point: รัน XAUUSD hunt
│   ├── run_loop.py       ← รันระบบ (Single loop)
│   └── check_ollama.py   ← ตรวจสอบ Ollama
├── logs/
│   ├── system_status.json ← Dashboard อ่านจากไฟล์นี้
│   ├── orchestrator.log  ← Log หลัก
│   └── run_multi.pid     ← PID ของ process
└── templates/mql5/       ← Jinja2 templates สำหรับ EA
```

---

## ⚙️ ไฟล์ Config หลัก

**ไฟล์:** `config/system.yaml`

| การตั้งค่า | ค่าปัจจุบัน | ความหมาย |
|---|---|---|
| `project.symbol` | XAUUSD | คู่เงินที่ Hunt |
| `project.risk_percent` | 0.5 | % ความเสี่ยงต่อเทรด |
| `targets.champion.profit_factor` | 1.3 | PF ขั้นต่ำเพื่อเลื่อน Champion |
| `targets.champion.max_drawdown_pct` | 30.0 | DD สูงสุดที่ยอมรับ |
| `ollama.code_gen_model` | qwen2.5-coder:14b | AI สร้างโค้ด |
| `ollama.analysis_model` | qwen3.5:9b | AI วิเคราะห์ผล |
| `multi_symbol.symbols` | ["XAUUSD"] | XAUUSD เท่านั้น |
| `walk_forward.enabled` | true | เปิดการทดสอบ Walk-Forward |

---

## 📋 คำสั่งที่ใช้บ่อย (รวมทั้งหมด)

```bash
# ── เตรียมตัว (ต้องทำก่อนเสมอ) ─────────────────────
cd /Users/doctorboyz/EA
source venv/bin/activate

# ── เปิด Dashboard ──────────────────────────────────
streamlit run dashboard.py

# ── Hunt Modes ───────────────────────────────────────
# ⚡ Quick Test (5 รอบ)
python scripts/run_multi.py --symbols XAUUSD --iterations 5

# 🔍 Normal Hunt (20 รอบ)
python scripts/run_multi.py --symbols XAUUSD --iterations 20

# 🏃 Long Hunt (50 รอบ)
python scripts/run_multi.py --symbols XAUUSD --iterations 50

# 🔄 Continuous (ไม่หยุด, รีสตาร์ททุก 5 นาที)
python scripts/run_multi.py --symbols XAUUSD --continuous --iterations 20 --restart-delay 300

# 👑 Until Champion (หยุดเมื่อเจอ Champion)
python scripts/run_multi.py --symbols XAUUSD --until-champion --iterations 100 --max-hours 48

# ── หยุดระบบ ─────────────────────────────────────────
kill $(cat logs/run_multi.pid)              # หยุดปกติ
pkill -9 -f "run_multi.py"                  # Force stop
launchctl unload ~/Library/LaunchAgents/com.aureus.trading.plist  # ปิด auto-start

# ── ตรวจสอบสถานะ ─────────────────────────────────────
cat logs/system_status.json | python -m json.tool    # ดู status
ps aux | grep run_multi | grep -v grep               # ดู process
tail -f logs/orchestrator.log                         # ดู log real-time
launchctl list | grep aureus                          # ดู daemon status

# ── ดู Champion ──────────────────────────────────────
python -c "
import yaml
from core.champion_manager import ChampionManager
cfg = yaml.safe_load(open('config/system.yaml'))
cm = ChampionManager(cfg['database']['url'])
champ = cm.get_global_champion('XAUUSD')
if champ:
    print(f'Champion: v{champ[\"version\"]}')
    print(f'PF={champ[\"profit_factor\"]:.2f}  DD={champ[\"max_drawdown_pct\"]:.1f}%')
    print(f'RF={champ[\"recovery_factor\"]:.2f}  W/L={champ[\"avg_win_loss_ratio\"]:.2f}')
else:
    print('ยังไม่มี Champion — เริ่ม Hunt ก่อน!')
"

# ── ทดสอบระบบ ────────────────────────────────────────
python -m pytest tests/ -v                            # รัน test ทั้งหมด
python scripts/check_ollama.py                        # ตรวจ Ollama

# ── เปิด/ปิด Auto-start daemon ──────────────────────
launchctl load ~/Library/LaunchAgents/com.aureus.trading.plist    # เปิด
launchctl unload ~/Library/LaunchAgents/com.aureus.trading.plist  # ปิด

# ── Cleanup (ล้างข้อมูลเก่า) ────────────────────────
rm -f logs/run_multi.pid logs/system_status.json      # ล้าง status
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null  # ล้าง cache
```

---

## 🔧 การแก้ปัญหาเบื้องต้น

### ปัญหา: Hunt ไม่เริ่ม / Dashboard ค้าง "Initializing..."
```bash
# ตรวจสอบว่ามี process ค้างอยู่
ps aux | grep run_multi | grep -v grep

# ถ้ามี — kill ทั้งหมดแล้วเริ่มใหม่
pkill -9 -f "run_multi.py"
rm -f logs/run_multi.pid logs/system_status.json
python scripts/run_multi.py --symbols XAUUSD --iterations 5
```

### ปัญหา: Hunt หยุดแล้ว แต่เปิดใหม่เอง
```bash
# ปิด launchd daemon
launchctl unload ~/Library/LaunchAgents/com.aureus.trading.plist
pkill -9 -f "run_multi.py"
```

### ปัญหา: Ollama ไม่ทำงาน
```bash
ollama serve                          # เริ่ม Ollama server
ollama list                           # ตรวจสอบ models
curl http://localhost:11434/api/tags  # ตรวจ API
```

### ปัญหา: ฐานข้อมูลไม่เชื่อมต่อ
```bash
docker ps | grep ai-db               # ตรวจ container
docker restart ai-db                  # รีสตาร์ท
```

### ปัญหา: Dashboard ไม่เปิด
```bash
killall streamlit 2>/dev/null         # ปิดตัวเก่า
streamlit run dashboard.py            # เปิดใหม่
```

---

## 🏆 ดูผล Champion

```bash
source venv/bin/activate
python -c "
import yaml
from core.champion_manager import ChampionManager
cfg = yaml.safe_load(open('config/system.yaml'))
cm = ChampionManager(cfg['database']['url'])
champ = cm.get_global_champion('XAUUSD')
if champ:
    print(f'🏆 Champion: v{champ[\"version\"]}')
    print(f'  PF  = {champ[\"profit_factor\"]:.2f}  (target > 1.3)')
    print(f'  DD  = {champ[\"max_drawdown_pct\"]:.1f}%  (target < 30%)')
    print(f'  RF  = {champ[\"recovery_factor\"]:.2f}  (target > 1.0)')
    print(f'  W/L = {champ[\"avg_win_loss_ratio\"]:.2f}  (target > 1.5)')
else:
    print('ยังไม่มี Champion — เริ่ม Hunt!')
"
```

---

## ⚠️ กฎสำคัญที่ห้ามละเมิด

1. **ห้ามใช้ FixedLossUSD** — สาเหตุที่ V4 ล้มเหลว (Drawdown 101%)
2. **Risk ต้องเป็น % เท่านั้น** — ค่าปัจจุบัน 0.5% ต่อเทรด
3. **R/R Ratio ต้องมากกว่า 2:1** — TP ต้องมากกว่า SL x 2
4. **อย่าแก้ไข** `core/constraint_validator.py` — ระบบป้องกัน V4 bug
5. **XAUUSD เท่านั้น** — ไม่ต้องเพิ่ม symbol อื่น (ยกเว้นพร้อมจริงๆ)

---

## 🚨 Safety Guards (อัตโนมัติ)

| กฎ | เงื่อนไข | การกระทำ |
|---|---|---|
| Emergency DD Stop | Drawdown > 20% | ปิดทุก Position ทันที |
| Equity Drop Stop | Equity ลด > 10% จากต้น Session | ปิดทุก Position ทันที |
| News Block | ข่าว High Impact ± 30 นาที | ปิด Position ชั่วคราว |
| Feedback Loop | Live PF < 1.2 หลัง 10 เทรด | กลับไป Backtest ใหม่ |

> ห้ามแก้ไข `agents/live_trade_agent.py` เพื่อผ่อนปรนเกณฑ์เหล่านี้

---

*เอกสารฉบับนี้อัปเดตล่าสุด: มีนาคม 2026 (XAUUSD Champion Hunter — Full Reset)*
