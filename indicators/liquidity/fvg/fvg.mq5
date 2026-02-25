#property indicator_chart_window
#property indicator_plots 0

//--- input parameters
input int     MaxBars      = 500;      // Số lượng nến check tối đa
input color   FVGColorUp   = clrDodgerBlue;  // Màu FVG tăng
input color   FVGColorDown = clrRed;   // Màu FVG giảm
input int     FVGLineWidth = 1;        // Độ dày đường nét đứt nhỏ hơn
input int     FVGLineStyle = STYLE_DASHDOT; // Kiểu đường nét đứt
input int     FVGLookAhead = 15;       // Số nến hiển thị độ lệch nếu không bị cắt phải

input color   GapColorUp   = clrAqua;     // Màu ray gap tăng
input color   GapColorDown = clrMagenta;  // Màu ray gap giảm

#define OBJ_PREFIX "FVG_"
#define GAP_PREFIX "GAP_"

enum SignalType { NONE, FVG_UP, FVG_DOWN, FVG_DIFF_UP, FVG_DIFF_DOWN, GAP_UP, GAP_DOWN };

struct DetectResult {
   SignalType type;
   double level;
   double gap;
   bool isUp;
   bool isFVG;
};

int OnInit()
  {
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, OBJ_PREFIX);
   ObjectsDeleteAll(0, GAP_PREFIX);
  }

DetectResult DetectFVGGap(int i,
                          const double &open[],
                          const double &close[],
                          const double &high[],
                          const double &low[])
{
   DetectResult res;
   res.type = NONE;

   // FVG cùng màu
   if(close[i-1] > open[i-1] && close[i] > open[i] && close[i-1] < open[i]) {
      res.type = FVG_UP;
      res.level = close[i-1];
      res.gap = open[i] - close[i-1];
      res.isUp = true;
      res.isFVG = true;
      return res;
   }
   if(close[i-1] < open[i-1] && close[i] < open[i] && close[i-1] > open[i]) {
      res.type = FVG_DOWN;
      res.level = close[i-1];
      res.gap = close[i-1] - open[i];
      res.isUp = false;
      res.isFVG = true;
      return res;
   }

   // FVG khác màu
   if(open[i-1] < open[i] && open[i-1] < close[i] && close[i-1] < open[i] && close[i-1] < close[i]) {
      res.type = FVG_DIFF_UP;
      res.level = close[i-1];
      res.gap = MathMax(MathAbs(open[i] - close[i-1]), MathAbs(close[i] - close[i-1]));
      res.isUp = true;
      res.isFVG = true;
      return res;
   }
   if(open[i-1] > open[i] && open[i-1] > close[i] && close[i-1] > open[i] && close[i-1] > close[i]) {
      res.type = FVG_DIFF_DOWN;
      res.level = close[i-1];
      res.gap = MathMax(MathAbs(open[i] - close[i-1]), MathAbs(close[i] - close[i-1]));
      res.isUp = false;
      res.isFVG = true;
      return res;
   }

   // Gap thực sự
   if(low[i] > high[i-1]) {
      res.type = GAP_UP;
      res.level = high[i-1];
      res.gap = low[i] - high[i-1];
      res.isUp = true;
      res.isFVG = false;
      return res;
   }
   if(high[i] < low[i-1]) {
      res.type = GAP_DOWN;
      res.level = low[i-1];
      res.gap = low[i-1] - high[i];
      res.isUp = false;
      res.isFVG = false;
      return res;
   }

   return res;
}

//--- OnCalculate ngắn gọn
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
   int start = MathMax(1, rates_total - MaxBars);
   for(int i=start; i<rates_total-1; i++)
     {
      DetectResult res = DetectFVGGap(i, open, close, high, low);
      if(res.type != NONE)
        {
         string prefix = (res.isFVG ? OBJ_PREFIX : GAP_PREFIX);
         color colorUp = (res.isFVG ? FVGColorUp : GapColorUp);
         color colorDown = (res.isFVG ? FVGColorDown : GapColorDown);
         DrawRay(i, res.level, res.gap, res.isUp, res.isFVG, time, open, close, high, low, rates_total, prefix, colorUp, colorDown);
        }
     }
   return(rates_total);
  }

//--- Vẽ ray nét đứt cho cả FVG và Gap
void DrawRay(int i, double level, double gap, bool isUp, bool isFVG,
             const datetime &time[], const double &open[], const double &close[],
             const double &high[], const double &low[], int rates_total,
             string prefix, color colorUp, color colorDown)
  {
   string obj_name = prefix + IntegerToString(i);
   color  line_color = isUp ? colorUp : colorDown;

   int end_index = rates_total-1;
   bool cut_right = false;

   // Chỉ FVG mới cần check bị quét phải, gap thì ray luôn chỉ từ i-1 đến i
   if(isFVG)
     {
      for(int j=i+1; j<rates_total; j++)
        {
         if((isUp && low[j] <= level) || (!isUp && high[j] >= level))
           {
            end_index = j;
            cut_right = true;
            break;
           }
        }
      if(!cut_right)
        end_index = rates_total-1;
     }
   else
     {
      end_index = i;
      cut_right = false;
     }

   datetime time_start = isFVG ? time[i] : time[i-1];
   datetime time_end   = time[end_index];

   // Vẽ ray nét đứt
   if(ObjectFind(0, obj_name) < 0)
     {
      ObjectCreate(0, obj_name, OBJ_TREND, 0, time_start, level, time_end, level);
      ObjectSetInteger(0, obj_name, OBJPROP_COLOR, line_color);
      ObjectSetInteger(0, obj_name, OBJPROP_WIDTH, FVGLineWidth);
      ObjectSetInteger(0, obj_name, OBJPROP_STYLE, FVGLineStyle);
      ObjectSetInteger(0, obj_name, OBJPROP_RAY_RIGHT, isFVG ? !cut_right : false);
     }
   else
     {
      ObjectMove(0, obj_name, 0, time_start, level);
      ObjectMove(0, obj_name, 1, time_end, level);
      ObjectSetInteger(0, obj_name, OBJPROP_STYLE, FVGLineStyle);
      ObjectSetInteger(0, obj_name, OBJPROP_RAY_RIGHT, isFVG ? !cut_right : false);
     }

   // Label số độ lệch/gap
   string label_name = obj_name + "_label";
   string gap_text = DoubleToString(gap, 2);
   int label_index;
   if(isFVG)
     {
      if(cut_right)
        label_index = (i + end_index)/2;
      else
        label_index = end_index;
     }
   else
     {
      label_index = i;
     }

   if(ObjectFind(0, label_name) < 0)
     {
      ObjectCreate(0, label_name, OBJ_TEXT, 0, time[label_index], level);
      ObjectSetString(0, label_name, OBJPROP_TEXT, gap_text);
      ObjectSetInteger(0, label_name, OBJPROP_COLOR, line_color);
      ObjectSetInteger(0, label_name, OBJPROP_FONTSIZE, 10);
     }
   else
     {
      ObjectMove(0, label_name, 0, time[label_index], level);
      ObjectSetString(0, label_name, OBJPROP_TEXT, gap_text);
     }
  }
