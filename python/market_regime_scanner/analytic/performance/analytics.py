
import numpy as np
import polars as pl
import pandas as pd
from typing import List, Dict, Optional
from collections import Counter

def calculate_regime_decay(regimes: List[str]) -> Dict[str, Dict]:
    """
    Calculate the probability of regime persistence and decay.
    
    Args:
        regimes: List of regime strings (e.g., ["BALANCE", "BALANCE", "IMBALANCE", ...])
    
    Returns:
        Dictionary with decay stats per regime type.
        {
            "BALANCE": {
                "avg_duration": 4.5,
                "max_duration": 12,
                "history": [2, 5, 4, ...],
                "probability_decay_after_n": {1: 0.1, 2: 0.2, ...}
            }
        }
    """
    if not regimes:
        return {}

    # 1. Compress to Run-Length Encoding
    # e.g. [("BALANCE", 5), ("IMBALANCE", 2), ...]
    runs = []
    if not regimes:
        return {}
        
    current_reg = regimes[0]
    count = 1
    for r in regimes[1:]:
        if r == current_reg:
            count += 1
        else:
            runs.append((current_reg, count))
            current_reg = r
            count = 1
    runs.append((current_reg, count))
    
    # 2. Group by Regime Type
    stats = {}
    for r_type, duration in runs:
        if r_type not in stats:
            stats[r_type] = []
        stats[r_type].append(duration)
        
    # 3. Calculate Metrics
    results = {}
    for r_type, durations in stats.items():
        durations = np.array(durations)
        avg = np.mean(durations)
        median = np.median(durations)
        max_d = np.max(durations)
        
        # Decay Probability: P(End | Age = t)
        # Count how many times it lasted exactly t vs >= t
        counts = Counter(durations)
        max_t = max(counts.keys())
        decay_prob = {}
        
        remaining = len(durations)
        for t in range(1, max_t + 1):
            ended_at_t = counts.get(t, 0)
            # Probability of ending at t given it reached t
            if remaining > 0:
                prob = ended_at_t / remaining
                decay_prob[t] = round(prob, 2)
            else:
                decay_prob[t] = 1.0
            
            remaining -= ended_at_t
            if remaining <= 0: break
            
        results[r_type] = {
            "count": len(durations),
            "avg_duration": float(f"{avg:.2f}"),
            "median": int(median),
            "max": int(max_d),
            "decay_prob": decay_prob
        }
        
    return results

def monte_carlo_simulation(trades_pnl: List[float], n_simulations: int = 10000) -> Dict:
    """
    Perform Monte Carlo simulation on trade sequence.
    
    Args:
        trades_pnl: List of PnL values (absolute or %)
        n_simulations: Number of shuffles
        
    Returns:
        Dict with worst case stats (Max DD, Max DD duration, etc.)
    """
    if not trades_pnl:
        return {}

    pnls = np.array(trades_pnl)
    original_dd = _calculate_max_drawdown(pnls)
    
    sim_dds = []
    
    # Vectorized might be hard for DD, looping is okay for 10k * len(trades) if len is small
    # For large N, we might need optimization. 150 trades * 10k is fast.
    
    for _ in range(n_simulations):
        np.random.shuffle(pnls)
        dd = _calculate_max_drawdown(pnls)
        sim_dds.append(dd)
        
    sim_dds = np.array(sim_dds)
    
    return {
        "original_max_dd": original_dd,
        "worst_case_dd": np.max(sim_dds), # DD is usually positive number representing loss? 
        # _calculate_max_drawdown usually returns negative for easy calc or positive magnitude
        # Let's assume it returns Magnitude (positive)
        "avg_max_dd": np.mean(sim_dds),
        "p95_max_dd": np.percentile(sim_dds, 95),
        "p99_max_dd": np.percentile(sim_dds, 99)
    }

def _calculate_max_drawdown(pnls):
    """Calculate Max Drawdown magnitude from PnL sequence."""
    equity = np.cumsum(pnls)
    if len(equity) == 0: return 0.0
    
    # To handle equity starting at 0 properly
    # Peak is mostly cumulative sum max
    # But if we want initial balance? Assume 0.
    
    peak = -999999999
    max_dd = 0
    
    running_equity = 0
    max_equity = 0
    
    # Fast loop or vector
    # Vectorized:
    cum_ret = np.cumsum(pnls)
    # We need to account for start at 0
    cum_ret = np.insert(cum_ret, 0, 0)
    
    peaks = np.maximum.accumulate(cum_ret)
    drawdowns = peaks - cum_ret
    return np.max(drawdowns)

