//+------------------------------------------------------------------+
//| Service: AutoSetSL                                               |
//| Chạy nền, không phụ thuộc chart, không bị disable khi đổi TF    |
//+------------------------------------------------------------------+
#property copyright "GitHub Copilot"
#property version   "3.00"
#property service

input double FixedSL_XAU = 1.0;    // Khoảng cách SL cho XAUUSD (USD)
input double FixedSL_BTC = 100.0;  // Khoảng cách SL cho BTCUSD (USD)
input double FixedSL_WTI = 0.5;    // Khoảng cách SL cho WTI/USOIL (USD)
input int    CheckIntervalMs = 2000; // Kiểm tra mỗi bao nhiêu ms

// Lưu ticket đã thất bại để tránh spam retry
struct FailedTicketInfo
  {
   ulong    ticket;
   int      retryCount;
   datetime lastAttempt;
  };

FailedTicketInfo g_failedTickets[];
const int        MAX_RETRIES    = 3;
const int        RETRY_COOLDOWN = 30; // giây

//+------------------------------------------------------------------+
//| Kiểm tra ticket đã bị block chưa                                |
//+------------------------------------------------------------------+
bool IsTicketBlocked(ulong ticket)
  {
   for(int i = 0; i < ArraySize(g_failedTickets); i++)
     {
      if(g_failedTickets[i].ticket == ticket)
        {
         if(g_failedTickets[i].retryCount >= MAX_RETRIES)
            return true;
         if(TimeCurrent() - g_failedTickets[i].lastAttempt < RETRY_COOLDOWN)
            return true;
         return false;
        }
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Ghi nhận ticket thất bại                                         |
//+------------------------------------------------------------------+
void RecordFailedTicket(ulong ticket)
  {
   for(int i = 0; i < ArraySize(g_failedTickets); i++)
     {
      if(g_failedTickets[i].ticket == ticket)
        {
         g_failedTickets[i].retryCount++;
         g_failedTickets[i].lastAttempt = TimeCurrent();
         return;
        }
     }
   int size = ArraySize(g_failedTickets);
   ArrayResize(g_failedTickets, size + 1);
   g_failedTickets[size].ticket      = ticket;
   g_failedTickets[size].retryCount  = 1;
   g_failedTickets[size].lastAttempt = TimeCurrent();
  }

//+------------------------------------------------------------------+
//| Xóa ticket thành công khỏi danh sách failed                     |
//+------------------------------------------------------------------+
void RemoveFailedTicket(ulong ticket)
  {
   for(int i = 0; i < ArraySize(g_failedTickets); i++)
     {
      if(g_failedTickets[i].ticket == ticket)
        {
         int last = ArraySize(g_failedTickets) - 1;
         if(i < last)
            g_failedTickets[i] = g_failedTickets[last];
         ArrayResize(g_failedTickets, last);
         return;
        }
     }
  }

//+------------------------------------------------------------------+
//| Dọn dẹp ticket không còn tồn tại                                |
//+------------------------------------------------------------------+
void CleanupStaleTickets()
  {
   for(int i = ArraySize(g_failedTickets) - 1; i >= 0; i--)
     {
      if(!PositionSelectByTicket(g_failedTickets[i].ticket))
        {
         int last = ArraySize(g_failedTickets) - 1;
         if(i < last)
            g_failedTickets[i] = g_failedTickets[last];
         ArrayResize(g_failedTickets, last);
        }
     }
  }

//+------------------------------------------------------------------+
//| Xác định khoảng cách SL cho symbol                              |
//+------------------------------------------------------------------+
double GetFixedSL(string symbol)
  {
   if(StringFind(symbol, "XAUUSD") >= 0)
      return FixedSL_XAU;
   if(StringFind(symbol, "BTCUSD") >= 0)
      return FixedSL_BTC;
   if(StringFind(symbol, "WTI") >= 0 || StringFind(symbol, "USOIL") >= 0 || StringFind(symbol, "OIL") >= 0)
      return FixedSL_WTI;
   return 0;
  }

//+------------------------------------------------------------------+
//| Xử lý đặt SL cho tất cả positions                              |
//+------------------------------------------------------------------+
void ProcessPositions()
  {
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
      return;

   // Dọn dẹp ticket cũ định kỳ
   static datetime lastCleanup = 0;
   if(TimeCurrent() - lastCleanup > 60)
     {
      CleanupStaleTickets();
      lastCleanup = TimeCurrent();
     }

   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      double sl     = PositionGetDouble(POSITION_SL);

      // Đã có SL rồi thì bỏ qua
      if(sl != 0)
         continue;

      // Xác định khoảng cách SL
      double fixed_sl = GetFixedSL(symbol);
      if(fixed_sl <= 0)
         continue;

      // Kiểm tra cooldown/max retry
      if(IsTicketBlocked(ticket))
         continue;

      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      long   type  = PositionGetInteger(POSITION_TYPE);

      double new_sl = 0;
      if(type == POSITION_TYPE_BUY)
         new_sl = price - fixed_sl;
      else if(type == POSITION_TYPE_SELL)
         new_sl = price + fixed_sl;
      else
         continue;

      // Lấy thông tin symbol
      int    sym_digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      double sym_point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
      double bid        = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask        = SymbolInfoDouble(symbol, SYMBOL_ASK);

      // Kiểm tra market data có sẵn không
      if(bid <= 0 || ask <= 0 || sym_point <= 0)
         continue;

      new_sl = NormalizeDouble(new_sl, sym_digits);

      // Kiểm tra STOPLEVEL
      long   stopLevelPoints = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
      double stopLevel       = stopLevelPoints * sym_point;

      if(stopLevel > 0)
        {
         if(type == POSITION_TYPE_BUY && (bid - new_sl) < stopLevel)
           {
            new_sl = NormalizeDouble(bid - stopLevel - sym_point, sym_digits);
            Print("Điều chỉnh SL BUY #", ticket, " do STOPLEVEL. SL=", new_sl);
           }
         else if(type == POSITION_TYPE_SELL && (new_sl - ask) < stopLevel)
           {
            new_sl = NormalizeDouble(ask + stopLevel + sym_point, sym_digits);
            Print("Điều chỉnh SL SELL #", ticket, " do STOPLEVEL. SL=", new_sl);
           }
        }

      // Validate SL logic
      if(type == POSITION_TYPE_BUY && new_sl >= bid)
        {
         Print("SL BUY #", ticket, " >= bid (", new_sl, " >= ", bid, "). Bỏ qua.");
         RecordFailedTicket(ticket);
         continue;
        }
      if(type == POSITION_TYPE_SELL && new_sl <= ask)
        {
         Print("SL SELL #", ticket, " <= ask (", new_sl, " <= ", ask, "). Bỏ qua.");
         RecordFailedTicket(ticket);
         continue;
        }

      if(new_sl <= 0)
        {
         Print("SL không hợp lệ cho lệnh #", ticket, ": ", new_sl);
         RecordFailedTicket(ticket);
         continue;
        }

      double existing_tp = PositionGetDouble(POSITION_TP);

      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      ZeroMemory(res);

      req.action   = TRADE_ACTION_SLTP;
      req.position = ticket;
      req.symbol   = symbol;
      req.sl       = new_sl;
      req.tp       = existing_tp;

      ResetLastError();
      bool sent = OrderSend(req, res);

      if(!sent || res.retcode != TRADE_RETCODE_DONE)
        {
         Print("LỖI đặt SL #", ticket,
               " | SL=", new_sl,
               " | TP=", existing_tp,
               " | Err=", GetLastError(),
               " | Retcode=", res.retcode,
               " | ", symbol,
               " | Bid=", bid, " Ask=", ask);
         RecordFailedTicket(ticket);
        }
      else
        {
         Print("OK đặt SL #", ticket,
               " = ", DoubleToString(new_sl, sym_digits),
               " (", symbol, ")");
         RemoveFailedTicket(ticket);
        }
     }
  }

//+------------------------------------------------------------------+
//| Service main function — vòng lặp chạy mãi                      |
//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== AutoSetSL SERVICE v3.00 STARTED ===");
   Print("SL_XAU=", FixedSL_XAU, " SL_BTC=", FixedSL_BTC, " SL_WTI=", FixedSL_WTI);
   Print("CheckInterval=", CheckIntervalMs, "ms, MaxRetries=", MAX_RETRIES, ", Cooldown=", RETRY_COOLDOWN, "s");

   ArrayResize(g_failedTickets, 0);

   while(!IsStopped())
     {
      ProcessPositions();
      Sleep(CheckIntervalMs);
     }

   Print("=== AutoSetSL SERVICE STOPPED ===");
  }
//+------------------------------------------------------------------+
