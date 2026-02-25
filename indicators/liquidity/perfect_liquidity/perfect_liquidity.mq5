#property indicator_chart_window
#property indicator_plots 0

input int MaxBars = 500;

#define OBJ_PREFIX "PL_"

//--- Xóa object khi remove indicator
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, OBJ_PREFIX);
  }

//--- Hàm kiểm tra nến nowick
bool IsNoWickUp(int i, const double &open[], const double &close[], const double &low[])
  {
   return (close[i] > open[i] && low[i] == open[i]);
  }
bool IsNoWickDown(int i, const double &open[], const double &close[], const double &high[])
  {
   return (close[i] < open[i] && high[i] == open[i]);
  }

//--- Perfect DB/DT
void DrawPerfectDoubleTopBottom(int start, int rates_total, const datetime &time[], const double &high[], const double &low[])
  {
   for(int i=start; i<rates_total; i++)
     {
      for(int j=i-1; j>=start; j--)
        {
         // Perfect Double Top
         if(high[i] == high[j])
           {
            bool isPerfect = true;
            for(int k=j+1; k<i; k++)
              {
               if(high[k] > high[i]) // bị cắt qua
                 {
                  isPerfect = false;
                  break;
                 }
              }
            if(isPerfect)
              {
               string obj_name = OBJ_PREFIX + "TOP_" + IntegerToString(i) + "_" + IntegerToString(j);
               ObjectCreate(0, obj_name, OBJ_TREND, 0, time[j], high[j], time[i], high[i]);
               ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrBlack);
               ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
               ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
              }
           }
         // Perfect Double Bottom
         if(low[i] == low[j])
           {
            bool isPerfect = true;
            for(int k=j+1; k<i; k++)
              {
               if(low[k] < low[i]) // bị cắt qua
                 {
                  isPerfect = false;
                  break;
                 }
              }
            if(isPerfect)
              {
               string obj_name = OBJ_PREFIX + "BOT_" + IntegerToString(i) + "_" + IntegerToString(j);
               ObjectCreate(0, obj_name, OBJ_TREND, 0, time[j], low[j], time[i], low[i]);
               ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrBlack);
               ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
               ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
              }
           }
        }
     }
  }

