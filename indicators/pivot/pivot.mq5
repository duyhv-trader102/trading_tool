//+------------------------------------------------------------------+
//|                                                         Pivot.mq5 |
//+------------------------------------------------------------------+
#property copyright "Your Name"
#property link      "https://www.mql5.com"
#property version   "1.00"
#property description "Pivot Points Indicator"

#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

//+------------------------------------------------------------------+
//|                                                  Pivot_XAUUSD... |
//|  Classic (Daily/Weekly/Monthly) + Daily DeMark                   |
//|  Uses PRIOR PERIOD OHLC: D1[1], W1[1], MN1[1]                    |
//|  Draws horizontal levels as objects; auto-updates each new day   |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property strict

// ===== Inputs =====
input bool   ShowDailyClassic   = true;
input bool   ShowWeeklyClassic  = true;
input bool   ShowMonthlyClassic = true;
input bool   ShowDailyDeMark    = true;

input bool   Show_R1R2R3 = true;
input bool   Show_S1S2S3 = true;
input bool   Show_Pivot  = true;

input color  ColDaily    = clrDeepSkyBlue;
input color  ColWeekly   = clrOrange;
input color  ColMonthly  = clrMediumSeaGreen;
input color  ColDeMark   = clrTomato;

input ENUM_LINE_STYLE LineStyle = STYLE_DASHDOT;
input int    LineWidth          = 1;

input int    LabelFontSize      = 12;       // Tăng font size từ 8 lên 12
input int    LabelXShift        = 150;      // Tăng khoảng cách từ 20 lên 150 pixels
input bool   ShowPriceLabels    = true;

// ===== Helpers =====
struct OHLC { double o,h,l,c; };
struct ClassicLevels {
  double P,R1,R2,R3,S1,S2,S3;
};

string prefix = "PIVOTXAU_";

datetime lastDailyCalc   = 0;
datetime lastWeeklyCalc  = 0;
datetime lastMonthlyCalc = 0;

int OnInit()
{
   Print("=== Pivot Indicator Initializing ===");
   Print("Symbol: ", _Symbol, " Period: ", EnumToString(PERIOD_CURRENT));
   
   ObjectsDeleteAll(0, prefix);
   
   // Force initial calculation
   lastDailyCalc = 0;
   lastWeeklyCalc = 0;
   lastMonthlyCalc = 0;
   
   return(INIT_SUCCEEDED);
}

int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[], const double &high[],
                const double &low[],  const double &close[],
                const long &tick_volume[], const long &volume[],
                const int &spread[])
{
   // Skip if not enough bars
   if(rates_total < 2) return(0);
   
   // Chỉ tính lại khi có nến mới của D1, W1 hoặc MN1
   datetime curD1 = iTime(_Symbol, PERIOD_D1, 0);
   datetime curW1 = iTime(_Symbol, PERIOD_W1, 0);
   datetime curMN1 = iTime(_Symbol, PERIOD_MN1, 0);
   
   static datetime lastD1 = 0;
   static datetime lastW1 = 0;
   static datetime lastMN1 = 0;
   
   bool needCalc = false;
   
   // Kiểm tra từng timeframe
   if(curD1 != lastD1) {
      lastD1 = curD1;
      RecalcDaily();
      needCalc = true;
   }
   
   if(curW1 != lastW1) {
      lastW1 = curW1;
      RecalcWeekly();
      needCalc = true;
   }
   
   if(curMN1 != lastMN1) {
      lastMN1 = curMN1;
      RecalcMonthly();
      needCalc = true;
   }
   
   if(needCalc) ChartRedraw(0);
   
   return(rates_total);
}

