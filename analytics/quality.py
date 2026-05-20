from typing import List, Dict, Any

def score_data_quality(
    options_data: List[Dict[str, Any]],
    bid_ask_spread_threshold: float = 0.50
) -> Dict[str, Any]:
    """
    Evaluate option chain data quality, calculate a quality score (0-100),
    and generate fallback warnings based on market microstructure parameters.
    
    Parameters:
      options_data: List of dicts, each containing:
         - 'strike': float
         - 'type': str ('C' or 'P')
         - 'oi': float
         - 'vol': float
         - 'bid': float
         - 'ask': float
      bid_ask_spread_threshold: Maximum allowed bid-ask spread as a fraction of mid-price (default 50%)
      
    Returns:
      Dict with keys:
        'quality_score': float (0.0 to 100.0)
        'warnings': List[str]
        'high_flow_instability': bool
        'valid_count': int
        'total_count': int
    """
    total_count = len(options_data)
    if total_count == 0:
        return {
            "quality_score": 0.0,
            "warnings": ["No option data available to evaluate."],
            "high_flow_instability": False,
            "valid_count": 0,
            "total_count": 0
        }
        
    valid_count = 0
    high_flow_strikes = []
    wide_spread_strikes = []
    zero_bid_strikes = []
    
    for opt in options_data:
        bid = float(opt.get('bid') or 0.0)
        ask = float(opt.get('ask') or 0.0)
        oi = float(opt.get('oi') or 0.0)
        vol = float(opt.get('vol') or 0.0)
        strike = float(opt.get('strike') or 0.0)
        
        mid = (bid + ask) / 2.0
        
        # 1. Bid-Ask Spread Filter
        if mid > 0:
            spread_pct = (ask - bid) / mid
            if spread_pct > bid_ask_spread_threshold:
                wide_spread_strikes.append(strike)
            else:
                valid_count += 1
        else:
            if bid == 0.0:
                zero_bid_strikes.append(strike)
                
        # 2. Volume vs. OI Check (High Flow Instability)
        if oi > 0 and vol > 2.0 * oi:
            high_flow_strikes.append(strike)
            
    # Calculate base quality score
    # Score is the percentage of options with healthy bid-ask spreads
    quality_score = (valid_count / total_count) * 100.0
    
    warnings = []
    if quality_score < 70.0:
        warnings.append(f"Low Data Quality Alert: Only {quality_score:.1f}% of options have liquid spreads.")
    if wide_spread_strikes:
        warnings.append(f"Wide Bid-Ask Spread detected at {len(wide_spread_strikes)} strikes. Exposure calculations might be noisy.")
    if zero_bid_strikes:
        warnings.append(f"Zero Bid detected at {len(zero_bid_strikes)} strikes (illiquid/deep OTM contracts).")
        
    high_flow_instability = len(high_flow_strikes) > 0
    if high_flow_instability:
        warnings.append(f"High Flow Instability Warning: Daily volume exceeds 200% of open interest at strikes: {sorted(list(set(high_flow_strikes))[:5])}.")
        
    return {
        "quality_score": round(quality_score, 1),
        "warnings": warnings,
        "high_flow_instability": high_flow_instability,
        "valid_count": valid_count,
        "total_count": total_count
    }
