//+------------------------------------------------------------------+
//|                                     Aureus_H1_Systematic_v2.mq5  |
//|                               Copyright 2026, Aureus Trading     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property version   "2.0-PRO"
#property strict

// --- AUREUS SYSTEMATIC v2.0 INPUTS (H1 Investment Grade) ---
input int      MagicNumber          = 20260111; 
input double   RiskPercent          = 1.0;      
input double   MaxSpreadPips        = 2.0;      
input int      StopLossPips         = 30;       
input int      TakeProfitPips       = 90;       
input int      BreakEvenPips        = 15;       
input int      TrailingStopPips     = 20;       
input int      RSI_Period           = 14;       
input int      LookbackPeriod       = 120;      
input int      ATR_Period           = 14;       // ATR for volatility protection
input double   ATR_MaxLimit         = 0.0035;   // Filter out high volatility noise

// Globale Variablen (MQL5 Handles)
int handleRSI = INVALID_HANDLE;
int handleATR = INVALID_HANDLE;
datetime lastTradeBar = 0;
datetime lastModifyTime = 0; 

int OnInit() { 
   // Initialize handles in OnInit
   handleRSI = iRSI(_Symbol, _Period, RSI_Period, PRICE_CLOSE);
   handleATR = iATR(_Symbol, _Period, ATR_Period);

   if(handleRSI == INVALID_HANDLE || handleATR == INVALID_HANDLE) {
      Print("Fehler beim Erstellen der Indikator-Handles");
      return(INIT_FAILED);
   }
   return(INIT_SUCCEEDED); 
}

void OnDeinit(const int reason) { 
   IndicatorRelease(handleRSI);
   IndicatorRelease(handleATR);
   Comment(""); 
   ObjectsDeleteAll(0, "TiefstLine"); 
   ObjectsDeleteAll(0, "HoechstLine"); 
}

void OnTick() {
   // Get values from handles
   double rsiBuffer[];
   double atrBuffer[];
   ArraySetAsSeries(rsiBuffer, true);
   ArraySetAsSeries(atrBuffer, true);

   if(CopyBuffer(handleRSI, 0, 0, 1, rsiBuffer) <= 0 || CopyBuffer(handleATR, 0, 0, 1, atrBuffer) <= 0) return;

   double currentRSI = rsiBuffer[0];
   double currentATR = atrBuffer[0];
   double currentSpread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) / 10.0;
   
   Comment("=== Aureus H1 v2.0 ===\nATR Volatility: " + DoubleToString(currentATR, 5) + "\nRSI: " + DoubleToString(currentRSI, 2) + "\nSpread: " + DoubleToString(currentSpread, 1));

   if(TimeCurrent() - lastModifyTime >= 3) ManagePositionsSafe();
   CheckForEarlyExit(currentRSI);

   if(PositionsTotal() == 0) {
      if(currentSpread > MaxSpreadPips) return;
      
      int lowIdx = iLowest(_Symbol, _Period, MODE_LOW, LookbackPeriod, 1);
      int highIdx = iHighest(_Symbol, _Period, MODE_HIGH, LookbackPeriod, 1);
      double tiefst = iLow(_Symbol, _Period, lowIdx);
      double hoechst = iHigh(_Symbol, _Period, highIdx);

      datetime currentBar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
      if(currentBar == lastTradeBar) return;

      double closePrice = iClose(_Symbol, _Period, 0);
      double buffer = 5 * 10.0 * _Point;

      // SURGICAL ADJ: Skip entry if ATR is too high (market is too chaotic)
      if(currentATR > ATR_MaxLimit) return; 

      if(closePrice <= (tiefst + buffer) && currentRSI < 30.0) ExecuteTrade(ORDER_TYPE_BUY);
      else if(closePrice >= (hoechst - buffer) && currentRSI > 70.0) ExecuteTrade(ORDER_TYPE_SELL);
   }
}

