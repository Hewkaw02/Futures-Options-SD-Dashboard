import math
from typing import List, Dict, Any, Optional
from analytics.exposure import black76_greeks, calculate_dealer_exposures

def run_stress_scenarios(
    options_rows: List[Dict[str, Any]],
    spot: float,
    dte: float,
    multiplier: float = 100.0,
    shifts: List[float] = [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03],
    iv_shifts: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Simulate market maker hedging shocks under spot price shifts and event IV shifts (Vanna Rally / Crush).
    """
    if spot <= 0 or not options_rows:
        return {'scenarios': [], 'vanna_rally_scenarios': [], 'gamma_flip_stress': None, 'gex_cliff_strike': None}
        
    T = max(dte, 0.5) / 365.0
    r = 0.05
    
    scenario_results = []
    base_dex = 0.0
    base_gex = 0.0
    
    # 1. Spot Price Shocks
    for shift in shifts:
        hypo_spot = spot * (1.0 + shift)
        total_gex = 0.0
        total_dex = 0.0
        total_vanna = 0.0
        
        for r_opt in options_rows:
            strike = float(r_opt.get('Strike', 0) or 0)
            oi = float(r_opt.get('Open_Interest', 0) or r_opt.get('OI', 0) or 0)
            iv = float(r_opt.get('IV', 0) or 0)
            opt_type = str(r_opt.get('Type', '')).upper()
            type_char = 'C' if 'C' in opt_type else 'P'
            
            if strike <= 0 or oi <= 0 or iv <= 0:
                continue
                
            greeks = black76_greeks(F=hypo_spot, K=strike, T=T, sigma=iv, r=r, option_type=type_char)
            exp = calculate_dealer_exposures(
                oi=oi,
                delta=greeks['delta'],
                gamma=greeks['gamma'],
                vega=greeks['vega'],
                vanna=greeks['vanna'],
                charm=greeks['charm'],
                spot=hypo_spot,
                multiplier=multiplier,
                option_type=type_char,
                dealer_assumed_side='short',
                strike=strike,
                dealer_model='asymmetric'
            )
            total_gex += exp['gex']
            total_dex += exp['dex']
            total_vanna += exp['vanna_exp']
            
        if shift == 0.0:
            base_dex = total_dex
            base_gex = total_gex
            
        scenario_results.append({
            'shift_pct': round(shift * 100.0, 1),
            'hypo_price': round(hypo_spot, 2),
            'total_gex': round(total_gex, 2),
            'total_dex': round(total_dex, 2),
            'gex_regime': 'STABLE (Positive Gamma)' if total_gex > 0 else 'VOLATILE (Negative Gamma)',
            'vanna_exposure': round(total_vanna, 2)
        })
        
    # Calculate dealer rebalancing requirement for each spot scenario
    for s in scenario_results:
        s['dealer_delta_hedge_demand'] = round(s['total_dex'] - base_dex, 2)

    # 2. Event IV Shocks (Vanna Rally / IV Crush Simulator)
    if iv_shifts is None:
        iv_shifts = [-0.05, -0.025, 0.0, 0.025, 0.05]

    vanna_rally_results = []
    for iv_s in iv_shifts:
        total_dex_iv = 0.0
        total_vanna_iv = 0.0

        for r_opt in options_rows:
            strike = float(r_opt.get('Strike', 0) or 0)
            oi = float(r_opt.get('Open_Interest', 0) or r_opt.get('OI', 0) or 0)
            iv = float(r_opt.get('IV', 0) or 0)
            opt_type = str(r_opt.get('Type', '')).upper()
            type_char = 'C' if 'C' in opt_type else 'P'

            if strike <= 0 or oi <= 0 or iv <= 0:
                continue

            hypo_iv = max(0.01, iv + iv_s)
            greeks = black76_greeks(F=spot, K=strike, T=T, sigma=hypo_iv, r=r, option_type=type_char)
            exp = calculate_dealer_exposures(
                oi=oi,
                delta=greeks['delta'],
                gamma=greeks['gamma'],
                vega=greeks['vega'],
                vanna=greeks['vanna'],
                charm=greeks['charm'],
                spot=spot,
                multiplier=multiplier,
                option_type=type_char,
                dealer_assumed_side='short',
                strike=strike,
                dealer_model='asymmetric'
            )
            total_dex_iv += exp['dex']
            total_vanna_iv += exp['vanna_exp']

        rebalance_usd = round(total_dex_iv - base_dex, 2)
        contract_size = spot * multiplier if (spot > 0 and multiplier > 0) else 1.0
        rebalance_contracts = round(rebalance_usd / contract_size, 1)

        if rebalance_usd > 0:
            direction = 'BUY_UNDERLYING (Vanna Rally)'
        elif rebalance_usd < 0:
            direction = 'SELL_UNDERLYING'
        else:
            direction = 'NEUTRAL'

        vanna_rally_results.append({
            'iv_shift_pct': round(iv_s * 100.0, 1),
            'dealer_rebalance_usd': rebalance_usd,
            'dealer_rebalance_contracts': rebalance_contracts,
            'vanna_rally_direction': direction
        })
        
    return {
        'base_price': spot,
        'base_gex': round(base_gex, 2),
        'base_dex': round(base_dex, 2),
        'scenarios': scenario_results,
        'vanna_rally_scenarios': vanna_rally_results,
        'gex_cliff_risk': any(s['total_gex'] < 0 for s in scenario_results if s['shift_pct'] < 0)
    }

