import math
from typing import List, Dict, Any, Optional

def calc_volume_imbalance(call_vol: float, put_vol: float) -> Dict[str, Any]:
    total_vol = call_vol + put_vol
    if total_vol <= 0:
        return {
            'imbalance': 0.0,
            'call_vol': 0.0,
            'put_vol': 0.0,
            'call_share_pct': 50.0,
            'put_share_pct': 50.0,
            'bias': 'NEUTRAL'
        }
        
    imbalance = (call_vol - put_vol) / total_vol
    call_share = (call_vol / total_vol) * 100.0
    put_share = (put_vol / total_vol) * 100.0
    
    if imbalance > 0.20:
        bias = 'AGGRESSIVE_CALL_FLOW'
    elif imbalance < -0.20:
        bias = 'AGGRESSIVE_PUT_FLOW'
    else:
        bias = 'BALANCED_FLOW'
        
    return {
        'imbalance': round(imbalance, 3),
        'call_vol': float(call_vol),
        'put_vol': float(put_vol),
        'call_share_pct': round(call_share, 1),
        'put_share_pct': round(put_share, 1),
        'bias': bias
    }

def detect_unusual_flow_spikes(
    rows: List[Dict[str, Any]],
    volume_to_oi_threshold: float = 2.0,
    min_volume_contracts: int = 50
) -> List[Dict[str, Any]]:
    anomalies = []
    for r in rows:
        vol = float(r.get('Volume', 0) or r.get('vol', 0) or 0)
        oi = float(r.get('Open_Interest', 0) or r.get('oi', 0) or 0)
        strike = float(r.get('Strike', 0) or r.get('strike', 0) or 0)
        opt_type = str(r.get('Type', '') or r.get('type', '')).upper()
        
        if vol >= min_volume_contracts:
            ratio = (vol / oi) if oi > 0 else 999.0
            if ratio >= volume_to_oi_threshold:
                anomalies.append({
                    'strike': strike,
                    'type': opt_type,
                    'volume': vol,
                    'oi': oi,
                    'vol_oi_ratio': round(ratio, 2),
                    'severity': 'HIGH' if ratio > 5.0 else 'MEDIUM',
                    'note': f'Volume ({int(vol)}) is {ratio:.1f}x of Open Interest ({int(oi)})'
                })
                
    return sorted(anomalies, key=lambda x: -x['vol_oi_ratio'])

def calc_vpin_score(
    volume_buckets: List[Dict[str, float]]
) -> Dict[str, Any]:
    if not volume_buckets:
        return {'vpin': 0.0, 'toxicity_level': 'LOW', 'description': 'No flow data.'}
        
    total_abs_imbalance = 0.0
    total_volume = 0.0
    
    for b in volume_buckets:
        v_buy = b.get('buy_vol', 0.0)
        v_sell = b.get('sell_vol', 0.0)
        total_abs_imbalance += abs(v_buy - v_sell)
        total_volume += (v_buy + v_sell)
        
    if total_volume <= 0:
        return {'vpin': 0.0, 'toxicity_level': 'LOW', 'description': 'Zero traded volume.'}
        
    vpin = total_abs_imbalance / total_volume
    vpin_val = round(vpin, 3)
    
    if vpin_val > 0.60:
        tox = 'CRITICAL'
        desc = f'VPIN {vpin_val:.2f}: Severe toxic order flow detected. Institutional positioning high.'
    elif vpin_val > 0.40:
        tox = 'ELEVATED'
        desc = f'VPIN {vpin_val:.2f}: Elevated informed trading pressure.'
    else:
        tox = 'NORMAL'
        desc = f'VPIN {vpin_val:.2f}: Order flow is balanced.'
        
    return {
        'vpin': vpin_val,
        'toxicity_level': tox,
        'description': desc
    }
