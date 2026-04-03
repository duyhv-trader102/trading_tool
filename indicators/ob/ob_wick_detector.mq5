//+------------------------------------------------------------------+
//|                                         ob_wick_detector.mq5    |
//|  Phát hiện nến Order Block (OB) có tổng râu 2 chiều >= X% spread|
//|                                                                  |
//|  Logic:                                                          |
//|    upper_wick = High  - max(Open, Close)                         |
//|    lower_wick = min(Open, Close) - Low                           |
//|    total_wick = upper_wick + lower_wick                          |
//|    Điều kiện: total_wick / spread >= InpWickPct / 100            |
//+------------------------------------------------------------------+
#property copyright   "trading_tool"
#property version     "1.00"
#property description "Detect OB candle: total wick (both sides) >= % of spread"
#property indicator_chart_window

#property indicator_buffers 2
#property indicator_plots   2

//--- Plot 0: Bull OB (mũi tên dưới nến)
#property indicator_label1  "Bull OB"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrMediumAquamarine
#property indicator_style1  STYLE_SOLID
#property indicator_width1  2

//--- Plot 1: Bear OB (mũi tên trên nến)
#property indicator_label2  "Bear OB"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrTomato
#property indicator_style2  STYLE_SOLID
#property indicator_width2  2

//--- Inputs
input double InpWickPct    = 50.0;               // Min tổng râu (% spread)
input int    InpMaxBars    = 300;                // Chỉ xét N nến gần nhất (0 = tất cả)
input int    InpBoxBars    = 5;                  // Chiều rộng box OB (nến)
input color  InpBullColor  = clrMediumAquamarine;// Màu Bull OB box
input color  InpBearColor  = clrTomato;          // Màu Bear OB box
input int    InpBoxAlpha   = 40;                 // Độ trong suốt box (0=đặc, 255=trong)
input bool   InpShowBox    = true;               // Vẽ box vùng thân nến
input bool   InpShowArrow  = true;               // Vẽ mũi tên trên/dưới nến

//--- Buffers
double BullBuffer[];
double BearBuffer[];

//--- Prefix cho object name để tránh trùng
static string OBJ_PREFIX = "OB_";

//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, BullBuffer, INDICATOR_DATA);
   SetIndexBuffer(1, BearBuffer, INDICATOR_DATA);

   //--- Mũi tên: 233 = ▲, 234 = ▼ (Wingdings)
   PlotIndexSetInteger(0, PLOT_ARROW, 233);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);

   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, EMPTY_VALUE);

   PlotIndexSetString(0, PLOT_LABEL, "Bull OB");
   PlotIndexSetString(1, PLOT_LABEL, "Bear OB");

   IndicatorSetString(INDICATOR_SHORTNAME,
      "OB Wick ≥" + DoubleToString(InpWickPct, 0) + "%");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   //--- Xoá tất cả object box đã vẽ khi remove indicator
   ObjectsDeleteAll(0, OBJ_PREFIX);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
