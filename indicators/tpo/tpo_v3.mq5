//+------------------------------------------------------------------+
//|                                                MarketProfile.mq5 |
//|                             Copyright © 2010-2025, EarnForex.com |
//|                                       https://www.earnforex.com/ |
//+------------------------------------------------------------------+
#property copyright "EarnForex.com"
#property link      "https://www.earnforex.com/indicators/MarketProfile/"
#property version   "1.24"

#property description "Displays the Market Profile indicator. Supports the following sessions:"
#property description "Daily, weekly, monthly"
#property description ""
#property description "Designed for major currency pairs, but should work also with exotic pairs, CFDs, or commodities."
//+------------------------------------------------------------------+
// Rectangle session - a rectangle's name should start with 'MPR' and must not contain an underscore ('_').
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 3
#property indicator_buffers 3
#property indicator_color1  clrGreen
#property indicator_width1  2
#property indicator_type1   DRAW_ARROW
#property indicator_label1  "Developing POC"
#property indicator_color2  clrGoldenrod
#property indicator_width2  2
#property indicator_type2   DRAW_ARROW
#property indicator_label2  "Developing VAH"
#property indicator_color3  clrSalmon
#property indicator_width3  2
#property indicator_type3   DRAW_ARROW
#property indicator_label3  "Developing VAL"

enum color_scheme
{
    Blue_to_Red,       // Blue to Red
    Red_to_Green,      // Red to Green
    Green_to_Blue,     // Green to Blue
    Yellow_to_Cyan,    // Yellow to Cyan
    Magenta_to_Yellow, // Magenta to Yellow
    Cyan_to_Magenta,   // Cyan to Magenta
    Single_Color       // Single Color
};

enum session_period
{
    Daily,
    Weekly,
    Monthly
};

enum sat_sun_solution
{
    Saturday_Sunday_Normal_Days, // Normal sessions
    Ignore_Saturday_Sunday,      // Ignore Saturday and Sunday
    Append_Saturday_Sunday       // Append Saturday and Sunday
};

enum sessions_to_draw_rays
{
    None,
    Previous,
    Current,
    PreviousCurrent, // Previous & Current
    AllPrevious,     // All Previous
    All
};

enum ways_to_stop_rays
{
    Stop_No_Rays,                      // Stop no rays
    Stop_All_Rays,                     // Stop all rays
    Stop_All_Rays_Except_Prev_Session, // Stop all rays except previous session
    Stop_Only_Previous_Session,        // Stop only previous session's rays
};

// Only for dot coloring choice in PutDot() when ColorBullBear == true.
enum bar_direction
{
    Bullish,
    Bearish,
    Neutral
};

enum single_print_type
{
    No,
    Leftside,
    Rightside
};

input group "Main"
input session_period Session                 = Daily;
input datetime       StartFromDate           = __DATE__;        // StartFromDate: lower priority.
input bool           StartFromCurrentSession = true;            // StartFromCurrentSession: higher priority.
input int            SessionsToCount         = 2;               // SessionsToCount: Number of sessions to count Market Profile.
input bool           EnableDevelopingPOC     = false;           // Enable Developing POC
input bool           EnableDevelopingVAHVAL  = false;           // Enable Developing VAH/VAL
input int            ValueAreaPercentage     = 70;              // ValueAreaPercentage: Percentage of TPO's inside Value Area.

input group "Colors and looks"
input color_scheme   ColorScheme              = Blue_to_Red;
input color          SingleColor              = clrBlue;        // SingleColor: if ColorScheme is set to Single Color.
input bool           ColorBullBear            = false;          // ColorBullBear: If true, colors are from bars' direction.
input color          MedianColor              = clrWhite;
input color          ValueAreaSidesColor      = clrWhite;
input color          ValueAreaHighLowColor    = clrWhite;
input ENUM_LINE_STYLE MedianStyle             = STYLE_SOLID;
input ENUM_LINE_STYLE MedianRayStyle          = STYLE_DASH;
input ENUM_LINE_STYLE ValueAreaSidesStyle     = STYLE_SOLID;
input ENUM_LINE_STYLE ValueAreaHighLowStyle   = STYLE_SOLID;
input ENUM_LINE_STYLE ValueAreaRayHighLowStyle= STYLE_DOT;
input int            MedianWidth              = 1;
input int            MedianRayWidth           = 1;
input int            ValueAreaSidesWidth      = 1;
input int            ValueAreaHighLowWidth    = 1;
input int            ValueAreaRayHighLowWidth = 1;
input sessions_to_draw_rays ShowValueAreaRays = None;           // ShowValueAreaRays: draw previous value area high/low rays.
input sessions_to_draw_rays ShowMedianRays    = None;           // ShowMedianRays: draw previous median rays.
input ways_to_stop_rays RaysUntilIntersection = Stop_No_Rays;   // RaysUntilIntersection: which rays stop when hit another MP.
input bool           HideRaysFromInvisibleSessions = false;     // HideRaysFromInvisibleSessions: hide rays from behind the screen.
input int            TimeShiftMinutes         = 0;              // TimeShiftMinutes: shift session + to the left, - to the right.
input bool           ShowKeyValues            = true;           // ShowKeyValues: print out VAH, VAL, POC on chart.
input color          KeyValuesColor           = clrWhite;       // KeyValuesColor: color for VAH, VAL, POC printout.
input int            KeyValuesSize            = 8;              // KeyValuesSize: font size for VAH, VAL, POC printout.
input single_print_type ShowSinglePrint       = No;             // ShowSinglePrint: mark Single Print profile levels.
input bool           SinglePrintRays          = false;          // SinglePrintRays: mark Single Print edges with rays.
input color          SinglePrintColor         = clrGold;
input ENUM_LINE_STYLE SinglePrintRayStyle     = STYLE_SOLID;
input int            SinglePrintRayWidth      = 1;
input color          ProminentMedianColor     = clrYellow;
input ENUM_LINE_STYLE ProminentMedianStyle    = STYLE_SOLID;
input int            ProminentMedianWidth     = 4;
input bool           ShowTPOCounts            = false;          // ShowTPOCounts: Show TPO counts above/below POC.
input color          TPOCountAboveColor       = clrHoneydew;    // TPOCountAboveColor: Color for TPO count above POC.
input color          TPOCountBelowColor       = clrMistyRose;   // TPOCountBelowColor: Color for TPO count below POC.
input bool           RightToLeft              = false;          // RightToLeft: Draw histogram from right to left.

