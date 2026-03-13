//+------------------------------------------------------------------+
//|                                     Aureus_Trend_Hunter_4.mq5    |
//|                               Copyright 2026, Aureus Trading     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property version   "4.00"
#property strict

// --- AUREUS TREND HUNTER 4 (High Accuracy Mode) ---
input int      MagicNumber          = 20260401; 
input double   FixedLossUSD         = 10.0;     // Loss per shot
input double   MaxSpreadPips        = 2.5;      
input int      StopLossPips         = 40;       
input int      TakeProfitPips       = 120;      
input int      TrailingStartPips    = 35;       // Start trailing after +3.5 USD profit
input int      TrailingStepPips     = 5;        
input int      ADX_MinStrength      = 25;       // Only trade strong trends
input int      EMA_LongTerm         = 200;      // H1 Trend
input int      EMA_H4_Filter        = 50;       // H4 Trend

// Handles
int handleRSI, handleATR, handleADX, handleEMA_H1, handleEMA_H4;

int OnInit() { 
   handleRSI    = iRSI(_Symbol, _Period, 14, PRICE_CLOSE);
   handleATR    = iATR(_Symbol, _Period, 14);
   handleADX    = iADX(_Symbol, _Period, 14);
   handleEMA_H1 = iMA(_Symbol, _Period, EMA_LongTerm, 0, MODE_EMA, PRICE_CLOSE);
   handleEMA_H4 = iMA(_Symbol, PERIOD_H4, EMA_H4_Filter, 0, MODE_EMA, PRICE_CLOSE);

   // COMPREHENSIVE HANDLE CHECK
   if(handleRSI == INVALID_HANDLE || handleATR == INVALID_HANDLE || 
      handleADX == INVALID_HANDLE || handleEMA_H1 == INVALID_HANDLE || 
      handleEMA_H4 == INVALID_HANDLE) {
      Print("Error creating indicator handles");
      return(INIT_FAILED);
   }
   return(INIT_SUCCEEDED); 
}

void OnDeinit(const int reason) { 
   IndicatorRelease(handleRSI); IndicatorRelease(handleATR);
   IndicatorRelease(handleADX); IndicatorRelease(handleEMA_H1); IndicatorRelease(handleEMA_H4);
}

void OnTick() {
   double rsi[], adx[], emaH1[], emaH4[];
   ArraySetAsSeries(rsi, true); ArraySetAsSeries(adx, true);
   ArraySetAsSeries(emaH1, true); ArraySetAsSeries(emaH4, true);

   if(CopyBuffer(handleRSI, 0, 0, 1, rsi) <= 0 || CopyBuffer(handleADX, 0, 0, 1, adx) <= 0 ||
      CopyBuffer(handleEMA_H1, 0, 0, 1, emaH1) <= 0 || CopyBuffer(handleEMA_H4, 0, 0, 1, emaH4) <= 0) return;

   double curRSI = rsi[0];
   double curADX = adx[0];
   double curEMA = emaH1[0];
   double h4EMA  = emaH4[0];
   double closePrice  = iClose(_Symbol, _Period, 0);
   double spread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) / 10.0;

   // Display Strategy Dashboard
   string trendTxt = (closePrice > h4EMA) ? "BULLISH" : "BEARISH";
   string adxTxt = (curADX > ADX_MinStrength) ? " [READY]" : " [WEAK]";
   
   string status = "=== AUREUS 4 SNIPER ===\n";
   status += "Trend Power (ADX): " + DoubleToString(curADX, 1) + adxTxt + "\n";
   status += "H4 Filter: " + trendTxt + "\n";
   status += "Shot Risk: $" + DoubleToString(FixedLossUSD, 2);
   Comment(status);

   ManageTrailing();

   if(PositionsTotal() == 0) {
      if(spread > MaxSpreadPips) return;
      if(curADX < ADX_MinStrength) return; // SKIP WEAK TRENDS

      // BUY SIGNAL: H1 Trend UP + H4 Trend UP + RSI Pullback
      if(closePrice > curEMA && closePrice > h4EMA && curRSI < 35.0) {
         ExecuteTrade(ORDER_TYPE_BUY);
      }
      // SELL SIGNAL: H1 Trend DOWN + H4 Trend DOWN + RSI Pullback
      else if(closePrice < curEMA && closePrice < h4EMA && curRSI > 65.0) {
         ExecuteTrade(ORDER_TYPE_SELL);
      }
   }
}

void ExecuteTrade(ENUM_ORDER_TYPE t) {
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tickVal <= 0) return;
   
   double lot = FixedLossUSD / (StopLossPips * 10.0 * tickVal);
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double stepL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   
   lot = MathRound(lot / stepL) * stepL;
   if(lot < minL) lot = minL;
   if(lot > maxL) lot = maxL;

   MqlTradeRequest r = {}; MqlTradeResult res = {};
   r.action = TRADE_ACTION_DEAL; r.symbol = _Symbol; r.volume = lot;
   r.magic = MagicNumber; r.type = t;
   r.price = (t == ORDER_TYPE_BUY) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   r.sl = (t == ORDER_TYPE_BUY) ? NormalizeDouble(r.price - (StopLossPips*10*_Point), _Digits) : NormalizeDouble(r.price + (StopLossPips*10*_Point), _Digits);
   r.tp = (t == ORDER_TYPE_BUY) ? NormalizeDouble(r.price + (TakeProfitPips*10*_Point), _Digits) : NormalizeDouble(r.price - (TakeProfitPips*10*_Point), _Digits);
   r.type_filling = ORDER_FILLING_IOC;
   r.deviation = 10;
   
   if(!OrderSend(r, res)) {
      Print("Trade execution error: ", res.retcode);
   }
}

void ManageTrailing() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) && PositionGetInteger(POSITION_MAGIC) == MagicNumber) {
         double openP = PositionGetDouble(POSITION_PRICE_OPEN);
         double slP = PositionGetDouble(POSITION_SL);
         double tpP = PositionGetDouble(POSITION_TP);
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) {
            if(bid > openP + (TrailingStartPips * 10.0 * _Point)) {
               double newSL = NormalizeDouble(bid - (TrailingStartPips * 10.0 * _Point), _Digits);
               if(newSL > slP + (TrailingStepPips * 10.0 * _Point)) {
                  ModifyPosition(t, newSL, tpP);
               }
            }
         } else {
            if(ask < openP - (TrailingStartPips * 10.0 * _Point)) {
               double newSL = NormalizeDouble(ask + (TrailingStartPips * 10.0 * _Point), _Digits);
               if(slP == 0 || newSL < slP - (TrailingStepPips * 10.0 * _Point)) {
                  ModifyPosition(t, newSL, tpP);
               }
            }
         }
      }
   }
}

void ModifyPosition(ulong t, double sl, double tp) {
   MqlTradeRequest req = {}; MqlTradeResult res = {};
   req.action = TRADE_ACTION_SLTP; req.position = t;
   req.symbol = _Symbol;
   req.sl = sl; req.tp = tp;
   if(!OrderSend(req, res)) {
      // Quietly fail or log if critical
   }
}