int OnCalculate(const int       rates_total,
                const int       prev_calculated,
                const datetime &time[],
                const double   &open[],
                const double   &high[],
                const double   &low[],
                const double   &close[],
                const long     &tick_volume[],
                const long     &volume[],
                const int      &spread[])
{
   //--- Khi recalc toàn bộ thì xoá objects cũ trước
   if(prev_calculated == 0)
      ObjectsDeleteAll(0, OBJ_PREFIX);

   int start = (prev_calculated > 1) ? prev_calculated - 1 : 0;

   //--- Giới hạn max bars
   if(InpMaxBars > 0 && start < rates_total - InpMaxBars)
      start = rates_total - InpMaxBars;

   for(int i = start; i < rates_total; i++)
   {
      BullBuffer[i] = EMPTY_VALUE;
      BearBuffer[i] = EMPTY_VALUE;

      double candle_spread = high[i] - low[i];
      if(candle_spread <= 0.0)
         continue;

      double body_top   = MathMax(open[i], close[i]);
      double body_bot   = MathMin(open[i], close[i]);
      double upper_wick = high[i]  - body_top;
      double lower_wick = body_bot - low[i];
      double total_wick = upper_wick + lower_wick;
      double wick_pct   = (total_wick / candle_spread) * 100.0;

      if(wick_pct < InpWickPct)
         continue;

      bool is_bull = (close[i] >= open[i]);

      //--- Arrow buffer
      if(InpShowArrow)
      {
         if(is_bull)
            BullBuffer[i] = low[i];   // hiển thị dưới nến
         else
            BearBuffer[i] = high[i];  // hiển thị trên nến
      }

      //--- Đường nét đứt tại midpoint (50% spread), kéo 3 nến sang phải
      {
         string mid_name = OBJ_PREFIX + "MID_" + TimeToString(time[i], TIME_DATE | TIME_MINUTES);
         if(ObjectFind(0, mid_name) >= 0)
            ObjectDelete(0, mid_name);

         double mid      = (high[i] + low[i]) / 2.0;
         int    end_bar  = MathMin(i + 3, rates_total - 1);
         datetime t_end  = time[end_bar];

         ObjectCreate(0, mid_name, OBJ_TREND, 0, time[i], mid, t_end, mid);
         ObjectSetInteger(0, mid_name, OBJPROP_COLOR,     clrBlack);
         ObjectSetInteger(0, mid_name, OBJPROP_WIDTH,     1);
         ObjectSetInteger(0, mid_name, OBJPROP_STYLE,     STYLE_DASH);
         ObjectSetInteger(0, mid_name, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, mid_name, OBJPROP_BACK,      true);
         ObjectSetInteger(0, mid_name, OBJPROP_SELECTABLE,false);
         ObjectSetInteger(0, mid_name, OBJPROP_HIDDEN,    true);
      }

      //--- Vẽ box vùng thân nến
      if(InpShowBox)
      {
         string obj_name = OBJ_PREFIX + TimeToString(time[i], TIME_DATE | TIME_MINUTES);

         //--- Nếu đã có (do recalc bar hiện tại) thì xoá trước
         if(ObjectFind(0, obj_name) >= 0)
            ObjectDelete(0, obj_name);

         //--- Tính thời điểm kết thúc box (dùng bar_index + InpBoxBars)
         int    end_bar    = MathMin(i + InpBoxBars, rates_total - 1);
         datetime time_end = time[end_bar];

         //--- Màu box: pha alpha
         color box_col     = is_bull
            ? ColorWithAlpha(InpBullColor, InpBoxAlpha)
            : ColorWithAlpha(InpBearColor, InpBoxAlpha);
         color border_col  = is_bull ? InpBullColor : InpBearColor;

         ObjectCreate(0, obj_name, OBJ_RECTANGLE, 0, time[i], body_top, time_end, body_bot);
         ObjectSetInteger(0, obj_name, OBJPROP_COLOR,     border_col);
         ObjectSetInteger(0, obj_name, OBJPROP_BGCOLOR,   box_col);
         ObjectSetInteger(0, obj_name, OBJPROP_FILL,      true);
         ObjectSetInteger(0, obj_name, OBJPROP_WIDTH,     1);
         ObjectSetInteger(0, obj_name, OBJPROP_BACK,      true);
         ObjectSetInteger(0, obj_name, OBJPROP_SELECTABLE,false);
         ObjectSetInteger(0, obj_name, OBJPROP_HIDDEN,    true);

         //--- Tooltip
         string tip = (is_bull ? "Bull OB" : "Bear OB") +
                      "  Wick: " + DoubleToString(wick_pct, 1) + "%" +
                      "  [" + TimeToString(time[i]) + "]";
         ObjectSetString(0, obj_name, OBJPROP_TOOLTIP, tip);
      }
   }

   ChartRedraw(0);
   return rates_total;
}

//+------------------------------------------------------------------+
//| Trộn màu với mức trong suốt (alpha: 0=đặc, 255=hoàn toàn trong) |
//+------------------------------------------------------------------+
color ColorWithAlpha(color base_color, int alpha)
{
   alpha = MathMax(0, MathMin(255, alpha));
   int r = (int)((base_color >> 16) & 0xFF);
   int g = (int)((base_color >>  8) & 0xFF);
   int b = (int)( base_color        & 0xFF);

   //--- Pha với trắng (255,255,255) theo alpha
   r = r + (int)(((255 - r) * alpha) / 255);
   g = g + (int)(((255 - g) * alpha) / 255);
   b = b + (int)(((255 - b) * alpha) / 255);

   return (color)((r << 16) | (g << 8) | b);
}
//+------------------------------------------------------------------+