input group "Performance"
input int            PointMultiplier          = 0;      // PointMultiplier: higher value = fewer objects. 0 - adaptive.
input int            ThrottleRedraw           = 0;      // ThrottleRedraw: delay (in seconds) for updating Market Profile.
input bool           DisableHistogram         = false;  // DisableHistogram: do not draw profile, VAH, VAL, and POC still visible.

input group "Miscellaneous"
input sat_sun_solution SaturdaySunday                 = Saturday_Sunday_Normal_Days;
input bool             DisableAlertsOnWrongTimeframes = false;  // Disable alerts on wrong timeframes.
input int              ProminentMedianPercentage      = 101;    // Percentage of Median TPOs out of total for a Prominent one.

datetime RememberSessionStart[];
datetime RememberSessionEnd[];
double   RememberSessionMax[];
double   RememberSessionMin[];
string   RememberSessionSuffix[];
int      SessionsNumber = 0;
int _SessionsToCount = 5; // Number of sessions to count Market Profile.

int PointMultiplier_calculated;     // Will have to be calculated based number digits in a quote if PointMultiplier input is 0.
int DigitsM;                        // Number of digits normalized based on PointMultiplier_calculated.
bool InitFailed;                    // Used for soft INIT_FAILED. Hard INIT_FAILED resets input parameters.
datetime StartDate;                 // Will hold either StartFromDate or iTime(Symbol(), Period(), 0).
double onetick;                     // One normalized pip.
bool FirstRunDone = false;          // If true - OnCalculate() was already executed once.
string Suffix = "_";                // Will store object name suffix depending on timeframe.
int Max_number_of_bars_in_a_session = 1;
int Timer = 0;                      // For throttling updates of market profiles in slow systems.
bool NeedToRestartDrawing = false;  // Global flag for RightToLeft redrawing;
int CleanedUpOn = 0;                // To prevent cleaning up the buffers again and again when the platform just starts.
double ValueAreaPercentage_double = 0.7; // Will be calculated based on the input parameter in OnInit().

sat_sun_solution _SaturdaySunday;   // To change the input value if incompatible with timeframe.
session_period _Session;            // Can be modified during runtime (hotkeys).
string m_FileName;                  // File name to store the session type.

// Used for ColorBullBear.
bar_direction CurrentBarDirection = Neutral;
bar_direction PreviousBarDirection = Neutral;
bool NeedToReviewColors = false;

color_scheme CurrentColorScheme;    // Required due to intraday sessions.

uint LastRecalculationTime = 0;

//+------------------------------------------------------------------+
//| Custom indicator initialization function                         |
//+------------------------------------------------------------------+
int OnInit()
{
    m_FileName = "MP_" + IntegerToString(ChartID()) + ".txt";

    if (!LoadSettingsFromDisk()) // Trying to read the saved session type from file.
    {
        _Session = Session;
    }

    return Initialize();
}

//+------------------------------------------------------------------+
//| Custom indicator deinitialization function                       |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    Deinitialize();

    if (reason == REASON_PARAMETERS) GlobalVariableSet("MP-" + IntegerToString(ChartID()) + "-Parameters", 1);

    if ((reason == REASON_REMOVE) || (reason == REASON_CHARTCLOSE) || (reason == REASON_PROGRAM))
    {
        DeleteSettingsFile();
    }
    else
    {
        SaveSettingsOnDisk();
    }
}

//+------------------------------------------------------------------+
//| Custom Market Profile main iteration function                    |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime& Time[],
                const double& Open[],
                const double& High[],
                const double& Low[],
                const double& Close[],
                const long& tick_volume[],
                const long& volume[],
                const int& spread[]
               )
{
    if (InitFailed)
    {
        if (!DisableAlertsOnWrongTimeframes) Print("Initialization failed. Please see the alert message for details.");
        return 0;
    }

    if (prev_calculated == 0) // Cannot do this inside OnInit() because chart not fully loaded yet.
    {
        InitializeOnetick();
    }

    return OnCalculateMain(rates_total, prev_calculated);
}

int FindSessionStart(const int n, const int rates_total)
{
    if (_Session == Daily) return FindDayStart(n, rates_total);
    else if (_Session == Weekly) return FindWeekStart(n, rates_total);
    else if (_Session == Monthly) return FindMonthStart(n, rates_total);
    return -1;
}