void ManagePositionsSafe() {
   double stopLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   double freezeLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL) * _Point;
   double minDistance = stopLevel + (2.0 * 10.0 * _Point);

   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket)) {
         if(PositionGetInteger(POSITION_MAGIC) == MagicNumber) {
            double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
            double currentSL = PositionGetDouble(POSITION_SL);
            double currentTP = PositionGetDouble(POSITION_TP);
            double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
            double newSL = currentSL;
            bool modify = false;

            if(MathAbs(bid - currentSL) <= freezeLevel || MathAbs(bid - currentTP) <= freezeLevel) return;

            if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) {
               if(bid >= openPrice + (BreakEvenPips * 10.0 * _Point) && currentSL < openPrice) newSL = openPrice + (2.0 * 10.0 * _Point);
               double trailPrice = NormalizeDouble(bid - (TrailingStopPips * 10.0 * _Point), _Digits);
               if(trailPrice > newSL + (3.0 * 10.0 * _Point)) newSL = trailPrice;
               if(newSL > currentSL + _Point && bid > newSL + minDistance) modify = true;
            } else {
               if(ask <= openPrice - (BreakEvenPips * 10.0 * _Point) && (currentSL > openPrice || currentSL == 0)) newSL = openPrice - (2.0 * 10.0 * _Point);
               double trailPrice = NormalizeDouble(ask + (TrailingStopPips * 10.0 * _Point), _Digits);
               if((trailPrice < newSL - (3.0 * 10.0 * _Point) || newSL == 0)) newSL = trailPrice;
               if((newSL < currentSL || currentSL == 0) && ask < newSL - minDistance) modify = true;
            }

            if(modify) {
               MqlTradeRequest req = {}; MqlTradeResult res = {};
               req.action = TRADE_ACTION_SLTP; req.position = ticket; req.symbol = _Symbol;
               req.sl = NormalizeDouble(newSL, _Digits); req.tp = currentTP;
               if(OrderSend(req, res)) lastModifyTime = TimeCurrent();
            }
         }
      }
   }
}

void ExecuteTrade(ENUM_ORDER_TYPE t) {
   double lot = CalculateLotSize();
   if(lot <= 0) return;

   MqlTradeRequest r = {}; MqlTradeResult res = {};
   r.action = TRADE_ACTION_DEAL; r.symbol = _Symbol; r.volume = lot;
   r.magic = MagicNumber; r.type = t;
   r.price = (t == ORDER_TYPE_BUY) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   r.sl = (t == ORDER_TYPE_BUY) ? NormalizeDouble(r.price - (StopLossPips*10*_Point), _Digits) : NormalizeDouble(r.price + (StopLossPips*10*_Point), _Digits);
   r.tp = (t == ORDER_TYPE_BUY) ? NormalizeDouble(r.price + (TakeProfitPips*10*_Point), _Digits) : NormalizeDouble(r.price - (TakeProfitPips*10*_Point), _Digits);
   r.type_filling = GetFillingMode();
   r.deviation = 10;
   
   if(!OrderSend(r, res)) Print("Trade-Fehler: ", res.retcode);
   else lastTradeBar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
}

double CalculateLotSize() {
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE); 
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   
   double lot = (balance * (RiskPercent / 100.0)) / (StopLossPips * 10.0 * tickVal);
   
   double marginRequired;
   if(!OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, 1.0, SymbolInfoDouble(_Symbol, SYMBOL_ASK), marginRequired)) {
      marginRequired = 250.0; 
   }
   
   if(marginRequired > 0) {
      double maxLotPossible = freeMargin / marginRequired;
      if(lot > maxLotPossible) lot = maxLotPossible * 0.90; 
   }

   double stepL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   
   lot = MathRound(lot / stepL) * stepL;
   if(lot < minL) lot = minL;
   if(lot > maxL) lot = maxL;

   if(!OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, lot, SymbolInfoDouble(_Symbol, SYMBOL_ASK), marginRequired) || marginRequired > freeMargin) {
      return 0; 
   }

   return lot;
}

ENUM_ORDER_TYPE_FILLING GetFillingMode() {
   long filling = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
   if((filling & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

void ClosePosition(ulong ticket) {
   MqlTradeRequest req = {}; MqlTradeResult res = {};
   if(PositionSelectByTicket(ticket)) {
      req.action = TRADE_ACTION_DEAL; req.position = ticket; req.symbol = _Symbol;
      req.volume = PositionGetDouble(POSITION_VOLUME);
      req.type = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.price = (req.type == ORDER_TYPE_SELL) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      req.type_filling = GetFillingMode();
      if(!OrderSend(req, res)) Print("Close-Fehler: ", res.retcode);
   }
}

void CheckForEarlyExit(double rsi) {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t) && PositionGetInteger(POSITION_MAGIC) == MagicNumber) {
         long type = PositionGetInteger(POSITION_TYPE);
         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         double currentPrice = (type == POSITION_TYPE_BUY) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double profitPips = (type == POSITION_TYPE_BUY) ? (currentPrice - openPrice) : (openPrice - currentPrice);
         profitPips /= (10.0 * _Point);

         // SURGICAL FIX: Only exit via RSI if we are in at least 5 pips of profit
         if(profitPips >= 5.0) {
            if((type == POSITION_TYPE_BUY && rsi > 70.0) || (type == POSITION_TYPE_SELL && rsi < 30.0)) ClosePosition(t);
         }
      }
   }
}
