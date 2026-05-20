import math

def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)

def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def black76_greeks(
    F: float,
    K: float,
    T: float,
    sigma: float,
    r: float = 0.05,
    option_type: str = "C"
) -> dict:
    """
    Calculate option Greeks using the Black-76 model for futures options.
    
    Parameters:
      F : Futures price (mark price)
      K : Strike price
      T : Time to expiration in years (e.g., DTE / 365.0)
      sigma : Implied volatility (decimal, e.g., 0.15 for 15%)
      r : Risk-free rate (decimal, default 0.05)
      option_type : "C" for Call, "P" for Put
      
    Returns:
      dict with keys: 'delta', 'gamma', 'vega', 'vanna', 'charm'
    """
    # Guard against invalid inputs
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "vanna": 0.0, "charm": 0.0}

    discount = math.exp(-r * T)
    std_dev = sigma * math.sqrt(T)
    
    d1 = (math.log(F / K) + 0.5 * (sigma**2) * T) / std_dev
    d2 = d1 - std_dev
    
    pdf_d1 = norm_pdf(d1)
    cdf_d1 = norm_cdf(d1)
    cdf_minus_d1 = norm_cdf(-d1)
    
    # 1. Delta
    if option_type == "C":
        delta = discount * cdf_d1
    else:
        delta = -discount * cdf_minus_d1
        
    # 2. Gamma
    gamma = discount * pdf_d1 / (F * std_dev)
    
    # 3. Vega
    vega = discount * F * math.sqrt(T) * pdf_d1
    
    # 4. Vanna (d_delta / d_sigma)
    # Vanna is identical for calls and puts in Black-76
    vanna = -discount * pdf_d1 * (d2 / sigma)
    
    # 5. Charm (d_delta / d_time)
    # In years, so rate of change per year. Divide by 365 to get daily charm.
    if option_type == "C":
        charm = -r * discount * cdf_d1 - discount * pdf_d1 * (d2 / (2.0 * T))
    else:
        charm = r * discount * cdf_minus_d1 - discount * pdf_d1 * (d2 / (2.0 * T))
        
    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "vanna": vanna,
        "charm": charm
    }

def calculate_dealer_exposures(
    oi: float,
    delta: float,
    gamma: float,
    vega: float,
    vanna: float,
    charm: float,
    spot: float,
    multiplier: float,
    option_type: str,
    dealer_assumed_side: str = "short"
) -> dict:
    """
    Calculate dollar-notional dealer exposures for a single option contract.
    
    Parameters:
      oi : Open Interest
      delta : Option Delta
      gamma : Option Gamma
      vega : Option Vega
      vanna : Option Vanna
      charm : Option Charm (per year)
      spot : Futures price
      multiplier : Contract multiplier (e.g., MES=5, ES=50)
      option_type : "C" or "P"
      dealer_assumed_side : "short" (MM is short) or "long" (MM is long)
      
    Returns:
      dict with GEX, DEX, Vanna Exposure, and Charm Exposure
    """
    # Determine the MM position sign based on assumption
    # Under standard 'short' dealer assumption, customers buy options -> dealer is short
    position_sign = -1.0 if dealer_assumed_side == "short" else 1.0
    
    # 1. GEX (Gamma Exposure per 1% underlying move)
    # GEX = Position * OI * Gamma * Spot^2 * 0.01 * multiplier
    # Standard sign conventions: short calls and short puts both have negative GEX
    gex = position_sign * oi * gamma * (spot**2) * 0.01 * multiplier
    
    # 2. DEX (Delta Exposure)
    # DEX = Position * OI * Delta * Spot * multiplier
    dex = position_sign * oi * delta * spot * multiplier
    
    # 3. Vanna Exposure (volatility risk)
    # Vanna Exposure is sensitivity of Delta to Volatility
    # vanna_exp = Position * OI * Vanna * multiplier
    vanna_exp = position_sign * oi * vanna * multiplier
    
    # 4. Charm Exposure (Delta Decay rate per day)
    # charm_exp = Position * OI * (Charm / 365.0) * Spot * multiplier
    charm_exp = position_sign * oi * (charm / 365.0) * spot * multiplier
    
    return {
        "gex": gex,
        "dex": dex,
        "vanna_exp": vanna_exp,
        "charm_exp": charm_exp
    }