int FindDayStart(const int n, const int rates_total)
{
    if (n >= rates_total) return -1;
    int x = n;
    int time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
    int time_n_day_of_week = time_x_day_of_week;

    // Condition should pass also if Append_Saturday_Sunday is on and it is Sunday or it is Friday but the bar n is on Saturday.
    while ((TimeDayOfYear(iTime(Symbol(), Period(), n) + TimeShiftMinutes * 60) == TimeDayOfYear(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60)) || ((_SaturdaySunday == Append_Saturday_Sunday) && ((time_x_day_of_week == 0) || ((time_x_day_of_week == 5) && (time_n_day_of_week == 6)))))
    {
        x++;
        if (x >= rates_total) break;
        time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
    }

    return (x - 1);
}

int FindWeekStart(const int n, const int rates_total)
{
    if (n >= rates_total) return -1;
    int x = n;
    int time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);

    // Condition should pass also if Append_Saturday_Sunday is on and it is Sunday.
    while ((SameWeek(iTime(Symbol(), Period(), n) + TimeShiftMinutes * 60, iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60)) || ((_SaturdaySunday == Append_Saturday_Sunday) && (time_x_day_of_week == 0)))
    {
        // If Ignore_Saturday_Sunday is on and we stepped into Sunday, stop.
        if ((_SaturdaySunday == Ignore_Saturday_Sunday) && (time_x_day_of_week == 0)) break;
        x++;
        if (x >= rates_total) break;
        time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
    }

    return (x - 1);
}

int FindMonthStart(const int n, const int rates_total)
{
    if (n >= rates_total) return -1;
    int x = n;
    int time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
    // These don't change:
    int time_n_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), n) + TimeShiftMinutes * 60);
    int time_n_day = TimeDay(iTime(Symbol(), Period(), n) + TimeShiftMinutes * 60);
    int time_n_month = TimeMonth(iTime(Symbol(), Period(), n) + TimeShiftMinutes * 60);

    // Condition should pass also if Append_Saturday_Sunday is on and it is Sunday or Saturday the 1st day of month.
    while ((time_n_month == TimeMonth(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60)) || ((_SaturdaySunday == Append_Saturday_Sunday) && ((time_x_day_of_week == 0) || ((time_n_day_of_week == 6) && (time_n_day == 1)))))
    {
        // If month distance somehow becomes greater than 1, break.
        int month_distance = time_n_month - TimeMonth(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
        if (month_distance < 0) month_distance = 12 + month_distance;
        if (month_distance > 1) break;
        // Check if Append_Saturday_Sunday is on and today is Saturday the 1st day of month. Despite it being current month, it should be skipped because it is appended to the previous month. Unless it is the sessionend day, which is the Saturday of the next month attached to this session.
        if (_SaturdaySunday == Append_Saturday_Sunday)
        {
            if ((time_x_day_of_week == 6) && (TimeDay(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) == 1) && (time_n_day != TimeDay(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60))) break;
        }
        // Check if Ignore_Saturday_Sunday is on and today is Sunday or Saturday the 2nd or the 1st day of month. Despite it being current month, it should be skipped because it is ignored.
        if (_SaturdaySunday == Ignore_Saturday_Sunday)
        {
            if (((time_x_day_of_week == 0) || (time_x_day_of_week == 6)) && ((TimeDay(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) == 1) || (TimeDay(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) == 2))) break;
        }
        x++;
        if (x >= rates_total) break;
        time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
    }

    return (x - 1);
}

//+------------------------------------------------------------------+
//| Finds the session's end bar by the session's date.               |
//+------------------------------------------------------------------+
int FindSessionEndByDate(const datetime date, const int rates_total)
{
    if (_Session == Daily) return FindDayEndByDate(date, rates_total);
    else if (_Session == Weekly) return FindWeekEndByDate(date, rates_total);
    else if (_Session == Monthly) return FindMonthEndByDate(date, rates_total);

    return -1;
}

int FindDayEndByDate(const datetime date, const int rates_total)
{
    int x = 0;

    // TimeAbsoluteDay is used for cases when the given date is Dec 30 (#364) and the current date is Jan 1 (#1) for example.
    while ((x < rates_total) && (TimeAbsoluteDay(date + TimeShiftMinutes * 60) < TimeAbsoluteDay(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60)))
    {
        // Check if Append_Saturday_Sunday is on and if the found end of the day is on Saturday and the given date is the previous Friday; or it is a Monday and the sought date is the previous Sunday.
        if (_SaturdaySunday == Append_Saturday_Sunday)
        {
            if (((TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) == 6) || (TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) == 1)) && (TimeAbsoluteDay(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) - TimeAbsoluteDay(date + TimeShiftMinutes * 60) == 1)) break;
        }
        x++;
    }

    return x;
}

int FindWeekEndByDate(const datetime date, const int rates_total)
{
    int x = 0;

    int time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);

    // Condition should pass also if Append_Saturday_Sunday is on and it is Sunday; and also if Ignore_Saturday_Sunday is on and it is Saturday or Sunday.
    while ((SameWeek(date + TimeShiftMinutes * 60, iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) != true) || ((_SaturdaySunday == Append_Saturday_Sunday) && (time_x_day_of_week == 0)) || ((_SaturdaySunday == Ignore_Saturday_Sunday) && ((time_x_day_of_week == 0) || (time_x_day_of_week == 6))))
    {
        x++;
        if (x >= rates_total) break;
        time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
    }

    return x;
}

