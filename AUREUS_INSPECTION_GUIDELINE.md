# 🔍 Aureus Systematic: Report Inspection Guideline

Use this guide to analyze backtest results and identify why an EA is winning or losing.

---

## 1. The "Edge" Metrics (Profitability)
| Metric | Goal | Meaning |
| :--- | :--- | :--- |
| **Profit Factor** | > 1.5 | Ratio of Gross Profit to Gross Loss. |
| **Avg Win / Avg Loss** | > 2.0 | You want "Fat Winners" and "Skinny Losers." |
| **Recovery Factor** | > 3.0 | How many times the profit exceeds the drawdown. |

---

## 2. The "Survival" Metrics (Risk)
| Metric | Safety Limit | Meaning |
| :--- | :--- | :--- |
| **Max Drawdown %** | < 15% | The maximum "dip" in your balance. |
| **Consec. Losses** | < 8 | How many $10 shots you might lose in a row. |
| **Margin Level** | > 500% | Ensures you don't get a Margin Call from the broker. |

---

## 3. Behavioral Analysis
- **Holding Time:** If winners are held for 1 hour but losers for 10 hours, the EA is "praying" for a reversal. **This is bad.**
- **Entry Precision:** Check if trades open exactly at the RSI extreme or if price keeps going against you for 50 pips after entry. If it keeps going, the **Stop Loss** needs to be wider or the **Entry Trigger** needs more confirmation.

---

## 4. GitHub Workflow
To save your work:
1. `git add .`
2. `git commit -m "Describe your changes"`
3. `git push origin main`

To get work back:
1. `git pull origin main`

### "Data tells you what happened. Math tells you what will happen next."
*Aureus Trading - 2026*
