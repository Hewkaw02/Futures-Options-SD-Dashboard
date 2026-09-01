import math
from typing import List, Dict, Any, Optional
import numpy as np

def simulate_price_cones(
    spot: float,
    iv: float,
    days_horizon: int = 30,
    num_paths: int = 5000,
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None
) -> Dict[str, Any]:
    """
    Simulate Geometric Brownian Motion probability cones and barrier touch odds.
    """
    if spot <= 0 or iv <= 0:
        return {'cones': [], 'barrier_odds': {}}
        
    dt = 1.0 / 365.0
    drift = 0.0  # Risk-neutral drift for futures
    sigma = iv
    
    np.random.seed(42)
    # Generate daily steps
    steps = days_horizon
    # Standard normal increments: (num_paths, steps)
    z = np.random.normal(0, 1, size=(num_paths, steps))
    log_returns = (drift - 0.5 * sigma**2) * dt + sigma * math.sqrt(dt) * z
    
    # Cumulative log returns
    cum_returns = np.cumsum(log_returns, axis=1)
    paths = spot * np.exp(cum_returns)  # (num_paths, steps)
    
    # Insert initial spot at t=0
    all_paths = np.hstack([np.full((num_paths, 1), spot), paths])
    
    checkpoints = [1, 3, 5, 10, 15, 20, 30]
    cones = []
    
    for d in checkpoints:
        if d <= steps:
            col = all_paths[:, d]
            cones.append({
                'day': d,
                'p5': round(float(np.percentile(col, 5)), 1),
                'p10': round(float(np.percentile(col, 10)), 1),
                'p25': round(float(np.percentile(col, 25)), 1),
                'p50': round(float(np.percentile(col, 50)), 1),
                'p75': round(float(np.percentile(col, 75)), 1),
                'p90': round(float(np.percentile(col, 90)), 1),
                'p95': round(float(np.percentile(col, 95)), 1),
            })
            
    # Barrier Touch Probabilities across 30 days
    max_path = np.max(all_paths, axis=1)
    min_path = np.min(all_paths, axis=1)
    
    prob_touch_call_wall = 0.0
    if call_wall and call_wall > spot:
        prob_touch_call_wall = float(np.mean(max_path >= call_wall)) * 100.0
        
    prob_touch_put_wall = 0.0
    if put_wall and put_wall < spot:
        prob_touch_put_wall = float(np.mean(min_path <= put_wall)) * 100.0
        
    return {
        'spot': spot,
        'iv_pct': round(iv * 100.0, 2),
        'cones': cones,
        'barrier_odds': {
            'call_wall_strike': call_wall,
            'put_wall_strike': put_wall,
            'prob_touch_call_wall_pct': round(prob_touch_call_wall, 1),
            'prob_touch_put_wall_pct': round(prob_touch_put_wall, 1),
            'prob_stay_in_walls_pct': round(max(0.0, 100.0 - (prob_touch_call_wall + prob_touch_put_wall)), 1)
        }
    }
