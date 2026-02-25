#property indicator_chart_window
#property indicator_plots 0

input int MaxBars = 500;
input ENUM_TIMEFRAMES ATR_Timeframe = PERIOD_M5;
input int ATR_Period = 1000;
input bool ShowMultiTopsBottoms = true; // Bật/tắt vẽ multi-tops/bottoms

//--- Chuyển mã timeframe thành chuỗi
string TfToStr(int tf) {
   switch(tf) {
      case PERIOD_M1:   return "M1";
      case PERIOD_M3:   return "M3";
      case PERIOD_M5:   return "M5";
      case PERIOD_M15:  return "M15";
      case PERIOD_M30:  return "M30";
      case PERIOD_H1:   return "H1";
      case PERIOD_H2:   return "H2";
      case PERIOD_H3:   return "H3";
      case PERIOD_H4:   return "H4";
      case PERIOD_H6:   return "H6";
      case PERIOD_H8:   return "H8";
      case PERIOD_H12:  return "H12";
      case PERIOD_D1:   return "D1";
      case PERIOD_W1:   return "W1";
      case PERIOD_MN1:  return "MN1";
      default: return IntegerToString(tf);
   }
}

//--- Vẽ object
void DrawMark(string name, int i, double price, color clr, datetime time, int arrow_code=233) {
   string obj_name = name + "_" + TfToStr(Period()) + "_" + IntegerToString(i);
   if(ObjectFind(0,obj_name) >= 0) ObjectDelete(0,obj_name);
   ObjectCreate(0,obj_name,OBJ_ARROW,0,time,price);
   ObjectSetInteger(0,obj_name,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,obj_name,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,obj_name,OBJPROP_ARROWCODE,arrow_code);
}

//--- Cleanup objects
void CleanupObjects() {
   string cur_tf = "_" + TfToStr(Period()) + "_";
   int total = ObjectsTotal(0);
   for(int i=total-1; i>=0; i--) {
      string name = ObjectName(0,i);
      // Nếu là object của indicator và KHÔNG phải khung hiện tại thì xóa
      if(StringFind(name, "_M") >= 0 || StringFind(name, "_H") >= 0 || StringFind(name, "_D1_") >= 0 || StringFind(name, "_W1_") >= 0 || StringFind(name, "_MN1_") >= 0) {
         if(StringFind(name, cur_tf) < 0)
            ObjectDelete(0,name);
      }
   }
}

//--- ATR đa timeframe
double GetATR_Custom(int shift, int period, ENUM_TIMEFRAMES tf) {
   static int atr_handle = INVALID_HANDLE;
   static ENUM_TIMEFRAMES last_tf = -1;
   static int last_period = -1;
   if(atr_handle == INVALID_HANDLE || last_tf != tf || last_period != period) {
      if(atr_handle != INVALID_HANDLE) IndicatorRelease(atr_handle);
      atr_handle = iATR(NULL, tf, period);
      last_tf = tf;
      last_period = period;
   }
   double atr[];
   if(CopyBuffer(atr_handle, 0, shift, 1, atr) == 1)
      return atr[0];
   return 0;
}

//--- Kiểm tra doji
bool IsDoji(const double &open[], const double &close[], const double &high[], const double &low[], int i) {
   double body = MathAbs(open[i] - close[i]);
   double range = high[i] - low[i];
   return (body <= 0.2 * range);
}

//--- Kiểm tra đỉnh/đáy
bool IsTop(const double &high[], int i, int rates_total) {
   if(i <= 0 || i >= rates_total-1) return false;
   return (high[i] > high[i-1] && high[i] > high[i+1]);
}
bool IsBottom(const double &low[], int i, int rates_total) {
   if(i <= 0 || i >= rates_total-1) return false;
   return (low[i] < low[i-1] && low[i] < low[i+1]);
}

//--- Kiểm tra inside bar
bool IsInsideBar(const double &high[], const double &low[], int i) {
   if(i <= 0) return false;
   return (high[i] < high[i-1] && low[i] > low[i-1]);
}

//--- Kiểm tra outside bar
bool IsOutsideBar(const double &high[], const double &low[], int i) {
   if(i <= 0) return false;
   return (high[i] > high[i-1] && low[i] < low[i-1]);
}

