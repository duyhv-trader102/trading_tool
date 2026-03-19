//+------------------------------------------------------------------+
//| Expert Advisor: AutoSetSL                                        |
//+------------------------------------------------------------------+
#property copyright "GitHub Copilot"
#property version   "1.20"
#property strict

#include <Trade\Trade.mqh>

input double FixedSL_XAU = 1.0;    // Khoảng cách SL cho XAUUSD (USD)
input double FixedSL_BTC = 100.0;  // Khoảng cách SL cho BTCUSD (USD)
input double FixedSL_WTI = 0.5;    // Khoảng cách SL cho WTI/USOIL (USD)

// Lưu ticket đã thất bại để tránh spam retry mỗi tick
struct FailedTicket
  {
   ulong ticket;
   int   retryCount;
   datetime lastAttempt;
  };

FailedTicket g_failedTickets[];
int          g_maxRetries = 3;        // Số lần thử tối đa cho mỗi lệnh
int          g_retryCooldownSec = 30; // Chờ 30 giây giữa các lần thử

//+------------------------------------------------------------------+
//| Kiểm tra ticket đã thất bại quá nhiều lần chưa                  |
//+------------------------------------------------------------------+
bool IsTicketBlocked(ulong ticket)
  {
   for(int i = 0; i < ArraySize(g_failedTickets); i++)
     {
      if(g_failedTickets[i].ticket == ticket)
        {
         // Đã vượt quá số lần retry
         if(g_failedTickets[i].retryCount >= g_maxRetries)
            return true;
         // Chưa hết cooldown
         if(TimeCurrent() - g_failedTickets[i].lastAttempt < g_retryCooldownSec)
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
   // Thêm mới
   int size = ArraySize(g_failedTickets);
   ArrayResize(g_failedTickets, size + 1);
   g_failedTickets[size].ticket      = ticket;
   g_failedTickets[size].retryCount  = 1;
   g_failedTickets[size].lastAttempt = TimeCurrent();
  }

//+------------------------------------------------------------------+
//| Xóa ticket đã thành công khỏi danh sách failed                  |
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
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("AutoSetSL EA started. SL_XAU=", FixedSL_XAU, " SL_BTC=", FixedSL_BTC, " SL_WTI=", FixedSL_WTI);
   ArrayResize(g_failedTickets, 0);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   Print("AutoSetSL EA stopped. Reason=", reason);
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   // Kiểm tra quyền trade
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

   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      double sl     = PositionGetDouble(POSITION_SL);
      double price  = PositionGetDouble(POSITION_PRICE_OPEN);
      long   type   = PositionGetInteger(POSITION_TYPE);

      // Xác định khoảng cách SL theo symbol
      double fixed_sl = 0;
      if(StringFind(symbol, "XAUUSD") == 0)
         fixed_sl = FixedSL_XAU;
      else if(StringFind(symbol, "BTCUSD") == 0)
         fixed_sl = FixedSL_BTC;
      else if(StringFind(symbol, "WTI") >= 0 || StringFind(symbol, "USOIL") >= 0 || StringFind(symbol, "OIL") >= 0)
         fixed_sl = FixedSL_WTI;
      else
         continue; // Symbol không hỗ trợ

      if(sl != 0)
         continue;

      // Kiểm tra cooldown/max retry
      if(IsTicketBlocked(ticket))
         continue;

      double new_sl = 0;
      if(type == POSITION_TYPE_BUY)
         new_sl = price - fixed_sl;
      else if(type == POSITION_TYPE_SELL)
         new_sl = price + fixed_sl;
      else
         continue;

      // Normalize SL theo đúng digits của symbol
      int sym_digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      new_sl = NormalizeDouble(new_sl, sym_digits);

      // Kiểm tra SL có hợp lệ (cách giá hiện tại ít nhất STOPLEVEL)
      double stopLevel = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(symbol, SYMBOL_POINT);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);

      if(type == POSITION_TYPE_BUY && bid - new_sl < stopLevel)
        {
         new_sl = NormalizeDouble(bid - stopLevel, sym_digits);
         Print("Điều chỉnh SL cho lệnh BUY #", ticket, " do STOPLEVEL. SL mới=", new_sl);
        }
      else if(type == POSITION_TYPE_SELL && new_sl - ask < stopLevel)
        {
         new_sl = NormalizeDouble(ask + stopLevel, sym_digits);
         Print("Điều chỉnh SL cho lệnh SELL #", ticket, " do STOPLEVEL. SL mới=", new_sl);
        }

      // Kiểm tra SL > 0
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
         Print("Lỗi đặt SL cho lệnh #", ticket,
               " | SL=", new_sl,
               " | TP=", existing_tp,
               " | Error=", GetLastError(),
               " | Retcode=", res.retcode,
               " | Symbol=", symbol);
         RecordFailedTicket(ticket);
        }
      else
        {
         Print("Đã đặt SL cho lệnh #", ticket,
               " tại ", DoubleToString(new_sl, sym_digits),
               " (", symbol, ")");
         RemoveFailedTicket(ticket);
        }
     }
  }
//+------------------------------------------------------------------+