def risk_of_ruin(win_rate: float, payoff_ratio: float, risk_per_trade: float) -> float:
    """
    Calculate Risk of Ruin using standard formula.
    
    Args:
        win_rate: 0.0 to 1.0 (e.g. 0.5)
        payoff_ratio: Avg Win / Avg Loss (absolute)
        risk_per_trade: % risk (e.g. 0.01 for 1%)
    
    Returns:
        Probability of ruin (0.0 to 1.0)
    """
    # Formula: ((1 - WR) / (WR * Payoff)) ^ (1 / Risk) ? 
    # Or simpler approximate: e ^ (-2 * E * B / S^2) ... complex
    
    # Common simplified formula for "Ruin" (loss of capital) 
    # Ruin = ((1 - Edge/1) / (1 + Edge/1)) ^ Units ?
    
    # Let's use the Perry Kaufman approximation or simply:
    # risk_of_ruin = ((1 - W) / (1 + W)) ^ units ? No
    
    # Using formula: R = ((1-(W*(P+1)-1))/ (W*(P+1)-1)) ... complicated
    
    # Let's use a simpler heuristic or iterative calculation if < 50%
    # If Expectancy > 0, RoR < 1. 
    
    # Standard formula for "infinite horizon":
    # R = ((1 - WR) / (WR * Payoff)) ** Risk_Units? No not Risk Units.
    
    # Let's use the formula:
    # Z = (WR * Payoff - (1 - WR)) / SD ? 
    
    # Let's stick to a robust calculation:
    # If WR * Payoff <= (1 - WR), Ruin is 100%. (Negative expectancy)
    if win_rate * payoff_ratio <= (1 - win_rate):
        return 1.0
        
    # Empirical calculation:
    e = win_rate * payoff_ratio - (1 - win_rate)
    # This is rough variance based
    
    # Let's just return a placeholder explanation or specific simpler formula
    # Ralph Vince formula:
    # Risk of Ruin = ((1 - A) / (1 + A)) ^ U
    # Where A = Edge, U = Units of capital.
    
    # Let's assume standard Kelly-like approximation
    # For user report, maybe simpler is better:
    # "If you risk 2% per trade, and WR drops to X, you die."
    
    # Let's implement a simulation-based Ruin check instead for accuracy?
    # No, formula is faster.
    
    # Using: R = ( (1 - WR) / (WR * Payoff) ) ^ (1 / Risk_Pct)? 
    # For small risk. 
    # Example: WR 0.5, Payoff 1.5, Risk 0.01
    
    try:
        base = (1 - win_rate) / (win_rate * payoff_ratio)
        if base >= 1: 
            return 1.0
        # Exponent is Capital / Risk_Amount = 1 / risk_per_trade
        return base ** (1 / risk_per_trade)
    except:
        return 0.0

def equity_correlation(asset_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate correlation matrix of equity curves.
    
    Args:
        asset_returns: DataFrame where columns are asset names, index is date, values are daily PnL (or % return).
    
    Returns:
        Correlation matrix DataFrame.
    """
    return asset_returns.corr()

def calculate_confidence_interval(wins, total, confidence=0.95):
    """Wilson Score Interval for Win Rate."""
    if total == 0: return 0.0, 0.0
    p_hat = wins / total
    
    # Z-score for 95% is approx 1.96
    z = 1.96
    
    denominator = 1 + z**2/total
    center = (p_hat + z**2/(2*total)) / denominator
    margin = z * np.sqrt((p_hat*(1-p_hat) + z**2/(4*total))/total) / denominator
    
    return max(0, center - margin), min(1, center + margin)

def calculate_sharpe_sortino(returns, periods=252, risk_free_rate=0.04):
    """Calculate Annualized Sharpe and Sortino Ratios."""
    if len(returns) < 2: return 0.0, 0.0
    excess_returns = returns - (risk_free_rate / periods)
    std = returns.std()
    downside_std = returns[returns < 0].std()
    
    sharpe = (excess_returns.mean() / std * np.sqrt(periods)) if std > 0 else 0
    sortino = (excess_returns.mean() / downside_std * np.sqrt(periods)) if (downside_std > 0 and not np.isnan(downside_std)) else 0
    return sharpe, sortino

def ulcer_index(equity_curve):
    """Calculate Ulcer Index."""
    if len(equity_curve) < 1: return 0.0
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    squared_dd = drawdown ** 2
    return np.sqrt(squared_dd.mean())

def block_bootstrap(returns, n_sims=1000, block_size=20):
    """Perform Block Bootstrap resampling."""
    n = len(returns)
    if n < block_size: return [], []
    
    sim_cagrs = []
    sim_max_dds = []
    
    for _ in range(n_sims):
        synthetic_returns = []
        while len(synthetic_returns) < n:
            start_idx = np.random.randint(0, n - block_size)
            block = returns[start_idx : start_idx + block_size]
            synthetic_returns.extend(block)
        
        synthetic_returns = np.array(synthetic_returns[:n])
        
        cum_ret = np.prod(1 + synthetic_returns)
        cagr = cum_ret ** (252/n) - 1 if n > 0 else 0
        
        eq = np.cumprod(1 + synthetic_returns)
        pk = np.maximum.accumulate(eq)
        dd = (eq - pk) / pk
        max_dd = dd.min()
        
        sim_cagrs.append(cagr)
        sim_max_dds.append(max_dd)
        
    return sim_cagrs, sim_max_dds

def calculate_portfolio_metrics(df):
    """Generalized trade-level metrics for a DataFrame of trades."""
    if df.empty: return {}
    
    n = len(df)
    wins = df[df['swing_profit'] > 0]
    losses = df[df['swing_profit'] <= 0]
    n_wins = len(wins)
    wr = n_wins / n if n > 0 else 0
    
    avg_win = wins['swing_profit'].mean() if not wins.empty else 0
    avg_loss = abs(losses['swing_profit'].mean()) if not losses.empty else 1.0
    payoff = avg_win / avg_loss if avg_loss > 0 else 0
    expectancy = (wr * avg_win) - ((1-wr) * avg_loss)
    
    # Max Drawdown
    equity = df['swing_profit'].cumsum()
    peak = equity.cummax()
    dd = peak - equity
    max_dd = dd.max()
    
    return {
        "trades": n,
        "win_rate": wr,
        "expectancy": expectancy,
        "payoff": payoff,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss
    }
