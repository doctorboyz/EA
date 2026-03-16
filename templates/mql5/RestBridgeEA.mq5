//+------------------------------------------------------------------+
//| RestBridgeEA.mq5                                                 |
//| Aureus AI — File-IPC Bridge between Python (macOS) and MT5      |
//|                                                                  |
//| HOW TO USE:                                                      |
//|   1. Compile this file in MetaEditor                             |
//|   2. Attach to any chart (e.g., EURUSD M1) — run permanently    |
//|   3. Python writes JSON to C:\bridge\requests\{uuid}.json        |
//|   4. EA processes on OnTimer(), writes C:\bridge\responses\      |
//|                                                                  |
//| SUPPORTED COMMANDS:                                              |
//|   ping, account_info, get_positions, get_history,               |
//|   open_trade, close_trade, close_all, modify_sl_tp, get_tick    |
//+------------------------------------------------------------------+
#property copyright   "Aureus AI"
#property version     "1.00"
#property description "File-IPC Bridge for Python automation"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\HistoryOrderInfo.mqh>

//--- Inputs
input int    BridgeMagicNumber = 99999;       // Magic number for this bridge EA
input string RequestFolder     = "bridge/requests/";   // Relative to MQL5\Files\
input string ResponseFolder    = "bridge/responses/";  // Relative to MQL5\Files\
input int    TimerIntervalMs   = 500;         // Poll interval in milliseconds

//--- Global objects
CTrade         g_trade;
CPositionInfo  g_pos;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(BridgeMagicNumber);
   g_trade.SetDeviationInPoints(20);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

   // Create directories if needed (MT5 creates relative to MQL5/Files/)
   // We use absolute paths via FileOpen with FILE_COMMON flag trick
   // Actually in Wine, C:\bridge\ is the literal path — use MQL5 file functions
   // with path relative to MQL5\Files\ OR use absolute FILE_ANSI paths

   EventSetMillisecondTimer(TimerIntervalMs);
   Print("RestBridgeEA started. Polling: ", RequestFolder);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("RestBridgeEA stopped. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Timer — polls request folder                                     |
//+------------------------------------------------------------------+
void OnTimer()
{
   // List all .json files in RequestFolder
   string filename;
   long   search_handle = FileFindFirst(RequestFolder + "*.json", filename);

   if(search_handle == INVALID_HANDLE)
      return; // No pending requests

   do {
      string req_path  = RequestFolder  + filename;
      string uuid_part = filename;
      StringReplace(uuid_part, ".json", "");
      string resp_path = ResponseFolder + uuid_part + ".json";

      // Read request
      string req_json = ReadFile(req_path);
      if(req_json == "")
         continue;

      // Delete request file before processing (prevents double-processing)
      FileDelete(req_path);

      // Process and write response
      string resp_json = ProcessCommand(req_json, uuid_part);
      WriteFile(resp_path, resp_json);

   } while(FileFindNext(search_handle, filename));

   FileFindClose(search_handle);
}

//+------------------------------------------------------------------+
//| Read entire file to string                                       |
//+------------------------------------------------------------------+
string ReadFile(const string path)
{
   int fh = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(fh == INVALID_HANDLE) return "";
   string content = "";
   while(!FileIsEnding(fh))
      content += FileReadString(fh);
   FileClose(fh);
   return content;
}

//+------------------------------------------------------------------+
//| Write string to file                                             |
//+------------------------------------------------------------------+
void WriteFile(const string path, const string content)
{
   int fh = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(fh == INVALID_HANDLE) {
      Print("WriteFile error: cannot open ", path, " error=", GetLastError());
      return;
   }
   FileWriteString(fh, content);
   FileClose(fh);
}

//+------------------------------------------------------------------+
//| Simple JSON value extractor (no library needed)                  |
//+------------------------------------------------------------------+
string JsonGet(const string json, const string key)
{
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   // Skip whitespace and colon
   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == ':'))
      pos++;
   if(pos >= StringLen(json)) return "";
   ushort first = StringGetCharacter(json, pos);
   if(first == '"') {
      // String value
      pos++;
      string val = "";
      while(pos < StringLen(json) && StringGetCharacter(json, pos) != '"') {
         val += ShortToString(StringGetCharacter(json, pos));
         pos++;
      }
      return val;
   } else {
      // Number/bool value
      string val = "";
      while(pos < StringLen(json) && StringGetCharacter(json, pos) != ',' && StringGetCharacter(json, pos) != '}' && StringGetCharacter(json, pos) != '\n') {
         val += ShortToString(StringGetCharacter(json, pos));
         pos++;
      }
      StringTrimLeft(val); StringTrimRight(val);
      return val;
   }
}

