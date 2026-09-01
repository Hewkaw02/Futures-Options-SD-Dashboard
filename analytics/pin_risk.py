import math
from typing import List, Dict, Any, Optional

def calc_pin_risk(
    options_rows: List[Dict[str, Any]],
    spot: float,
    dte: float,
    max_pain_strike: Optional[float] = None
) -> Dict[str, Any]:
    """
    Compute Pin Risk Score, Gamma Concentration, and Expected Pinning Range.
    """
    if spot <= 0 or not options_rows:
        return {
            'pin_score': 0.0,
            'gamma_concentration_pct': 0.0,
            'pinning_zone': [0, 0],
            'pin_magnet_active': False,
            'description': 'No option data for pin risk evaluation.'
        }
        
    total_oi = sum(float(r.get('Open_Interest', 0) or 0) for r in options_rows)
    if total_oi <= 0:
        return {
            'pin_score': 0.0,
            'gamma_concentration_pct': 0.0,
            'pinning_zone': [spot * 0.99, spot * 1.01],
            'pin_magnet_active': False,
            'description': 'Zero Open Interest.'
        }
        
    # Near-ATM OI within 1% of spot
    near_atm_oi = sum(
        float(r.get('Open_Interest', 0) or 0) 
        for r in options_rows 
        if abs(float(r.get('Strike', 0) or 0) - spot) <= (spot * 0.012)
    )
    
    dte_adj = max(dte, 0.25)
    # Pin Risk formula
    concentration_ratio = (near_atm_oi / total_oi) if total_oi > 0 else 0
    pin_score = min(100.0, (concentration_ratio * 100.0) * (1.0 / math.sqrt(dte_adj)))
    
    # Expected Pinning Zone (Cluster around Max Pain or highest OI strike)
    target_strike = max_pain_strike if max_pain_strike and max_pain_strike > 0 else spot
    pin_lower = round(target_strike * 0.995, 1)
    pin_upper = round(target_strike * 1.005, 1)
    
    magnet_active = dte <= 2.5 and pin_score >= 40.0
    
    if magnet_active:
        desc = f'HIGH PIN RISK (Score: {pin_score:.1f}/100, DTE: {dte:.1f}d). Strong dealer gravitational pull toward {target_strike:.1f}.'
    elif dte <= 3.0:
        desc = f'Moderate pin pressure. Expected pinning band between {pin_lower:.1f} and {pin_upper:.1f}.'
    else:
        desc = f'Low pin risk (DTE {dte:.1f}d). Market is free-floating away from expiry compression.'
        
    return {
        'pin_score': round(pin_score, 1),
        'gamma_concentration_pct': round(concentration_ratio * 100.0, 1),
        'pinning_zone': [pin_lower, pin_upper],
        'pin_target_strike': target_strike,
        'pin_magnet_active': magnet_active,
        'description': desc
    }