// ---------- Recalc wrappers ----------
void RecalcDaily()
{
   datetime tPrevD = iTime(_Symbol, PERIOD_D1, 1);
   if(tPrevD==0) {
      Print("Error: Could not get previous day time");
      return;
   }
   if(tPrevD!=lastDailyCalc)
   {
      lastDailyCalc = tPrevD;
      OHLC d = GetPrev(PERIOD_D1);
      
      // Add debug prints
      Print("Previous Day OHLC: O=", d.o, " H=", d.h, " L=", d.l, " C=", d.c);
      
      if(ShowDailyClassic) {
         ClassicLevels L = Classic(d);
         Print("Daily Pivot Levels: P=", L.P, " R1=", L.R1, " S1=", L.S1);
         DrawClassic(d, "D", ColDaily);
      }
      if(ShowDailyDeMark) DrawDeMark(d, "DMD", ColDeMark);
   }
}

void RecalcWeekly()
{
   datetime tPrevW = iTime(_Symbol, PERIOD_W1, 1);
   if(tPrevW==0) {
      Print("Error: Could not get previous week time");
      return;
   }
   if(tPrevW!=lastWeeklyCalc)
   {
      lastWeeklyCalc = tPrevW;
      if(ShowWeeklyClassic)
      {
         OHLC w = GetPrev(PERIOD_W1);
         
         // Add debug prints
         Print("Previous Week OHLC: O=", w.o, " H=", w.h, " L=", w.l, " C=", w.c);
         
         ClassicLevels L = Classic(w);
         Print("Weekly Pivot Levels: P=", L.P, " R1=", L.R1, " S1=", L.S1);
         DrawClassic(w, "W", ColWeekly);
      }
   }
}

void RecalcMonthly()
{
   datetime tPrevM = iTime(_Symbol, PERIOD_MN1, 1);
   if(tPrevM==0) {
      Print("Error: Could not get previous month time");
      return;
   }
   if(tPrevM!=lastMonthlyCalc)
   {
      lastMonthlyCalc = tPrevM;
      if(ShowMonthlyClassic)
      {
         OHLC m = GetPrev(PERIOD_MN1);
         
         // Add debug prints
         Print("Previous Month OHLC: O=", m.o, " H=", m.h, " L=", m.l, " C=", m.c);
         
         ClassicLevels L = Classic(m);
         Print("Monthly Pivot Levels: P=", L.P, " R1=", L.R1, " S1=", L.S1);
         DrawClassic(m, "M", ColMonthly);
      }
   }
}

// ---------- Data helpers ----------
OHLC GetPrev(ENUM_TIMEFRAMES tf)
{
   OHLC x;
   
   // Luôn lấy nến đã đóng (previous completed candle)
   x.o = iOpen (_Symbol, tf, 1);  // Shift = 1 for previous candle
   x.h = iHigh (_Symbol, tf, 1);
   x.l = iLow  (_Symbol, tf, 1);
   x.c = iClose(_Symbol, tf, 1);
   
   // Debug info chi tiết hơn
   Print("------ ", EnumToString(tf), " Pivot Calculation ------");
   Print("Previous ", EnumToString(tf), " OHLC:");
   Print("Open:   ", x.o);
   Print("High:   ", x.h);
   Print("Low:    ", x.l);
   Print("Close:  ", x.c);
   Print("Time:   ", TimeToString(iTime(_Symbol, tf, 1)));
   
   // Kiểm tra dữ liệu hợp lệ
   if(x.o == 0 || x.h == 0 || x.l == 0 || x.c == 0) {
      Print("Error: Invalid OHLC data for ", EnumToString(tf));
      Print("Make sure you have enough historical data loaded");
   }
   
   return x;
}

ClassicLevels Classic(const OHLC &p)
{
   ClassicLevels L;
   double P = (p.h + p.l + p.c)/3.0;
   L.P  = P;
   L.R1 = 2.0*P - p.l;
   L.S1 = 2.0*P - p.h;
   L.R2 = P + (p.h - p.l);
   L.S2 = P - (p.h - p.l);
   L.R3 = p.h + 2.0*(P - p.l);
   L.S3 = p.l - 2.0*(p.h - P);
   return L;
}

