//+------------------------------------------------------------------+
//| Point & Figure Chart Indicator                                   |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0

input double BoxSize = 100;      // Kích thước 1 box (point)
input int ReversalBox = 3;       // Số box đảo chiều

int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &Time[],
                const double &Open[],
                const double &High[],
                const double &Low[],
                const double &Close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
    // Xóa object cũ
    for(int i=ObjectsTotal(0)-1; i>=0; i--)
    {
        string name = ObjectName(0, i);
        if(StringFind(name, "PNF_") == 0)
            ObjectDelete(0, name);
    }

    double last_price = Close[0];
    int col = 0;
    bool isX = true; // true: X, false: O

    for(int i=1; i<rates_total; i++)
    {
        double diff = Close[i] - last_price;
        if(isX)
        {
            if(diff >= BoxSize*_Point)
            {
                col++;
                string name = StringFormat("PNF_%d", col);
                ObjectCreate(0, name, OBJ_TEXT, 0, Time[i], Close[i]);
                ObjectSetString(0, name, OBJPROP_TEXT, "X");
                ObjectSetInteger(0, name, OBJPROP_COLOR, clrBlue);
                last_price = Close[i];
            }
            else if(diff <= -BoxSize*_Point*ReversalBox)
            {
                isX = false;
                col++;
                string name = StringFormat("PNF_%d", col);
                ObjectCreate(0, name, OBJ_TEXT, 0, Time[i], Close[i]);
                ObjectSetString(0, name, OBJPROP_TEXT, "O");
                ObjectSetInteger(0, name, OBJPROP_COLOR, clrRed);
                last_price = Close[i];
            }
        }
        else // O
        {
            if(diff <= -BoxSize*_Point)
            {
                col++;
                string name = StringFormat("PNF_%d", col);
                ObjectCreate(0, name, OBJ_TEXT, 0, Time[i], Close[i]);
                ObjectSetString(0, name, OBJPROP_TEXT, "O");
                ObjectSetInteger(0, name, OBJPROP_COLOR, clrRed);
                last_price = Close[i];
            }
            else if(diff >= BoxSize*_Point*ReversalBox)
            {
                isX = true;
                col++;
                string name = StringFormat("PNF_%d", col);
                ObjectCreate(0, name, OBJ_TEXT, 0, Time[i], Close[i]);
                ObjectSetString(0, name, OBJPROP_TEXT, "X");
                ObjectSetInteger(0, name, OBJPROP_COLOR, clrBlue);
                last_price = Close[i];
            }
        }
    }
    return(rates_total);
}