//--- Perfect trendline
void DrawPerfectTrendline(int start, int rates_total, const datetime &time[], const double &high[], const double &low[])
  {
   // 3 điểm liên tiếp
   for(int i=start+2; i<rates_total; i++)
     {
      double x1=i-2, x2=i-1, x3=i;
      // Trendline tăng (đáy)
      if(low[int(x1)] < low[int(x2)] && low[int(x2)] < low[int(x3)])
        {
         double a = (low[int(x3)] - low[int(x1)]) / (x3 - x1);
         double b = low[int(x1)] - a*x1;
         if(MathAbs(low[int(x2)] - (a*x2 + b)) < 1e-6)
           {
            string obj_name = OBJ_PREFIX + "TL_UP3_" + IntegerToString(i);
            ObjectCreate(0, obj_name, OBJ_TREND, 0, time[int(x1)], low[int(x1)], time[int(x3)], low[int(x3)]);
            ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrBlack);
            ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
            ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
           }
        }
      // Trendline giảm (đỉnh)
      if(high[int(x1)] > high[int(x2)] && high[int(x2)] > high[int(x3)])
        {
         double a = (high[int(x3)] - high[int(x1)]) / (x3 - x1);
         double b = high[int(x1)] - a*x1;
         if(MathAbs(high[int(x2)] - (a*x2 + b)) < 1e-6)
           {
            string obj_name = OBJ_PREFIX + "TL_DOWN3_" + IntegerToString(i);
            ObjectCreate(0, obj_name, OBJ_TREND, 0, time[int(x1)], high[int(x1)], time[int(x3)], high[int(x3)]);
            ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrBlack);
            ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
            ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
           }
        }
     }

   // 4 điểm liên tiếp
   for(int i=start+3; i<rates_total; i++)
     {
      double x1=i-3, x2=i-2, x3=i-1, x4=i;
      // Trendline tăng (đáy)
      if(low[int(x1)] < low[int(x2)] && low[int(x2)] < low[int(x3)] && low[int(x3)] < low[int(x4)])
        {
         // Tính a, b từ 2 điểm đầu/cuối
         double a = (low[int(x4)] - low[int(x1)]) / (x4 - x1);
         double b = low[int(x1)] - a*x1;
         // Kiểm tra 2 điểm giữa có nằm trên đường thẳng
         if(MathAbs(low[int(x2)] - (a*x2 + b)) < 1e-6 && MathAbs(low[int(x3)] - (a*x3 + b)) < 1e-6)
           {
            string obj_name = OBJ_PREFIX + "TL_UP4_" + IntegerToString(i);
            ObjectCreate(0, obj_name, OBJ_TREND, 0, time[int(x1)], low[int(x1)], time[int(x4)], low[int(x4)]);
            ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrBlack);
            ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
            ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
           }
        }
      // Trendline giảm (đỉnh)
      if(high[int(x1)] > high[int(x2)] && high[int(x2)] > high[int(x3)] && high[int(x3)] > high[int(x4)])
        {
         double a = (high[int(x4)] - high[int(x1)]) / (x4 - x1);
         double b = high[int(x1)] - a*x1;
         if(MathAbs(high[int(x2)] - (a*x2 + b)) < 1e-6 && MathAbs(high[int(x3)] - (a*x3 + b)) < 1e-6)
           {
            string obj_name = OBJ_PREFIX + "TL_DOWN4_" + IntegerToString(i);
            ObjectCreate(0, obj_name, OBJ_TREND, 0, time[int(x1)], high[int(x1)], time[int(x4)], high[int(x4)]);
            ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrBlack);
            ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
            ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
           }
        }
     }
  }

//--- Nowick candle
void DrawNoWickCandles(int start, int rates_total, const datetime &time[], const double &open[], const double &close[], const double &high[], const double &low[])
  {
   for(int i=start; i<rates_total; i++)
     {
      // Nến tăng không râu dưới
      if(IsNoWickUp(i, open, close, low))
        {
         int end_index = rates_total-1;
         for(int j=i+1; j<rates_total; j++)
           {
            if(low[j] < low[i]) // bị cắt qua
              {
               end_index = j;
               break;
              }
           }
         string obj_name = OBJ_PREFIX + "NOWICK_UP_" + IntegerToString(i);
         ObjectCreate(0, obj_name, OBJ_TREND, 0, time[i], low[i], time[end_index], low[i]);
         ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrDodgerBlue);
         ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
         ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
         ObjectSetInteger(0, obj_name, OBJPROP_RAY_RIGHT, end_index == rates_total-1);
        }
      // Nến giảm không râu trên
      if(IsNoWickDown(i, open, close, high))
        {
         int end_index = rates_total-1;
         for(int j=i+1; j<rates_total; j++)
           {
            if(high[j] > high[i]) // bị cắt qua
              {
               end_index = j;
               break;
              }
           }
         string obj_name = OBJ_PREFIX + "NOWICK_DOWN_" + IntegerToString(i);
         ObjectCreate(0, obj_name, OBJ_TREND, 0, time[i], high[i], time[end_index], high[i]);
         ObjectSetInteger(0, obj_name, OBJPROP_COLOR, clrRed);
         ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, 1);
         ObjectSetInteger(0, obj_name, OBJPROP_STYLE, STYLE_SOLID);
         ObjectSetInteger(0, obj_name, OBJPROP_RAY_RIGHT, end_index == rates_total-1);
        }
     }
  }

//--- OnCalculate chỉ gọi hàm
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
   int start = MathMax(20, rates_total - MaxBars);

   DrawPerfectDoubleTopBottom(start, rates_total, time, high, low);
   DrawPerfectTrendline(start, rates_total, time, high, low);
   DrawNoWickCandles(start, rates_total, time, open, close, high, low);

   return(rates_total);
  }
