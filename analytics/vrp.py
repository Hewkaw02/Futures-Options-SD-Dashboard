import math
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

def calc_yang_zhang_rv(
    df: pd.DataFrame,
    window: int = 20,
    annualization_factor: float = 365.0
) -> float:
    if df is None or len(df) < max(window, 3):
        return 0.0
        
    sub_df = df.iloc[-window:].copy()
    if isinstance(sub_df.columns, pd.MultiIndex):
        sub_df.columns = [c[0] if isinstance(c, tuple) else c for c in sub_df.columns]
        
    for col in ['Open', 'High', 'Low', 'Close']:
        if col not in sub_df.columns:
            if 'Close' in sub_df.columns:
                returns = np.log(sub_df['Close'] / sub_df['Close'].shift(1)).dropna()
                if len(returns) > 1:
                    return float(returns.std(ddof=1) * math.sqrt(annualization_factor))
            return 0.0

    o = sub_df['Open'].astype(float).values
    h = sub_df['High'].astype(float).values
    l = sub_df['Low'].astype(float).values
    c = sub_df['Close'].astype(float).values
    
    n = len(c)
    if n < 3:
        return 0.0

    log_oc = np.log(o[1:] / c[:-1])
    log_co = np.log(c[1:] / o[1:])
    log_ho = np.log(h[1:] / o[1:])
    log_lo = np.log(l[1:] / o[1:])
    log_hc = np.log(h[1:] / c[1:])
    log_lc = np.log(l[1:] / c[1:])
    
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    
    var_open = np.var(log_oc, ddof=1)
    var_close = np.var(log_co, ddof=1)
    rs = np.mean(log_ho * log_hc + log_lo * log_lc)
    
    var_yz = var_open + k * var_close + (1.0 - k) * rs
    
    if var_yz <= 0.0 or np.isnan(var_yz):
        returns = np.diff(np.log(c))
        if len(returns) > 1:
            var_yz = float(np.var(returns, ddof=1))
        else:
            return 0.0
            
    rv = math.sqrt(max(var_yz, 0.0) * annualization_factor)
    return float(rv)

def calc_parkinson_rv(
    df: pd.DataFrame,
    window: int = 20,
    annualization_factor: float = 365.0
) -> float:
    if df is None or len(df) < max(window, 2):
        return 0.0
    sub_df = df.iloc[-window:].copy()
    if isinstance(sub_df.columns, pd.MultiIndex):
        sub_df.columns = [c[0] if isinstance(c, tuple) else c for c in sub_df.columns]
        
    h = sub_df['High'].astype(float).values
    l = sub_df['Low'].astype(float).values
    
    valid_mask = (l > 0) & (h >= l)
    if not np.any(valid_mask):
        return 0.0
        
    hl_ratio = np.log(h[valid_mask] / l[valid_mask])
    var_p = (1.0 / (4.0 * math.log(2.0))) * np.mean(hl_ratio**2)
    return float(math.sqrt(var_p * annualization_factor))

def calc_vrp(iv: float, rv: float) -> Dict[str, Any]:
    iv_pct = round(iv * 100.0, 2)
    rv_pct = round(rv * 100.0, 2)
    vrp_pct = round(iv_pct - rv_pct, 2)
    
    if vrp_pct > 3.0:
        regime = "EXPENSIVE"
        signal = "SELL_PREMIUM"
        description = f"Implied Vol ({iv_pct}%) > Realized Vol ({rv_pct}%). Net option sellers capture rich premium."
    elif vrp_pct < -3.0:
        regime = "CHEAP"
        signal = "BUY_PREMIUM"
        description = f"Realized Vol ({rv_pct}%) > Implied Vol ({iv_pct}%). Option buyers favored."
    else:
        regime = "FAIR"
        signal = "NEUTRAL"
        description = f"IV ({iv_pct}%) and RV ({rv_pct}%) are balanced (VRP: {vrp_pct:+.1f}%)."
        
    return {
        "iv_pct": iv_pct,
        "rv_pct": rv_pct,
        "vrp_pct": vrp_pct,
        "regime": regime,
        "signal": signal,
        "description": description
    }

def calc_iv_percentile_rank(
    current_iv: float,
    historical_ivs: List[float]
) -> Dict[str, Any]:
    valid_ivs = [x for x in historical_ivs if x > 0 and not np.isnan(x)]
    if not valid_ivs or current_iv <= 0:
        return {"iv_rank": 50.0, "iv_percentile": 50.0, "min_iv": 0.0, "max_iv": 0.0}
        
    min_iv = min(valid_ivs)
    max_iv = max(valid_ivs)
    
    if max_iv > min_iv:
        iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100.0
    else:
        iv_rank = 50.0
        
    lower_count = sum(1 for x in valid_ivs if x < current_iv)
    iv_percentile = (lower_count / len(valid_ivs)) * 100.0
    
    return {
        "iv_rank": round(max(0.0, min(100.0, iv_rank)), 1),
        "iv_percentile": round(max(0.0, min(100.0, iv_percentile)), 1),
        "min_iv": round(min_iv * 100.0, 2),
        "max_iv": round(max_iv * 100.0, 2)
    }
