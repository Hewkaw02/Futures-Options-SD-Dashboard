import math
from typing import List, Dict, Any, Optional

def calc_term_structure_slope(expiries: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = sorted([e for e in expiries if e.get('dte', 0) > 0 and e.get('iv', 0) > 0], key=lambda x: x['dte'])
    if len(valid) < 2:
        return {
            'slope_30d': 0.0,
            'regime': 'FLAT',
            'front_iv': round(valid[0]['iv'] * 100, 2) if valid else 0.0,
            'back_iv': round(valid[0]['iv'] * 100, 2) if valid else 0.0,
            'front_dte': valid[0]['dte'] if valid else 0,
            'back_dte': valid[0]['dte'] if valid else 0,
            'description': 'Insufficient expiries to compute term structure.'
        }
        
    front = valid[0]
    back = valid[-1]
    
    delta_dte = back['dte'] - front['dte']
    if delta_dte <= 0:
        delta_dte = 1.0
        
    delta_iv = (back['iv'] - front['iv']) * 100.0
    slope_30d = round((delta_iv / delta_dte) * 30.0, 2)
    
    if slope_30d > 0.5:
        regime = 'CONTANGO'
        desc = f'Normal contango (+{slope_30d:.1f}% / 30d). Near-term event risk is low.'
    elif slope_30d < -0.5:
        regime = 'BACKWARDATION'
        desc = f'Backwardation ({slope_30d:.1f}% / 30d). Elevated near-term event risk / hedging demand.'
    else:
        regime = 'FLAT'
        desc = f'Flat term structure ({slope_30d:+.1f}% / 30d). Uniform volatility expectations.'
        
    return {
        'slope_30d': slope_30d,
        'regime': regime,
        'front_iv': round(front['iv'] * 100.0, 2),
        'back_iv': round(back['iv'] * 100.0, 2),
        'front_dte': front['dte'],
        'back_dte': back['dte'],
        'description': desc
    }

def calc_25delta_skew(
    rows: List[Dict[str, Any]],
    spot: float,
    atm_iv: float
) -> Dict[str, Any]:
    calls = [r for r in rows if r.get('Type') in ['Call', 'C'] and r.get('IV', 0) > 0]
    puts = [r for r in rows if r.get('Type') in ['Put', 'P'] and r.get('IV', 0) > 0]
    
    if not calls or not puts:
        return {
            'risk_reversal_25d': 0.0,
            'butterfly_25d': 0.0,
            'call_25d_iv': 0.0,
            'put_25d_iv': 0.0,
            'skew_regime': 'NEUTRAL'
        }
        
    call_25 = None
    if any('Delta' in r and r['Delta'] > 0 for r in calls):
        call_25 = min(calls, key=lambda r: abs(r.get('Delta', 0) - 0.25))
    else:
        otm_call_target = spot * 1.025
        call_25 = min(calls, key=lambda r: abs(r.get('Strike', 0) - otm_call_target))
        
    put_25 = None
    if any('Delta' in r and r['Delta'] < 0 for r in puts):
        put_25 = min(puts, key=lambda r: abs(abs(r.get('Delta', 0)) - 0.25))
    else:
        otm_put_target = spot * 0.975
        put_25 = min(puts, key=lambda r: abs(r.get('Strike', 0) - otm_put_target))
        
    c_iv = call_25.get('IV', 0) * 100.0 if call_25 else atm_iv * 100.0
    p_iv = put_25.get('IV', 0) * 100.0 if put_25 else atm_iv * 100.0
    atm_iv_pct = atm_iv * 100.0
    
    risk_reversal = round(c_iv - p_iv, 2)
    butterfly = round(((c_iv + p_iv) / 2.0) - atm_iv_pct, 2)
    
    if risk_reversal > 1.0:
        skew_regime = 'CALL_SKEW (Bullish Speculation)'
    elif risk_reversal < -1.0:
        skew_regime = 'PUT_SKEW (Bearish Hedging / Fear)'
    else:
        skew_regime = 'BALANCED'
        
    return {
        'risk_reversal_25d': risk_reversal,
        'butterfly_25d': butterfly,
        'call_25d_iv': round(c_iv, 2),
        'put_25d_iv': round(p_iv, 2),
        'skew_regime': skew_regime
    }
