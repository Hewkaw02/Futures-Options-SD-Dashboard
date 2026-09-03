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

def classify_oi_volume_quadrant(
    volume: float,
    delta_oi: float,
    min_vol: float = 50.0,
    churn_threshold_pct: float = 0.15
) -> Dict[str, Any]:
    """
    Classify options activity into institutional 4-quadrants:
    - Volume Up + Positive Delta OI: Accumulation (new long/short position opening)
    - Volume Up + Negative Delta OI: Liquidation (unwinding / de-risking)
    - Volume Up + Flat Delta OI: Day Trading (churn / scalp turnover)
    - Low Volume: Inactive
    """
    if volume < min_vol:
        return {'quadrant': 'INACTIVE', 'badge': '—', 'desc': 'Low volume'}

    abs_doi = abs(delta_oi)
    if abs_doi < (volume * churn_threshold_pct):
        return {
            'quadrant': 'DAY_TRADING',
            'badge': '⚪ CHURN/SCALP',
            'desc': f'High turnover ({int(volume)} contracts) with flat OI change ({int(delta_oi)}). Speculative day trading.'
        }
    elif delta_oi > 0:
        return {
            'quadrant': 'ACCUMULATION',
            'badge': '🟢 ACCUMULATING',
            'desc': f'Volume ({int(volume)}) confirmed by positive ΔOI (+{int(delta_oi)}). Institutional position building.'
        }
    else:
        return {
            'quadrant': 'LIQUIDATION',
            'badge': '🔴 DE-RISKING',
            'desc': f'Volume ({int(volume)}) accompanied by OI contraction ({int(delta_oi)}). Position unwinding / profit taking.'
        }

def decompose_strike_flow(
    strike_records: List[Dict[str, Any]],
    min_vol: float = 50.0
) -> Dict[str, Any]:
    """
    Scan strike records to aggregate institutional accumulation vs liquidation vs day trading.
    """
    accumulations = []
    liquidations = []
    day_trades = []

    for r in strike_records:
        strike = float(r.get('strike', 0.0) or 0.0)
        # Calls
        c_v = float(r.get('call_vol', 0.0) or 0.0)
        c_doi = float(r.get('call_doi', 0.0) or 0.0)
        c_res = classify_oi_volume_quadrant(c_v, c_doi, min_vol=min_vol)
        if c_res['quadrant'] == 'ACCUMULATION':
            accumulations.append({'strike': strike, 'type': 'CALL', 'volume': c_v, 'delta_oi': c_doi, 'badge': c_res['badge']})
        elif c_res['quadrant'] == 'LIQUIDATION':
            liquidations.append({'strike': strike, 'type': 'CALL', 'volume': c_v, 'delta_oi': c_doi, 'badge': c_res['badge']})
        elif c_res['quadrant'] == 'DAY_TRADING':
            day_trades.append({'strike': strike, 'type': 'CALL', 'volume': c_v, 'delta_oi': c_doi, 'badge': c_res['badge']})

        # Puts
        p_v = float(r.get('put_vol', 0.0) or 0.0)
        p_doi = float(r.get('put_doi', 0.0) or 0.0)
        p_res = classify_oi_volume_quadrant(p_v, p_doi, min_vol=min_vol)
        if p_res['quadrant'] == 'ACCUMULATION':
            accumulations.append({'strike': strike, 'type': 'PUT', 'volume': p_v, 'delta_oi': p_doi, 'badge': p_res['badge']})
        elif p_res['quadrant'] == 'LIQUIDATION':
            liquidations.append({'strike': strike, 'type': 'PUT', 'volume': p_v, 'delta_oi': p_doi, 'badge': p_res['badge']})
        elif p_res['quadrant'] == 'DAY_TRADING':
            day_trades.append({'strike': strike, 'type': 'PUT', 'volume': p_v, 'delta_oi': p_doi, 'badge': p_res['badge']})

    dominant = 'ACCUMULATION' if len(accumulations) > len(liquidations) else (
        'LIQUIDATION' if len(liquidations) > len(accumulations) else 'DAY_TRADING'
    )

    return {
        'dominant_regime': dominant,
        'accumulation_strikes': sorted(accumulations, key=lambda x: -x['delta_oi']),
        'liquidation_strikes': sorted(liquidations, key=lambda x: x['delta_oi']),
        'day_trading_strikes': sorted(day_trades, key=lambda x: -x['volume']),
        'summary': f"{len(accumulations)} strikes accumulating, {len(liquidations)} de-risking, {len(day_trades)} day-traded."
    }

def detect_calendar_roll_activity(
    front_oi_changes: Dict[float, float],
    back_oi_changes: Dict[float, float],
    min_roll_contracts: float = 100.0,
    min_roll_ratio: float = 0.50
) -> List[Dict[str, Any]]:
    """
    Detect multi-expiry calendar roll activity where front-month positions are unwound
    and rolled into back-month contracts at the same or adjacent strike.
    """
    detected_rolls = []
    common_strikes = sorted(set(front_oi_changes.keys()).intersection(set(back_oi_changes.keys())))

    for s in common_strikes:
        f_doi = front_oi_changes.get(s, 0.0)
        b_doi = back_oi_changes.get(s, 0.0)

        # Roll signature: Front month losing contracts and Back month gaining
        if f_doi <= -min_roll_contracts and b_doi >= (min_roll_contracts * min_roll_ratio):
            ratio = min(1.0, abs(b_doi / f_doi)) if f_doi != 0 else 0.0
            detected_rolls.append({
                'strike': float(s),
                'front_delta_oi': float(f_doi),
                'back_delta_oi': float(b_doi),
                'roll_ratio': round(ratio, 2),
                'roll_status': 'ACTIVE_CALENDAR_ROLL',
                'description': f"Strike {s:,.1f}: {int(abs(f_doi))} contracts unwound in front month and rolled into back month (+{int(b_doi)} contracts, {int(ratio*100)}% roll-through)."
            })

    return sorted(detected_rolls, key=lambda x: -x['back_delta_oi'])


