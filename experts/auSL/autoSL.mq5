//+------------------------------------------------------------------+
//| Expert Advisor: AutoSetSL_XAUUSD                                 |
//+------------------------------------------------------------------+
#property copyright "GitHub Copilot"
#property version   "1.00"
#property strict

input double FixedSL = 1.0; // Khoảng cách SL theo giá (ví dụ: 1 USD)

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("AutoSetSL_XAUUSD EA started.");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   Print("AutoSetSL_XAUUSD EA stopped.");
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
         long type     = PositionGetInteger(POSITION_TYPE);

         // Chỉ áp dụng cho các symbol chứa "XAUUSD" và lệnh chưa có SL
         if(StringFind(symbol, "XAUUSD") == 0 && sl == 0)
           {
            double new_sl = 0;
            if(type == POSITION_TYPE_BUY)
               new_sl = price - FixedSL;
            else if(type == POSITION_TYPE_SELL)
               new_sl = price + FixedSL;
            else
               continue;

            double existing_tp = PositionGetDouble(POSITION_TP); // Giữ nguyên TP hiện tại

            MqlTradeRequest req;
            MqlTradeResult  res;
            ZeroMemory(req);

            req.action   = TRADE_ACTION_SLTP;
            req.position = ticket;
            req.symbol   = symbol;
            req.sl       = new_sl;
            req.tp       = existing_tp; // Không xóa TP

            if(!OrderSend(req, res))
               Print("Lỗi đặt SL cho lệnh #", ticket, " - ", GetLastError(), " - retcode: ", res.retcode);
            else
               Print("Đã đặt SL cho lệnh #", ticket, " tại mức ", DoubleToString(new_sl, Digits()));
           }
        }
     }
  }
//+------------------------------------------------------------------+
