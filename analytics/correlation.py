import math
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

def calc_asset_correlations(
    candles_dict: Dict[str, pd.DataFrame],
    lookback_days: int = 30
) -> Dict[str, Any]:
    """
    Compute Cross-Asset Rolling Correlations, Macro Regime, and Divergence Signals.
    """
    price_series = {}
    for asset, df in candles_dict.items():
        if df is not None and not df.empty and 'Close' in df.columns:
            # Resample or take daily close
            s = df['Close'].dropna()
            if not s.empty:
                price_series[asset] = s
                
    if len(price_series) < 2:
        return {
            'matrix': {},
            'macro_regime': 'DECORRELATED / NEUTRAL',
            'gc_es_corr': 0.0,
            'es_nq_corr': 0.0,
            'gc_nq_corr': 0.0,
            'divergence_detected': False,
            'description': 'Insufficient asset data for cross-market correlation.'
        }
        
    comb_df = pd.DataFrame(price_series).ffill().dropna()
    if len(comb_df) < 5:
        return {
            'matrix': {},
            'macro_regime': 'NEUTRAL',
            'gc_es_corr': 0.0,
            'es_nq_corr': 0.0,
            'gc_nq_corr': 0.0,
            'divergence_detected': False,
            'description': 'Too few overlapping price bars.'
        }
        
    ret_df = np.log(comb_df / comb_df.shift(1)).dropna()
    sub_ret = ret_df.iloc[-lookback_days:] if len(ret_df) >= lookback_days else ret_df
    
    corr_mat = sub_ret.corr().to_dict()
    
    gc_es = corr_mat.get('GC', {}).get('ES', corr_mat.get('Gold', {}).get('S&P 500', 0.0))
    es_nq = corr_mat.get('ES', {}).get('NQ', corr_mat.get('S&P 500', {}).get('NASDAQ', 0.0))
    gc_nq = corr_mat.get('GC', {}).get('NQ', corr_mat.get('Gold', {}).get('NASDAQ', 0.0))
    
    # Check 5-day momentum
    recent_5d = sub_ret.iloc[-5:].sum() if len(sub_ret) >= 5 else sub_ret.sum()
    es_ret = recent_5d.get('ES', recent_5d.get('S&P 500', 0.0))
    gc_ret = recent_5d.get('GC', recent_5d.get('Gold', 0.0))
    
    # Macro Regime Classification
    if es_ret > 0.005 and gc_ret < -0.002:
        macro_regime = 'RISK_ON (Equity Inflow / Gold Outflow)'
        desc = 'Equities rallying with Gold under pressure. Capital favoring risk assets.'
    elif es_ret < -0.005 and gc_ret > 0.005:
        macro_regime = 'RISK_OFF (Flight to Safe Haven)'
        desc = 'Equities declining while Gold bids up. Capital fleeing to safe-haven assets.'
    elif gc_es > 0.60:
        macro_regime = 'MACRO_INFLATION / DOLLAR_DEBASEMENT'
        desc = 'Gold and Equities strongly positively correlated. Driven by broad liquidity / currency moves.'
    elif es_nq < 0.60:
        macro_regime = 'EQUITY_INTERNALS_DIVERGENCE'
        desc = 'S&P 500 and NASDAQ decoupling. Sector rotation or tech concentration divergence.'
    else:
        macro_regime = 'BALANCED_CORRELATION'
        desc = f'Normal inter-market correlation (ES/NQ: {es_nq:.2f}, GC/ES: {gc_es:.2f}).'
        
    divergence = abs(gc_es) > 0.75 or (es_nq < 0.50 and len(sub_ret) >= 10)
    
    return {
        'matrix': corr_mat,
        'macro_regime': macro_regime,
        'gc_es_corr': round(gc_es, 2),
        'es_nq_corr': round(es_nq, 2),
        'gc_nq_corr': round(gc_nq, 2),
        'divergence_detected': divergence,
        'description': desc
    }