//+------------------------------------------------------------------+
//| Escape string for JSON output                                    |
//+------------------------------------------------------------------+
string JsonStr(const string s)
{
   string out = s;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   return "\"" + out + "\"";
}

//+------------------------------------------------------------------+
//| Format datetime as ISO 8601                                      |
//+------------------------------------------------------------------+
string FormatTime(datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d",
      dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec);
}

//+------------------------------------------------------------------+
//| Error response helper                                            |
//+------------------------------------------------------------------+
string ErrResponse(const string id, const int retcode, const string msg)
{
   return StringFormat("{\"id\":%s,\"status\":\"error\",\"retcode\":%d,\"message\":%s}",
      JsonStr(id), retcode, JsonStr(msg));
}

//+------------------------------------------------------------------+
//| OK response helper                                               |
//+------------------------------------------------------------------+
string OkResponse(const string id, const string body)
{
   return StringFormat("{\"id\":%s,\"status\":\"ok\",%s}", JsonStr(id), body);
}

//+------------------------------------------------------------------+
//| Process a single JSON command                                    |
//+------------------------------------------------------------------+
string ProcessCommand(const string json, const string req_id)
{
   string cmd = JsonGet(json, "cmd");
   Print("Bridge cmd=", cmd, " id=", req_id);

   if(cmd == "ping")            return CmdPing(req_id);
   if(cmd == "account_info")    return CmdAccountInfo(req_id);
   if(cmd == "get_positions")   return CmdGetPositions(req_id, json);
   if(cmd == "get_history")     return CmdGetHistory(req_id, json);
   if(cmd == "open_trade")      return CmdOpenTrade(req_id, json);
   if(cmd == "close_trade")     return CmdCloseTrade(req_id, json);
   if(cmd == "close_all")       return CmdCloseAll(req_id, json);
   if(cmd == "modify_sl_tp")    return CmdModifySlTp(req_id, json);
   if(cmd == "get_tick")        return CmdGetTick(req_id, json);
   if(cmd == "get_calendar")    return CmdGetCalendar(req_id, json);

   return ErrResponse(req_id, -1, "Unknown command: " + cmd);
}

//+------------------------------------------------------------------+
//| ping                                                             |
//+------------------------------------------------------------------+
string CmdPing(const string id)
{
   return OkResponse(id, StringFormat(
      "\"server_time\":%s,\"version\":\"1.0\",\"bridge_magic\":%d",
      JsonStr(FormatTime(TimeCurrent())), BridgeMagicNumber));
}

//+------------------------------------------------------------------+
//| account_info                                                     |
//+------------------------------------------------------------------+
string CmdAccountInfo(const string id)
{
   return OkResponse(id, StringFormat(
      "\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,\"free_margin\":%.2f,"
      "\"currency\":%s,\"leverage\":%d,\"server\":%s",
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_FREEMARGIN),
      JsonStr(AccountInfoString(ACCOUNT_CURRENCY)),
      (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
      JsonStr(AccountInfoString(ACCOUNT_SERVER))));
}

//+------------------------------------------------------------------+
//| get_positions                                                    |
//+------------------------------------------------------------------+
string CmdGetPositions(const string id, const string json)
{
   string magic_str = JsonGet(json, "magic");
   int filter_magic = (magic_str != "") ? (int)StringToInteger(magic_str) : -1;

   string items = "";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(filter_magic >= 0 && (int)PositionGetInteger(POSITION_MAGIC) != filter_magic)
         continue;
      if(items != "") items += ",";
      items += StringFormat(
         "{\"ticket\":%llu,\"symbol\":%s,\"order_type\":%s,"
         "\"volume\":%.2f,\"open_price\":%.5f,\"current_price\":%.5f,"
         "\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f,\"commission\":%.2f,"
         "\"swap\":%.2f,\"open_time\":%s,\"magic\":%d,\"comment\":%s}",
         ticket,
         JsonStr(PositionGetString(POSITION_SYMBOL)),
         JsonStr(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "buy" : "sell"),
         PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_PRICE_CURRENT),
         PositionGetDouble(POSITION_SL),
         PositionGetDouble(POSITION_TP),
         PositionGetDouble(POSITION_PROFIT),
         PositionGetDouble(POSITION_COMMISSION),
         PositionGetDouble(POSITION_SWAP),
         JsonStr(FormatTime((datetime)PositionGetInteger(POSITION_TIME))),
         (int)PositionGetInteger(POSITION_MAGIC),
         JsonStr(PositionGetString(POSITION_COMMENT)));
   }
   return OkResponse(id, "\"positions\":[" + items + "]");
}