int FindMonthEndByDate(const datetime date, const int rates_total)
{
    int x = 0;

    int time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);

    // Condition should pass also if Append_Saturday_Sunday is on and it is Sunday; and also if Ignore_Saturday_Sunday is on and it is Saturday or Sunday.
    while ((SameMonth(date + TimeShiftMinutes * 60, iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) != true) || ((_SaturdaySunday == Append_Saturday_Sunday) && (time_x_day_of_week == 0)) || ((_SaturdaySunday == Ignore_Saturday_Sunday) && ((time_x_day_of_week == 0) || (time_x_day_of_week == 6))))
    {
        // Check if Append_Saturday_Sunday is on.
        if (_SaturdaySunday == Append_Saturday_Sunday)
        {
            // Today is Saturday the 1st day of the next month. Despite it being in a next month, it should be appended to the current month.
            if ((time_x_day_of_week == 6) && (TimeDay(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) == 1) && (TimeYear(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) * 12 + TimeMonth(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) - TimeYear(date + TimeShiftMinutes * 60) * 12 - TimeMonth(date + TimeShiftMinutes * 60) == 1)) break;
            if ((TimeDayOfWeek(date + TimeShiftMinutes * 60) == 0) && (TimeYear(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) * 12 + TimeMonth(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60) - TimeYear(date + TimeShiftMinutes * 60) * 12 - TimeMonth(date + TimeShiftMinutes * 60) == 1)) break;
        }
        x++;
        if (x >= rates_total) break;
        time_x_day_of_week = TimeDayOfWeek(iTime(Symbol(), Period(), x) + TimeShiftMinutes * 60);
    }

    return x;
}

int SameWeek(const datetime date1, const datetime date2)
{
    MqlDateTime dt1, dt2;

    TimeToStruct(date1, dt1);
    TimeToStruct(date2, dt2);

    int seconds_from_start = dt1.day_of_week * 24 * 3600 + dt1.hour * 3600 + dt1.min * 60 + dt1.sec;

    if (date1 == date2) return true;
    else if (date2 < date1)
    {
        if (date1 - date2 <= seconds_from_start) return true;
    }
    // 604800 - seconds in one week.
    else if (date2 - date1 < 604800 - seconds_from_start) return true;

    return false;
}

//+------------------------------------------------------------------+
//| Check if two dates are in the same month.                        |
//+------------------------------------------------------------------+
int SameMonth(const datetime date1, const datetime date2)
{
    MqlDateTime dt1, dt2;

    TimeToStruct(date1, dt1);
    TimeToStruct(date2, dt2);

    if ((dt1.mon == dt2.mon) && (dt1.year == dt2.year)) return true;
    return false;
}

void RemoveSinglePrintMark(const double price, const int sessionstart, const string rectangle_prefix)
{
    int t = sessionstart + 1;
    if (ShowSinglePrint == Rightside) t = sessionstart;

    string LastNameStart = " " + TimeToString(iTime(Symbol(), Period(), t)) + " ";
    string LastName = LastNameStart + DoubleToString(price, _Digits);

    ObjectDelete(0, rectangle_prefix + "MPSP" + Suffix + LastName);
}

void PutSinglePrintMark(const double price, const int sessionstart, const string rectangle_prefix)
{
    int t1 = sessionstart + 1, t2 = sessionstart;
    bool fill = true;
    if (ShowSinglePrint == Rightside)
    {
        t1 = sessionstart;
        t2 = sessionstart - 1;
        fill = false;
    }
    string LastNameStart = " " + TimeToString(iTime(Symbol(), Period(), t1)) + " ";
    string LastName = LastNameStart + DoubleToString(price, _Digits);

    // If already there - ignore.
    if (ObjectFind(0, rectangle_prefix + "MPSP" + Suffix + LastName) >= 0) return;
    ObjectCreate(0, rectangle_prefix + "MPSP" + Suffix + LastName, OBJ_RECTANGLE, 0, iTime(Symbol(), Period(), t1), price, iTime(Symbol(), Period(), t2), price - onetick);
    ObjectSetInteger(0, rectangle_prefix + "MPSP" + Suffix + LastName, OBJPROP_COLOR, SinglePrintColor);

    // Fills rectangle.
    ObjectSetInteger(0, rectangle_prefix + "MPSP" + Suffix + LastName, OBJPROP_FILL, fill);
    ObjectSetInteger(0, rectangle_prefix + "MPSP" + Suffix + LastName, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, rectangle_prefix + "MPSP" + Suffix + LastName, OBJPROP_HIDDEN, true);
    ObjectSetString(0, rectangle_prefix + "MPSP" + Suffix + LastName, OBJPROP_TOOLTIP, "Single Print Mark");
}

void PutSinglePrintRay(const double price, const int sessionstart, const string rectangle_prefix, const color spr_color)
{
    datetime t1 = iTime(Symbol(), Period(), sessionstart), t2;
    if (sessionstart - 1 >= 0) t2 = iTime(Symbol(), Period(), sessionstart - 1);
    else t2 = iTime(Symbol(), Period(), sessionstart) + 1;

    if (ShowSinglePrint == Rightside)
    {
        t1 = iTime(Symbol(), Period(), sessionstart);
        t2 = iTime(Symbol(), Period(), sessionstart + 1);
    }

    string LastNameStart = " " + TimeToString(t1) + " ";
    string LastName = LastNameStart + DoubleToString(price, _Digits);

    // If already there - ignore.
    if (ObjectFind(0, rectangle_prefix + "MPSPR" + Suffix + LastName) >= 0) return;
    ObjectCreate(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJ_TREND, 0, t1, price, t2, price);
    ObjectSetInteger(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJPROP_COLOR, spr_color);
    ObjectSetInteger(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJPROP_STYLE, SinglePrintRayStyle);
    ObjectSetInteger(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJPROP_WIDTH, SinglePrintRayWidth);
    ObjectSetInteger(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJPROP_RAY_RIGHT, true);
    ObjectSetInteger(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJPROP_HIDDEN, true);
    ObjectSetString(0, rectangle_prefix + "MPSPR" + Suffix + LastName, OBJPROP_TOOLTIP, "Single Print Ray");
}

