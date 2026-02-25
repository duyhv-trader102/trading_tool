//+------------------------------------------------------------------+
//| Expert Advisor: AutoSetSL_XAUUSD_BTCUSD                          |
//+------------------------------------------------------------------+
#property copyright "GitHub Copilot"
#property version   "2.00"
#property strict

input double FixedSL_XAU = 1.0;    // Khoảng cách SL cho XAUUSD (USD)
input double FixedSL_BTC = 100.0;  // Khoảng cách SL cho BTCUSD (USD)

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("AutoSetSL_XAUUSD_BTCUSD EA started.");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   Print("AutoSetSL_XAUUSD_BTCUSD EA stopped.");
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   for(int i=0; i<PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
        {
         string symbol = PositionGetString(POSITION_SYMBOL);
         double sl     = PositionGetDouble(POSITION_SL);
         double price  = PositionGetDouble(POSITION_PRICE_OPEN);
         int type      = PositionGetInteger(POSITION_TYPE);

         double fixed_sl = 0;
         // Xác định khoảng cách SL theo symbol
         if(StringFind(symbol, "XAUUSD") == 0)
            fixed_sl = FixedSL_XAU;
         else if(StringFind(symbol, "BTCUSD") == 0)
            fixed_sl = FixedSL_BTC;
         else
            continue; // Không phải XAUUSD hoặc BTCUSD thì bỏ qua

         // Chỉ đặt SL cho lệnh chưa có SL
         if(sl == 0)
           {
            double new_sl = 0;
            if(type == POSITION_TYPE_BUY)
               new_sl = price - fixed_sl;
            else if(type == POSITION_TYPE_SELL)
               new_sl = price + fixed_sl;
            else
               continue;

            MqlTradeRequest req;
            MqlTradeResult  res;
            ZeroMemory(req);

            req.action   = TRADE_ACTION_SLTP;
            req.position = ticket;
            req.symbol   = symbol;
            req.sl       = new_sl;

            if(!OrderSend(req, res))
               Print("Lỗi đặt SL cho lệnh #", ticket, " - ", GetLastError(), " - retcode: ", res.retcode);
            else
               Print("Đã đặt SL cho lệnh #", ticket, " tại mức ", DoubleToString(new_sl, Digits()), " (", symbol, ")");
           }
        }
     }
  }
//+
