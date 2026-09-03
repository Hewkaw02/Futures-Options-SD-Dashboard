from typing import Dict, Any, List
import numpy as np

def extract_quant_feature_vector(
    bias: Dict[str, Any],
    vrp: Dict[str, Any],
    skew: Dict[str, Any],
    flow: Dict[str, Any],
    corr: Dict[str, Any],
    pin: Dict[str, Any]
) -> Dict[str, float]:
    """
    Extract structured normalized quantitative features for regime classification.
    """
    # 1. Price vs Walls
    price = float(bias.get('price', 0.0) or 0.0)
    cw = float(bias.get('wall_resistance', 0.0) or 0.0)
    pw = float(bias.get('wall_support', 0.0) or 0.0)
    
    dist_cw = ((cw - price) / price * 100.0) if price > 0 and cw > 0 else 2.0
    dist_pw = ((price - pw) / price * 100.0) if price > 0 and pw > 0 else 2.0
    
    # 2. VRP & Vol
    vrp_val = float(vrp.get('vrp_pct', 0.0) or 0.0)
    iv_val = float(vrp.get('iv_pct', 20.0) or 20.0)
    
    # 3. Skew
    rr25 = float(skew.get('risk_reversal_25d', 0.0) or 0.0) if skew else 0.0
    bf25 = float(skew.get('butterfly_25d', 0.0) or 0.0) if skew else 0.0
    
    # 4. Flow Imbalance
    flow_imb = float(flow.get('imbalance', {}).get('imbalance', 0.0) or 0.0) if flow else 0.0
    
    # 5. GEX Sign (+1 for stable, -1 for volatile)
    gex_str = str(bias.get('gex', '')).upper()
    gex_sign = 1.0 if 'STABLE' in gex_str else (-1.0 if 'VOLTL' in gex_str or 'VOLATILE' in gex_str else 0.0)
    
    # 6. PCR Volume
    pcr_v = float(bias.get('pcr_vol', 1.0) or 1.0)
    
    # 7. Pin Risk
    pin_score = float(pin.get('pin_score', 0.0) or 0.0) if pin else 0.0
    
    return {
        'dist_call_wall_pct': dist_cw,
        'dist_put_wall_pct': dist_pw,
        'vrp_pct': vrp_val,
        'iv_pct': iv_val,
        'rr25_skew': rr25,
        'bf25_butterfly': bf25,
        'flow_imbalance': flow_imb,
        'gex_sign': gex_sign,
        'pcr_vol': pcr_v,
        'pin_score': pin_score
    }