datetime PutDot(const double price, const int start_bar, const int range, const int bar, string rectangle_prefix = "", datetime converted_time = 0)
{
    double divisor, color_shift;
    color colour = -1;

    // All dots are with the same date/time for a given origin bar, but with a different price.
    string LastNameStart = " " + TimeToString(iTime(Symbol(), Period(), bar + start_bar)) + " ";
    string LastName = LastNameStart + DoubleToString(price, _Digits);

    if (ColorBullBear) colour = CalculateProperColor();

    // Bull/bear coloring part.
    if (NeedToReviewColors)
    {
        // Finding all dots (rectangle objects) with proper suffix and start of last name (date + time of the bar, but not price).
        // This is needed to change their color if candle changed its direction.
        int obj_total = ObjectsTotal(ChartID(), -1, OBJ_RECTANGLE);
        for (int i = obj_total - 1; i >= 0; i--)
        {
            string obj = ObjectName(ChartID(), i, -1, OBJ_RECTANGLE);
            // Probably some other object.
            if (StringSubstr(obj, 0, StringLen(rectangle_prefix + "MP" + Suffix)) != rectangle_prefix + "MP" + Suffix) continue;
            // Previous bar's dot found.
            if (StringSubstr(obj, 0, StringLen(rectangle_prefix + "MP" + Suffix + LastNameStart)) != rectangle_prefix + "MP" + Suffix + LastNameStart) break;
            // Change color.
            ObjectSetInteger(0, obj, OBJPROP_COLOR, colour);
        }
    }

    if (ObjectFind(0, rectangle_prefix + "MP" + Suffix + LastName) >= 0)
    {
        if ((!RightToLeft) || (converted_time == 0)) return 0; // Normal case;
    }

    datetime time_end, time_start;
    datetime prev_time = converted_time; // For drawing, we need two times.
    if (converted_time != 0) // This is the right-to-left mode and the right-most session.
    {
        // Check if we have started a new right-most session, so the previous one should be cleaned up.
        static datetime prev_time_start_bar = 0;
        if ((iTime(Symbol(), Period(), start_bar) != prev_time_start_bar) && (prev_time_start_bar != 0)) // New right-most session arrived - recalculate everything.
        {
            NeedToRestartDrawing = true;
        }
        prev_time_start_bar = iTime(Symbol(), Period(), start_bar);

        // Find the time:
        int x = -1;
        for (int i = range + 1; i > 0; i--) // + 1 to get a bit "lefter" time in converted_time, and actual dot's time into prev_time.
        {
            prev_time = converted_time;
            if (converted_time == iTime(Symbol(), Period(), 0)) // First time stepped into existing candles.
            {
                x = i + 1; // Remember the position.
                converted_time = iTime(Symbol(), Period(), 1); // Move further.
            }
            else if (converted_time < iTime(Symbol(), Period(), 0))
            {
                if (x == -1) x = iBarShift(Symbol(), Period(), converted_time) + i + 1;
                converted_time = iTime(Symbol(), Period(), x - i); // While inside the existing candles, use existing Time for candles.
            }
            else converted_time -= PeriodSeconds(); // While beyond the current candle, subtract fixed time periods to move left on the time scale.
        }
        time_end = converted_time;
        time_start = prev_time;
    }
    else
    {
        if (start_bar - (range + 1) < 0) time_end = iTime(Symbol(), Period(), 0) + PeriodSeconds(); // Protection from 'Array out of range' error.
        else time_end = iTime(Symbol(), Period(), start_bar - (range + 1));
        time_start = iTime(Symbol(), Period(), start_bar - range);
    }

    if (ObjectFind(0, rectangle_prefix + "MP" + Suffix + LastName) >= 0) // Need to move the rectangle.
    {
        ObjectSetInteger(0, rectangle_prefix  + "MP" + Suffix + LastName, OBJPROP_TIME, 0, time_start);
        ObjectSetInteger(0, rectangle_prefix  + "MP" + Suffix + LastName, OBJPROP_TIME, 1, time_end);
    }
    else ObjectCreate(0, rectangle_prefix + "MP" + Suffix + LastName, OBJ_RECTANGLE, 0, time_start, price, time_end, price - onetick);

    if (!ColorBullBear) // Otherwise, colour is already calculated.
    {
        // Color switching depending on the distance of the bar from the session's beginning.
        int offset1, offset2;
        switch (CurrentColorScheme)
        {
        case Blue_to_Red:
            colour = 0x00FF0000; // clrBlue;
            offset1 = 0x00010000;
            offset2 = 0x00000001;
            break;
        case Red_to_Green:
            colour = 0x000000FF; // clrDarkRed;
            offset1 = 0x00000001;
            offset2 = 0x00000100;
            break;
        case Green_to_Blue:
            colour = 0x0000FF00; // clrDarkGreen;
            offset1 = 0x00000100;
            offset2 = 0x00010000;
            break;
        case Yellow_to_Cyan:
            colour = 0x0000FFFF; // clrYellow;
            offset1 = 0x00000001;
            offset2 = 0x00010000;
            break;
        case Magenta_to_Yellow:
            colour = 0x00FF00FF; // clrMagenta;
            offset1 = 0x00010000;
            offset2 = 0x00000100;
            break;
        case Cyan_to_Magenta:
            colour = 0x00FFFF00; // clrCyan;
            offset1 = 0x00000100;
            offset2 = 0x00000001;
            break;
        case Single_Color:
            colour = SingleColor;
            offset1 = 0;
            offset2 = 0;
            break;
        default:
            colour = SingleColor;
            offset1 = 0;
            offset2 = 0;
            break;
        }

        // No need to do these calculations if plain color is used.
        if (CurrentColorScheme != Single_Color)
        {
            divisor = 1.0 / 0xFF * (double)Max_number_of_bars_in_a_session;

            // bar is negative.
            color_shift = MathFloor((double)bar / divisor);
            // Prevents color overflow.
            
            if ((int)color_shift < -255) color_shift = -255; // -0xFF doesn't work in MT5!

            colour += color((int)color_shift * offset1);
            colour -= color((int)color_shift * offset2);
        }
    }

    ObjectSetInteger(0, rectangle_prefix + "MP" + Suffix + LastName, OBJPROP_COLOR, colour);
    // Fills rectangle.
    ObjectSetInteger(0, rectangle_prefix + "MP" + Suffix + LastName, OBJPROP_FILL, true);
    ObjectSetInteger(0, rectangle_prefix + "MP" + Suffix + LastName, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, rectangle_prefix + "MP" + Suffix + LastName, OBJPROP_HIDDEN, true);

    return time_end;
}