// DeMark: decide by prior day's C vs O (as in your sheet)
void DeMarkLevels(const OHLC &p, double &P, double &R1, double &S1)
{
   // X depends on relation of Close vs Open
   double X;
   if(p.c < p.o)       X = p.h + 2.0*p.l + p.c;
   else if(p.c > p.o)  X = 2.0*p.h + p.l + p.c;
   else                X = p.h + p.l + 2.0*p.c;

   P  = X/4.0;
   R1 = X/2.0 - p.l;
   S1 = X/2.0 - p.h;
}

// ---------- Drawing ----------
void DrawClassic(const OHLC &src, const string tag, const color col)
{
   ClassicLevels L = Classic(src);
   int d = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   if(Show_Pivot)  DrawH("P_"+tag,  L.P , col, "Pivot "+tag, d);
   if(Show_R1R2R3) {
      DrawH("R1_"+tag, L.R1, col, "R1 "+tag, d);
      DrawH("R2_"+tag, L.R2, col, "R2 "+tag, d);
      DrawH("R3_"+tag, L.R3, col, "R3 "+tag, d);
   }
   if(Show_S1S2S3) {
      DrawH("S1_"+tag, L.S1, col, "S1 "+tag, d);
      DrawH("S2_"+tag, L.S2, col, "S2 "+tag, d);
      DrawH("S3_"+tag, L.S3, col, "S3 "+tag, d);
   }
}

void DrawDeMark(const OHLC &src, const string tag, const color col)
{
   int d = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double P,R1,S1;
   DeMarkLevels(src, P, R1, S1);

   if(Show_Pivot) DrawH("P_"+tag,  P , col, "DeMark P", d);
   // DeMark chỉ có 1 R và 1 S trong phiên bản bảng bạn gửi
   DrawH("R1_"+tag, R1, col, "DeMark R", d);
   DrawH("S1_"+tag, S1, col, "DeMark S", d);
}

// Create/update a horizontal line + optional price label near the latest bar
void DrawH(const string key, const double price, const color col, const string label, int digits)
{
   string name = prefix + key;
   
   // Delete existing object first
   ObjectDelete(0, name);
   
   // Create horizontal line
   if(!ObjectCreate(0, name, OBJ_HLINE, 0, 0, price))
   {
      Print("Error creating line object: ", GetLastError());
      return;
   }
   
   // Set line properties
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_STYLE, LineStyle);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, LineWidth);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, false);
   ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   ObjectSetInteger(0, name, OBJPROP_TIMEFRAMES, OBJ_ALL_PERIODS);

   // Handle label
   if(ShowPriceLabels)
   {
      string tname = name + "_LBL";
      ObjectDelete(0, tname);
      
      // Get current timeframe's last bar time
      datetime lastTime = iTime(_Symbol, PERIOD_CURRENT, 0);
      // Shift right by 20 bars
      datetime shiftedTime = lastTime + PeriodSeconds(PERIOD_CURRENT) * 20;
      
      if(ObjectCreate(0, tname, OBJ_TEXT, 0, shiftedTime, price))
      {
         string txt = StringFormat("%s  %."+IntegerToString(digits)+"f", label, price);
         ObjectSetString(0, tname, OBJPROP_TEXT, txt);
         ObjectSetInteger(0, tname, OBJPROP_COLOR, col);
         ObjectSetInteger(0, tname, OBJPROP_FONTSIZE, LabelFontSize);
         ObjectSetInteger(0, tname, OBJPROP_ANCHOR, ANCHOR_LEFT);
         ObjectSetString(0, tname, OBJPROP_FONT, "Arial Bold");
         ObjectSetInteger(0, tname, OBJPROP_TIMEFRAMES, OBJ_ALL_PERIODS);
      }
      else
      {
         Print("Error creating label object: ", GetLastError());
      }
   }
   
   ChartRedraw(0);
}

// ---------- Cleanup ----------
void OnDeinit(const int reason)
{
   // Xóa tất cả các objects với prefix đã định nghĩa
   ObjectsDeleteAll(0, prefix);
   
   // In thông báo để xác nhận việc xóa
   Print("=== Pivot Indicator removed, all objects cleaned up ===");
   ChartRedraw(0); // Đảm bảo chart được cập nhật sau khi xóa
}
