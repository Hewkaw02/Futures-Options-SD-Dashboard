from typing import List, Tuple

def interpolate_atm_iv(spot: float, strike_ivs: List[Tuple[float, float]]) -> float:
    """
    Interpolate the Implied Volatility at the exact spot price from a list of (strike, iv) tuples.
    Uses linear interpolation between the two nearest flanking strikes.
    
    Parameters:
      spot : Current futures mark price
      strike_ivs : List of tuples (strike_price, implied_volatility)
      
    Returns:
      Interpolated ATM IV as a decimal (e.g., 0.15). If list is empty, returns 0.0.
    """
    # Filter out invalid or zero IVs
    valid_pairs = [(strike, iv) for strike, iv in strike_ivs if iv > 0 and strike > 0]
    if not valid_pairs:
        return 0.0
        
    # Sort by strike price
    valid_pairs.sort(key=lambda x: x[0])
    
    # If only one valid pair exists, return its IV
    if len(valid_pairs) == 1:
        return valid_pairs[0][1]
        
    # Check if spot is outside the range of strikes
    if spot <= valid_pairs[0][0]:
        return valid_pairs[0][1]
    if spot >= valid_pairs[-1][0]:
        return valid_pairs[-1][1]
        
    # Find the flanking strikes
    lower_pair = None
    upper_pair = None
    
    for i in range(len(valid_pairs) - 1):
        k1, iv1 = valid_pairs[i]
        k2, iv2 = valid_pairs[i+1]
        if k1 <= spot <= k2:
            lower_pair = (k1, iv1)
            upper_pair = (k2, iv2)
            break
            
    if lower_pair and upper_pair:
        k1, iv1 = lower_pair
        k2, iv2 = upper_pair
        # Linear interpolation formula: y = y1 + (x - x1) * (y2 - y1) / (k2 - k1)
        interpolated_iv = iv1 + (spot - k1) * (iv2 - iv1) / (k2 - k1)
        return interpolated_iv
        
    # Fallback to the nearest strike by absolute distance
    nearest_pair = min(valid_pairs, key=lambda x: abs(x[0] - spot))
    return nearest_pair[1]
