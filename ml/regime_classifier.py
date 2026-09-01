import math
from typing import Dict, Any, Optional

def predict_market_regime(features: Dict[str, float]) -> Dict[str, Any]:
    """
    Calibrated quantitative probabilistic regime classifier.
    Blends Multi-Factor Model with logistic link functions.
    """
    # Feature scores
    flow_imb = features.get('flow_imbalance', 0.0)
    rr25 = features.get('rr25_skew', 0.0)
    pcr = features.get('pcr_vol', 1.0)
    gex_sign = features.get('gex_sign', 0.0)
    vrp = features.get('vrp_pct', 0.0)
    dist_cw = features.get('dist_call_wall_pct', 2.0)
    dist_pw = features.get('dist_put_wall_pct', 2.0)
    pin_score = features.get('pin_score', 0.0)
    
    # Linear Bullish Logit: Flow + CallSkew - PCR + Wall Proximity
    z_bull = (1.5 * flow_imb) + (0.3 * rr25) - (0.8 * (pcr - 1.0)) + (0.5 if dist_pw < 0.5 else 0.0)
    # Linear Bearish Logit
    z_bear = (-1.5 * flow_imb) - (0.3 * rr25) + (0.8 * (pcr - 1.0)) + (0.5 if dist_cw < 0.5 else 0.0)
    # Range Logit (High pin risk, high positive GEX, rich VRP)
    z_range = (0.02 * pin_score) + (0.5 * gex_sign) + (0.2 * vrp)
    
    # Softmax probabilities
    exp_bull = math.exp(max(-10, min(10, z_bull)))
    exp_bear = math.exp(max(-10, min(10, z_bear)))
    exp_range = math.exp(max(-10, min(10, z_range)))
    total_exp = exp_bull + exp_bear + exp_range
    
    p_bull = round(exp_bull / total_exp, 3)
    p_bear = round(exp_bear / total_exp, 3)
    p_range = round(exp_range / total_exp, 3)
    
    # Decision
    max_p = max(p_bull, p_bear, p_range)
    if max_p == p_bull and p_bull > 0.40:
        regime = 'MOMENTUM_BULL'
        action = 'CALL_SIDE_ACCELERATION'
        desc = f'Prob(Bull)={p_bull*100:.1f}%. Bullish order flow and call skew dominance.'
    elif max_p == p_bear and p_bear > 0.40:
        regime = 'MOMENTUM_BEAR'
        action = 'PUT_SIDE_DEFENSE'
        desc = f'Prob(Bear)={p_bear*100:.1f}%. Elevated put flow and downside hedging pressure.'
    else:
        regime = 'GAMMA_PINNED_RANGE'
        action = 'RANGE_MEAN_REVERSION'
        desc = f'Prob(Range)={p_range*100:.1f}%. Stable positive gamma dampening volatility.'
        
    confidence = int(max_p * 100)
    
    return {
        'regime': regime,
        'action_signal': action,
        'prob_bull': p_bull,
        'prob_bear': p_bear,
        'prob_range': p_range,
        'confidence_pct': confidence,
        'description': desc
    }