//+------------------------------------------------------------------+
//| Deletes all chart objects created by the indicator.              |
//+------------------------------------------------------------------+
void ObjectCleanup(string rectangle_prefix = "")
{
    // Delete all rectangles with set prefix.
    ObjectsDeleteAll(0, rectangle_prefix + "MP" + Suffix, 0, OBJ_RECTANGLE);
    ObjectsDeleteAll(0, rectangle_prefix + "Median" + Suffix, 0, OBJ_TREND);
    ObjectsDeleteAll(0, rectangle_prefix + "VA_LeftSide" + Suffix, 0, OBJ_TREND);
    ObjectsDeleteAll(0, rectangle_prefix + "VA_RightSide" + Suffix, 0, OBJ_TREND);
    ObjectsDeleteAll(0, rectangle_prefix + "VA_Top" + Suffix, 0, OBJ_TREND);
    ObjectsDeleteAll(0, rectangle_prefix + "VA_Bottom" + Suffix, 0, OBJ_TREND);
    if (ShowValueAreaRays != None)
    {
        // Delete all trendlines with set prefix.
        ObjectsDeleteAll(0, rectangle_prefix + "Value Area HighRay" + Suffix, 0, OBJ_TREND);
        ObjectsDeleteAll(0, rectangle_prefix + "Value Area LowRay" + Suffix, 0, OBJ_TREND);
    }
    if (ShowMedianRays != None)
    {
        // Delete all trendlines with set prefix.
        ObjectsDeleteAll(0, rectangle_prefix + "Median Ray" + Suffix, 0, OBJ_TREND);
    }
    if (ShowKeyValues)
    {
        // Delete all text labels with set prefix.
        ObjectsDeleteAll(0, rectangle_prefix + "VAH" + Suffix, 0, OBJ_TEXT);
        ObjectsDeleteAll(0, rectangle_prefix + "VAL" + Suffix, 0, OBJ_TEXT);
        ObjectsDeleteAll(0, rectangle_prefix + "POC" + Suffix, 0, OBJ_TEXT);
    }
    if (ShowSinglePrint)
    {
        // Delete all Single Print marks.
        ObjectsDeleteAll(0, rectangle_prefix + "MPSP" + Suffix, 0, OBJ_RECTANGLE);
    }
    if (SinglePrintRays)
    {
        // Delete all Single Print rays.
        ObjectsDeleteAll(0, rectangle_prefix + "MPSPR" + Suffix, 0, OBJ_TREND);
    }
    if (ShowTPOCounts)
    {
        ObjectsDeleteAll(0, rectangle_prefix + "TPOCA" + Suffix, 0, OBJ_TEXT);
        ObjectsDeleteAll(0, rectangle_prefix + "TPOCB" + Suffix, 0, OBJ_TEXT);
    }
}

