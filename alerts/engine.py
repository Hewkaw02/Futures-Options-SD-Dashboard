from typing import List, Dict, Any
from datetime import datetime

def evaluate_market_alerts(
    asset_symbol: str,
    price: float,
    bias_label: str,
    call_wall: float,
    put_wall: float,
    gex_regime: str,
    vrp_data: Dict[str, Any],
    flow_anomalies: List[Dict[str, Any]],
    prev_bias_label: str = ''
) -> List[Dict[str, Any]]:
    alerts = []
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    
    # 1. Wall Breach Alerts
    if call_wall > 0 and price >= call_wall:
        alerts.append({
            'timestamp': ts,
            'asset': asset_symbol,
            'severity': 'CRITICAL',
            'category': 'WALL_BREACH',
            'title': f'🔴 Call Wall Breached at {call_wall:.1f}',
            'detail': f'{asset_symbol} trading at {price:.2f} >= Call Wall {call_wall:.1f}. Monitor for Gamma Squeeze continuation or mean-reversion rejection.'
        })
    elif put_wall > 0 and price <= put_wall:
        alerts.append({
            'timestamp': ts,
            'asset': asset_symbol,
            'severity': 'CRITICAL',
            'category': 'WALL_BREACH',
            'title': f'🟢 Put Wall Breached at {put_wall:.1f}',
            'detail': f'{asset_symbol} trading at {price:.2f} <= Put Wall {put_wall:.1f}. Potential Delta Cascade risk or major demand bounce.'
        })
        
    # 2. GEX Regime Flip Alert
    if 'VOLATILE' in gex_regime.upper() or 'NEGATIVE' in gex_regime.upper():
        alerts.append({
            'timestamp': ts,
            'asset': asset_symbol,
            'severity': 'WARNING',
            'category': 'REGIME_FLIP',
            'title': f'⚡ Negative Gamma Regime Active ({gex_regime})',
            'detail': 'Market Makers are short gamma. Accelerating intraday volatility expected.'
        })
        
    # 3. VRP Mispricing Alert
    vrp_val = vrp_data.get('vrp_pct', 0.0)
    if vrp_val > 4.0:
        alerts.append({
            'timestamp': ts,
            'asset': asset_symbol,
            'severity': 'INFO',
            'category': 'VRP_RICH',
            'title': f'💎 Rich Option Premiums (VRP: +{vrp_val:.1f}%)',
            'detail': 'Implied Volatility heavily overprices realized movement. Premium selling favored.'
        })
    elif vrp_val < -4.0:
        alerts.append({
            'timestamp': ts,
            'asset': asset_symbol,
            'severity': 'INFO',
            'category': 'VRP_CHEAP',
            'title': f'🎯 Discounted Option Premiums (VRP: {vrp_val:.1f}%)',
            'detail': 'Options are statistically cheap relative to price velocity. Long gamma setups favored.'
        })
        
    # 4. Unusual Flow Alert
    if flow_anomalies:
        top_anomaly = flow_anomalies[0]
        alerts.append({
            'timestamp': ts,
            'asset': asset_symbol,
            'severity': 'WARNING',
            'category': 'UNUSUAL_FLOW',
            'title': f'🌊 Flow Spike: {top_anomaly.get("type", "")} {top_anomaly.get("strike", 0)}',
            'detail': f'Volume is {top_anomaly.get("vol_oi_ratio", 0)}x of Open Interest ({int(top_anomaly.get("volume", 0))} contracts).'
        })
        
    # 5. Bias Flip Alert
    if prev_bias_label and prev_bias_label != bias_label:
        if ('BULL' in prev_bias_label and 'BEAR' in bias_label) or ('BEAR' in prev_bias_label and 'BULL' in bias_label):
            alerts.append({
                'timestamp': ts,
                'asset': asset_symbol,
                'severity': 'CRITICAL',
                'category': 'BIAS_REVERSAL',
                'title': f'🔄 Master Bias Reversal: {prev_bias_label} ➔ {bias_label}',
                'detail': f'Institutional bias shifted direction on {asset_symbol}. Re-evaluate existing positions.'
            })
            
    return alerts
