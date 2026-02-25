//+------------------------------------------------------------------+
//|                Trader Helper: Candle Timer & RR Display         |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0
#include <ChartObjects\ChartObjectsTxtControls.mqh>

input int TimerFontSize = 18;
input color TimerColor = clrBlack;
input int RRFontSize = 16;
input color RRColor = clrGold;
input int TimerXDistance = 1000; // Dịch timer sang phải (pixel, tính từ góc trái)
input int TimerYDistance = 20;   // Dịch timer xuống dưới (pixel)

string timerLabel = "CandleTimer";
string rrLabel = "RRLabel";

//--- Hàm lấy thời gian còn lại đến khi đóng nến hiện tại
string GetCandleTimeLeft()
{
   datetime now = TimeCurrent();
   datetime candleOpen = iTime(_Symbol, _Period, 0);
   int tfSec = PeriodSeconds(_Period);
   long left = candleOpen + tfSec - now;
   if(left < 0) left = 0;
   int m = (int)(left / 60);
   int s = (int)(left % 60);
   return StringFormat("%02d:%02d", m, s);
}

//--- Hàm tính RR của lệnh đang mở (nếu có)
string GetRR()
{
   double rr = 0;
   int total = PositionsTotal();
   for(int i=0; i<total; i++)
   {
      if(PositionGetSymbol(i) == _Symbol)
      {
         double entry = PositionGetDouble(POSITION_PRICE_OPEN);
         double sl = PositionGetDouble(POSITION_SL);
         double tp = PositionGetDouble(POSITION_TP);
         long type = PositionGetInteger(POSITION_TYPE);
         if(sl > 0 && tp > 0)
         {
            double risk = MathAbs(entry - sl);
            double reward = MathAbs(tp - entry);
            if(risk > 0) rr = reward / risk;
            break;
         }
      }
   }
   if(rr > 0) return "RR=1:" + DoubleToString(rr,2);
   else return "RR=--";
}

//--- Hiển thị timer bằng OBJ_LABEL ở góc phải trên
void DrawTimerLabel(string text, color clr, int fontsize, int xdist, int ydist) {
   string name = timerLabel + "_LABEL";
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_CORNER, 0); // CORNER_LEFT_UPPER
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, xdist);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, ydist);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontsize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
}

int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   // Hiển thị timer ở góc phải trên
   string timer = GetCandleTimeLeft();
   DrawTimerLabel(timer, TimerColor, TimerFontSize, TimerXDistance, TimerYDistance);

   // Hiển thị RR ở góc phải trên, lệch xuống dưới timer
   string rr = GetRR();
   if(ObjectFind(0, rrLabel) < 0)
      ObjectCreate(0, rrLabel, OBJ_LABEL, 0, 0, 0);
   ObjectSetString(0, rrLabel, OBJPROP_TEXT, rr);
   ObjectSetInteger(0, rrLabel, OBJPROP_CORNER, 0); // CORNER_LEFT_UPPER
   ObjectSetInteger(0, rrLabel, OBJPROP_XDISTANCE, TimerXDistance);
   ObjectSetInteger(0, rrLabel, OBJPROP_YDISTANCE, TimerYDistance+30);
   ObjectSetInteger(0, rrLabel, OBJPROP_FONTSIZE, RRFontSize);
   ObjectSetInteger(0, rrLabel, OBJPROP_COLOR, RRColor);

   return(rates_total);
}