//+------------------------------------------------------------------+
//| get_history                                                      |
//+------------------------------------------------------------------+
string CmdGetHistory(const string id, const string json)
{
   string from_str  = JsonGet(json, "from");
   string to_str    = JsonGet(json, "to");
   string magic_str = JsonGet(json, "magic");
   int filter_magic = (magic_str != "") ? (int)StringToInteger(magic_str) : -1;

   datetime from_dt = (from_str != "") ? StringToTime(from_str) : 0;
   datetime to_dt   = (to_str   != "") ? StringToTime(to_str)   : TimeCurrent();

   HistorySelect(from_dt, to_dt);

   string items = "";
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++) {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(filter_magic >= 0 && (int)HistoryDealGetInteger(ticket, DEAL_MAGIC) != filter_magic)
         continue;

      double profit   = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      double commission = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      double swap     = HistoryDealGetDouble(ticket, DEAL_SWAP);
      double price    = HistoryDealGetDouble(ticket, DEAL_PRICE);
      string symbol   = HistoryDealGetString(ticket, DEAL_SYMBOL);
      long   type     = HistoryDealGetInteger(ticket, DEAL_TYPE);
      double volume   = HistoryDealGetDouble(ticket, DEAL_VOLUME);
      datetime ctime  = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);

      // Find matching open deal for open_price and open_time
      ulong order_ticket = (ulong)HistoryDealGetInteger(ticket, DEAL_ORDER);
      double open_price  = price;
      datetime open_time = ctime;
      if(HistoryOrderSelect(order_ticket)) {
         open_price = HistoryOrderGetDouble(order_ticket, ORDER_PRICE_OPEN);
         open_time  = (datetime)HistoryOrderGetInteger(order_ticket, ORDER_TIME_SETUP);
      }

      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      double pips  = (point > 0) ? MathAbs(price - open_price) / (point * 10) : 0;

      if(items != "") items += ",";
      items += StringFormat(
         "{\"ticket\":%llu,\"symbol\":%s,\"order_type\":%s,"
         "\"volume\":%.2f,\"open_price\":%.5f,\"close_price\":%.5f,"
         "\"open_time\":%s,\"close_time\":%s,"
         "\"profit\":%.2f,\"commission\":%.2f,\"swap\":%.2f,\"pips\":%.1f,"
         "\"magic\":%d,\"comment\":%s}",
         ticket,
         JsonStr(symbol),
         JsonStr(type == DEAL_TYPE_BUY ? "buy" : "sell"),
         volume, open_price, price,
         JsonStr(FormatTime(open_time)),
         JsonStr(FormatTime(ctime)),
         profit, commission, swap, pips,
         (int)HistoryDealGetInteger(ticket, DEAL_MAGIC),
         JsonStr(HistoryDealGetString(ticket, DEAL_COMMENT)));
   }
   return OkResponse(id, "\"trades\":[" + items + "]");
}

//+------------------------------------------------------------------+
//| open_trade                                                       |
//+------------------------------------------------------------------+
string CmdOpenTrade(const string id, const string json)
{
   string symbol     = JsonGet(json, "symbol");
   string type_str   = JsonGet(json, "order_type");
   double volume     = StringToDouble(JsonGet(json, "volume"));
   double sl         = StringToDouble(JsonGet(json, "sl"));
   double tp         = StringToDouble(JsonGet(json, "tp"));
   int    magic      = (int)StringToInteger(JsonGet(json, "magic"));
   string comment    = JsonGet(json, "comment");

   g_trade.SetExpertMagicNumber(magic);

   bool ok = false;
   if(type_str == "buy")
      ok = g_trade.Buy(volume, symbol, 0, sl, tp, comment);
   else if(type_str == "sell")
      ok = g_trade.Sell(volume, symbol, 0, sl, tp, comment);
   else
      return ErrResponse(id, -2, "Invalid order_type: " + type_str);

   if(ok) {
      ulong ticket = g_trade.ResultDeal();
      return OkResponse(id, StringFormat("\"ticket\":%llu", ticket));
   } else {
      int    retcode = (int)g_trade.ResultRetcode();
      string retmsg  = g_trade.ResultRetcodeDescription();
      return ErrResponse(id, retcode, retmsg);
   }
}