bool GetHoursAndMinutes(string time_string, int& hours, int& minutes, int& time)
{
    if (StringLen(time_string) == 4) time_string = "0" + time_string;

    if (
        // Wrong length.
        (StringLen(time_string) != 5) ||
        // Wrong separator.
        (time_string[2] != ':') ||
        // Wrong first number (only 24 hours in a day).
        ((time_string[0] < '0') || (time_string[0] > '2')) ||
        // 00 to 09 and 10 to 19.
        (((time_string[0] == '0') || (time_string[0] == '1')) && ((time_string[1] < '0') || (time_string[1] > '9'))) ||
        // 20 to 23.
        ((time_string[0] == '2') && ((time_string[1] < '0') || (time_string[1] > '3'))) ||
        // 0M to 5M.
        ((time_string[3] < '0') || (time_string[3] > '5')) ||
        // M0 to M9.
        ((time_string[4] < '0') || (time_string[4] > '9'))
    )
    {
        Print("Wrong time string: ", time_string, ". Please use HH:MM format.");
        return false;
    }

    string result[];
    int number_of_substrings = StringSplit(time_string, ':', result);
    hours = (int)StringToInteger(result[0]);
    minutes = (int)StringToInteger(result[1]);
    time = hours * 60 + minutes;

    return true;
}
bool ProcessSession(const int sessionstart, const int sessionend, const int i, const int rates_total)
{
    string rectangle_prefix = ""; // Only for rectangle sessions

    if (sessionstart >= rates_total) return false; // Data not yet ready.
    if (onetick == 0) return false; // onetick cannot be zero.

    double SessionMax = DBL_MIN, SessionMin = DBL_MAX;

    // Find the session's high and low.
    for (int bar = sessionstart; bar >= sessionend; bar--)
    {
        if (iHigh(Symbol(), Period(), bar) > SessionMax) SessionMax = iHigh(Symbol(), Period(), bar);
        if (iLow(Symbol(), Period(), bar) < SessionMin) SessionMin = iLow(Symbol(), Period(), bar);
    }
    SessionMax = NormalizeDouble(SessionMax, DigitsM);
    SessionMin = NormalizeDouble(SessionMin, DigitsM);

    int session_counter = i;

    // Find iTime(Symbol(), Period(), sessionstart) among RememberSessionStart[].
    bool need_to_increment = true;

    for (int j = 0; j < SessionsNumber; j++)
    {
        if (RememberSessionStart[j] == iTime(Symbol(), Period(), sessionstart))
        {
            need_to_increment = false;
            session_counter = j; // Real number of the session.
            break;
        }
    }
    // Raise the number of sessions and resize arrays.
    if (need_to_increment)
    {
        SessionsNumber++;
        session_counter = SessionsNumber - 1; // Newest session.
        ArrayResize(RememberSessionMax, SessionsNumber);
        ArrayResize(RememberSessionMin, SessionsNumber);
        ArrayResize(RememberSessionStart, SessionsNumber);
        ArrayResize(RememberSessionSuffix, SessionsNumber);
        ArrayResize(RememberSessionEnd, SessionsNumber); // Used only for Arrows.
    }

    // Adjust SessionMin, SessionMax for onetick granularity.
    SessionMax = NormalizeDouble(MathRound(SessionMax / onetick) * onetick, DigitsM);
    SessionMin = NormalizeDouble(MathRound(SessionMin / onetick) * onetick, DigitsM);

    RememberSessionMax[session_counter] = SessionMax;
    RememberSessionMin[session_counter] = SessionMin;
    RememberSessionStart[session_counter] = iTime(Symbol(), Period(), sessionstart);
    RememberSessionSuffix[session_counter] = Suffix;
    RememberSessionEnd[session_counter] = iTime(Symbol(), Period(), sessionend); // Used only for Arrows.

    static double PreviousSessionMax = DBL_MIN;
    static datetime PreviousSessionStartTime = 0;
    // Reset PreviousSessionMax when a new session becomes the 'latest one'.
    if (iTime(Symbol(), Period(), sessionstart) > PreviousSessionStartTime)
    {
        PreviousSessionMax = DBL_MIN;
        PreviousSessionStartTime = iTime(Symbol(), Period(), sessionstart);
    }
    if ((FirstRunDone) && (i == _SessionsToCount - 1) && (PointMultiplier_calculated > 1)) // Updating the latest trading session.
    {
        if (SessionMax - PreviousSessionMax < onetick) // SessionMax increased only slightly - too small to use the new value with the current onetick.
        {
            SessionMax = PreviousSessionMax; // Do not update session max.
        }
        else
        {
            if (PreviousSessionMax != DBL_MIN)
            {
                // Calculate number of increments.
                double nc = (SessionMax - PreviousSessionMax) / onetick;
                // Adjust SessionMax.
                SessionMax = NormalizeDouble(PreviousSessionMax + MathRound(nc) * onetick, DigitsM);
            }
            PreviousSessionMax = SessionMax;
        }
    }

    int TPOperPrice[];
    // Possible price levels if multiplied to integer.
    int max = (int)MathRound((SessionMax - SessionMin) / onetick + 2); // + 2 because further we will be possibly checking array at SessionMax + 1.
    ArrayResize(TPOperPrice, max);
    ArrayInitialize(TPOperPrice, 0);

    bool SinglePrintTracking_array[]; // For SinglePrint rays.
    if (SinglePrintRays)
    {
        ArrayResize(SinglePrintTracking_array, max);
        ArrayInitialize(SinglePrintTracking_array, false);
    }
    
    int MaxRange = 0; // Maximum distance from session start to the drawn dot.
    double PriceOfMaxRange = 0; // Level of the maximum range, required to draw Median.
    double DistanceToCenter = DBL_MAX; // Closest distance to center for the Median.

    datetime converted_time = 0;
    datetime converted_end_time = 0;
    datetime min_converted_end_time = UINT_MAX;
    if ((RightToLeft) && (sessionend == 0))
    {
        int dummy_subwindow;
        double dummy_price;
        ChartXYToTimePrice(0, (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS), 0, dummy_subwindow, converted_time, dummy_price);
    }

    int TotalTPO = 0; // Total amount of dots (TPO's).

    // Going through all possible quotes from session's High to session's Low.
    for (double price = SessionMax; price >= SessionMin; price -= onetick)
    {
        price = NormalizeDouble(price, DigitsM);
        int range = 0; // Distance from first bar to the current bar.

        // Going through all bars of the session to see if the price was encountered here.
        for (int bar = sessionstart; bar >= sessionend; bar--)
        {
            // Price is encountered in the given bar.
            if ((price >= iLow(Symbol(), Period(), bar)) && (price <= iHigh(Symbol(), Period(), bar)))
            {
                // Update maximum distance from session's start to the found bar (needed for Median).
                // Using the center-most Median if there are more than one.
                if ((MaxRange < range) || ((MaxRange == range) && (MathAbs(price - (SessionMin + (SessionMax - SessionMin) / 2)) < DistanceToCenter)))
                {
                    MaxRange = range;
                    PriceOfMaxRange = price;
                    DistanceToCenter = MathAbs(price - (SessionMin + (SessionMax - SessionMin) / 2));
                }

                if (!DisableHistogram)
                {
                    if (ColorBullBear)
                    {
                        // These are needed in all cases when we color dots according to bullish/bearish bars.
                        double close = iClose(NULL, PERIOD_CURRENT, bar);
                        double open = iOpen(NULL, PERIOD_CURRENT, bar);
                        if (close == open) CurrentBarDirection = Neutral;
                        else if (close > open) CurrentBarDirection = Bullish;
                        else if (close < open) CurrentBarDirection = Bearish;

                        // This is for recoloring of the dots from the current (most-latest) bar.
                        if (bar == 0)
                        {
                            if (PreviousBarDirection == CurrentBarDirection) NeedToReviewColors = false;
                            else
                            {
                                NeedToReviewColors = true;
                                PreviousBarDirection = CurrentBarDirection;
                            }
                        }
                    }

                    // Draws rectangle.
                    if (!RightToLeft) PutDot(price, sessionstart, range, bar - sessionstart, rectangle_prefix);
                    // Inverted drawing.
                    else
                    {
                        converted_end_time = PutDot(price, sessionstart, range, bar - sessionstart, rectangle_prefix, converted_time);
                        if (converted_end_time < min_converted_end_time) min_converted_end_time = converted_end_time; // Find the leftmost time to use for the left border of the value area.
                    }
                }

                // Remember the number of encountered bars for this price.
                int index = (int)MathRound((price - SessionMin) / onetick);
                TPOperPrice[index]++;
                range++;
                TotalTPO++;
            }
        }
        // Single print marking is due at this price.
        if (ShowSinglePrint)
        {
            if (range == 1) PutSinglePrintMark(price, sessionstart, rectangle_prefix);
            else if (range > 1) RemoveSinglePrintMark(price, sessionstart, rectangle_prefix); // Remove single print max if it exists.
        }
        
        if (SinglePrintRays)
        {
            int index = (int)MathRound((price - SessionMin) / onetick);
            if (range == 1) SinglePrintTracking_array[index] = true; // Remember the single print's position relative to the price.
            else SinglePrintTracking_array[index] = false;
        }
    }

    // Single Print Rays
    // Go through all prices again, check TPOs - whether they are single and whether they aren't bordered by another single print TPOs?
    if (SinglePrintRays)
    {
        color spr_color = SinglePrintColor; // Normal ray color.
        if ((HideRaysFromInvisibleSessions) && (iTime(Symbol(), Period(), (int)ChartGetInteger(ChartID(), CHART_FIRST_VISIBLE_BAR)) >= iTime(Symbol(), Period(), sessionstart))) spr_color = clrNONE; // Hide rays if behind the screen.

        for (double price = SessionMax; price >= SessionMin; price -= onetick)
        {
            price = NormalizeDouble(price, DigitsM);
            int index = (int)MathRound((price - SessionMin) / onetick);
            if (SinglePrintTracking_array[index])
            {
                if (price == SessionMax) // Top of the session.
                {
                    PutSinglePrintRay(price, sessionstart, rectangle_prefix, spr_color);
                }
                else
                {
                    if ((index + 1 < ArraySize(SinglePrintTracking_array)) && (SinglePrintTracking_array[index + 1] == false)) // Above is a non-single print.
                    {
                        PutSinglePrintRay(price, sessionstart, rectangle_prefix, spr_color);
                    }
                    else
                    {
                        RemoveSinglePrintRay(price, sessionstart, rectangle_prefix);
                    }
                }
                if (price == SessionMin) // Bottom of the session.
                {
                    PutSinglePrintRay(price - onetick, sessionstart, rectangle_prefix, spr_color);
                }
                else
                {
                    if ((index - 1 >= 0) && (SinglePrintTracking_array[index - 1] == false)) // Below is a non-single print.
                    {
                        PutSinglePrintRay(price - onetick, sessionstart, rectangle_prefix, spr_color);
                    }
                    else
                    {
                        RemoveSinglePrintRay(price - onetick, sessionstart, rectangle_prefix);
                    }
                }
            }
            else
            {
                // Attempt to remove a horizontal line below the "potentially no longer existing" single print mark.
                RemoveSinglePrintRay(price - onetick, sessionstart, rectangle_prefix);
            }
        }
    }
    
    FirstRunDone = true;
    Timer = (int)TimeLocal();
    return rates_total;
}

//+------------------------------------------------------------------+
//| Removes a Single Print Ray from the chart.                       |
//+------------------------------------------------------------------+
void RemoveSinglePrintRay(double price, int sessionstart, string rectangle_prefix = "")
{
    string LastName = " " + TimeToString(iTime(Symbol(), Period(), sessionstart)) + " " + DoubleToString(price, _Digits);
    string obj_name = rectangle_prefix + "MPSPR" + Suffix + LastName;
    ObjectDelete(0, obj_name);
}