//--- Vẽ multi-tops/bottoms
void DrawMultiTopsBottoms(const int rates_total,
                          const double &high[],
                          const double &low[],
                          const datetime &time[],
                          double atr,
                          int max_bars) {
   if(atr <= 0) return;
   int start = MathMax(2, rates_total - max_bars);
   string tf_str = TfToStr(Period());

   // Multi-Tops
   for(int i=rates_total-2; i>=start; i--) {
      for(int j=i-1; j>=start; j--) {
         if(MathAbs(high[i] - high[j]) <= (2.0/3.0)*atr) {
            bool broken = false;
            for(int k=j+1; k<i; k++) {
               if(high[k] > MathMax(high[i], high[j])) {
                  broken = true;
                  break;
               }
            }
            if(!broken) {
               string obj_name = "MultiTop_" + tf_str + "_" + IntegerToString(i) + "_" + IntegerToString(j);
               if(ObjectFind(0,obj_name) >= 0) ObjectDelete(0,obj_name);
               ObjectCreate(0,obj_name,OBJ_TREND,0,time[j],high[j],time[i],high[i]);
               ObjectSetInteger(0,obj_name,OBJPROP_COLOR,clrRed);
               ObjectSetInteger(0,obj_name,OBJPROP_WIDTH,1);
            }
         }
      }
   }

   // Multi-Bottoms
   for(int i=rates_total-2; i>=start; i--) {
      for(int j=i-1; j>=start; j--) {
         if(MathAbs(low[i] - low[j]) <= (2.0/3.0)*atr) {
            bool broken = false;
            for(int k=j+1; k<i; k++) {
               if(low[k] < MathMin(low[i], low[j])) {
                  broken = true;
                  break;
               }
            }
            if(!broken) {
               string obj_name = "MultiBottom_" + tf_str + "_" + IntegerToString(i) + "_" + IntegerToString(j);
               if(ObjectFind(0,obj_name) >= 0) ObjectDelete(0,obj_name);
               ObjectCreate(0,obj_name,OBJ_TREND,0,time[j],low[j],time[i],low[i]);
               ObjectSetInteger(0,obj_name,OBJPROP_COLOR,clrGreen);
               ObjectSetInteger(0,obj_name,OBJPROP_WIDTH,1);
            }
         }
      }
   }
}

//--- Tính toán chính
void CalculateMajorLiquidity(const int rates_total,
                            const double &open[],
                            const double &high[],
                            const double &low[],
                            const double &close[],
                            const datetime &time[]) {
   double atr = GetATR_Custom(0, ATR_Period, ATR_Timeframe);
   int start = MathMax(2, rates_total - MaxBars);
   for(int i=rates_total-2; i>=start; i--) {
      if(i+1 < rates_total && IsOutsideBar(high, low, i+1))
         continue;
      if(IsTop(high, i, rates_total) && IsDoji(open, close, high, low, i))
         DrawMark("MajorLiquidityTopDoji",i,high[i]+atr*0.5,clrBlue,time[i],234);
      if(IsBottom(low, i, rates_total) && IsDoji(open, close, high, low, i))
         DrawMark("MajorLiquidityBottomDoji",i,low[i]-atr*0.5,clrBlue,time[i],233);

      if(!IsInsideBar(high, low, i)) {
         double range = high[i] - low[i];
         double upper_wick = high[i] - MathMax(open[i], close[i]);
         double lower_wick = MathMin(open[i], close[i]) - low[i];
         if(upper_wick > 0.5 * range)
            DrawMark("BigWickRejectionUp",i,high[i]+atr*0.5,clrOrange,time[i],234);
         if(lower_wick > 0.5 * range)
            DrawMark("BigWickRejectionDown",i,low[i]-atr*0.5,clrOrange,time[i],233);
      }
   }
   if(ShowMultiTopsBottoms &&
      (Period() == PERIOD_M30 || Period() == PERIOD_H1 || Period() == PERIOD_H2 ||
       Period() == PERIOD_H3 || Period() == PERIOD_H4 || Period() == PERIOD_H6 ||
       Period() == PERIOD_H8 || Period() == PERIOD_H12 || Period() == PERIOD_D1 ||
       Period() == PERIOD_W1 || Period() == PERIOD_MN1)) {
      DrawMultiTopsBottoms(rates_total, high, low, time, atr, MaxBars);
   }
}

//--- Khởi tạo
int OnInit() {
   CleanupObjects();
   return(INIT_SUCCEEDED);
}

//--- Xóa toàn bộ object của indicator (dùng khi xóa khỏi chart)
void CleanupAllIndicatorObjects() {
   int total = ObjectsTotal(0);
   for(int i=total-1; i>=0; i--) {
      string name = ObjectName(0,i);
      if(StringFind(name, "MultiTop_") == 0 ||
         StringFind(name, "MultiBottom_") == 0 ||
         StringFind(name, "MajorLiquidityTopDoji_") == 0 ||
         StringFind(name, "MajorLiquidityBottomDoji_") == 0 ||
         StringFind(name, "BigWickRejectionUp_") == 0 ||
         StringFind(name, "BigWickRejectionDown_") == 0) {
         ObjectDelete(0, name);
      }
   }
}

//--- Xóa object khi indicator bị xóa khỏi chart
void OnDeinit(const int reason) {
   CleanupAllIndicatorObjects();
}

//--- Tính toán lại khi có dữ liệu mới
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[]) {
   CalculateMajorLiquidity(rates_total, open, high, low, close, time);
   return(rates_total);
}