//+------------------------------------------------------------------+
//| close_trade                                                      |
//+------------------------------------------------------------------+
string CmdCloseTrade(const string id, const string json)
{
   ulong ticket = (ulong)StringToInteger(JsonGet(json, "ticket"));
   if(!PositionSelectByTicket(ticket))
      return ErrResponse(id, -3, "Position not found: " + (string)ticket);

   bool ok = g_trade.PositionClose(ticket);
   if(ok)
      return OkResponse(id, "\"closed\":1");
   else
      return ErrResponse(id, (int)g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| close_all                                                        |
//+------------------------------------------------------------------+
string CmdCloseAll(const string id, const string json)
{
   string magic_str = JsonGet(json, "magic");
   int filter_magic = (magic_str != "") ? (int)StringToInteger(magic_str) : -1;
   int closed = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(filter_magic >= 0 && (int)PositionGetInteger(POSITION_MAGIC) != filter_magic)
         continue;
      if(g_trade.PositionClose(ticket))
         closed++;
   }
   return OkResponse(id, StringFormat("\"closed\":%d", closed));
}

//+------------------------------------------------------------------+
//| modify_sl_tp                                                     |
//+------------------------------------------------------------------+
string CmdModifySlTp(const string id, const string json)
{
   ulong  ticket = (ulong)StringToInteger(JsonGet(json, "ticket"));
   double sl     = StringToDouble(JsonGet(json, "sl"));
   double tp     = StringToDouble(JsonGet(json, "tp"));

   if(!PositionSelectByTicket(ticket))
      return ErrResponse(id, -3, "Position not found: " + (string)ticket);

   bool ok = g_trade.PositionModify(ticket, sl, tp);
   if(ok)
      return OkResponse(id, "\"modified\":true");
   else
      return ErrResponse(id, (int)g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| get_tick                                                         |
//+------------------------------------------------------------------+
string CmdGetTick(const string id, const string json)
{
   string symbol = JsonGet(json, "symbol");
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return ErrResponse(id, -4, "Cannot get tick for: " + symbol);

   double point   = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double digits  = (double)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double spread  = (point > 0) ? (tick.ask - tick.bid) / (point * 10) : 0;

   return OkResponse(id, StringFormat(
      "\"symbol\":%s,\"bid\":%.5f,\"ask\":%.5f,\"spread\":%.1f,\"time\":%s",
      JsonStr(symbol), tick.bid, tick.ask, spread,
      JsonStr(FormatTime(tick.time))));
}

//+------------------------------------------------------------------+
//| get_calendar                                                     |
//| Fetches high-impact EUR + USD events from MT5 built-in calendar  |
//| Request: {"cmd":"get_calendar","hours_ahead":168}               |
//| Response: {"events":[{"name":..,"time":..,"currency":..,"importance":..,"actual":..,"forecast":..,"previous":..}]}
//+------------------------------------------------------------------+
string CmdGetCalendar(const string id, const string json)
{
   string hours_str = JsonGet(json, "hours_ahead");
   int    hours     = (hours_str != "") ? (int)StringToInteger(hours_str) : 168; // 7 days default

   datetime from = TimeCurrent();
   datetime to   = from + (datetime)(hours * 3600);

   string items = "";

   // Country codes to check: "US" = USD, "EU" = EUR (ECB), "DE"/"FR" also affect EUR
   string country_codes[];
   ArrayResize(country_codes, 4);
   country_codes[0] = "US";
   country_codes[1] = "EU";
   country_codes[2] = "DE";
   country_codes[3] = "FR";

   string currency_labels[];
   ArrayResize(currency_labels, 4);
   currency_labels[0] = "USD";
   currency_labels[1] = "EUR";
   currency_labels[2] = "EUR";
   currency_labels[3] = "EUR";

   for(int c = 0; c < ArraySize(country_codes); c++)
   {
      MqlCalendarValue values[];
      int count = CalendarValueHistory(values, from, to, country_codes[c]);
      if(count <= 0) continue;

      for(int i = 0; i < count; i++)
      {
         MqlCalendarEvent evt;
         if(!CalendarEventById(values[i].event_id, evt)) continue;
         if(evt.importance != CALENDAR_IMPORTANCE_HIGH)  continue;

         // Decode actual / forecast / previous (stored as int * 10^digits)
         double divisor   = (evt.digits > 0) ? MathPow(10, evt.digits) : 1.0;
         string actual_s  = (values[i].actual_value   != LONG_MIN)
                            ? DoubleToString(values[i].actual_value   / divisor, evt.digits) : "null";
         string forecast_s= (values[i].forecast_value != LONG_MIN)
                            ? DoubleToString(values[i].forecast_value / divisor, evt.digits) : "null";
         string previous_s= (values[i].prev_value     != LONG_MIN)
                            ? DoubleToString(values[i].prev_value     / divisor, evt.digits) : "null";

         if(items != "") items += ",";
         items += StringFormat(
            "{\"name\":%s,\"time\":%s,\"currency\":%s,"
            "\"importance\":\"high\","
            "\"actual\":%s,\"forecast\":%s,\"previous\":%s}",
            JsonStr(evt.name),
            JsonStr(FormatTime(values[i].time)),
            JsonStr(currency_labels[c]),
            actual_s, forecast_s, previous_s
         );
      }
   }

   return OkResponse(id, "\"events\":[" + items + "]");
}
//+------------------------------------------------------------------+
