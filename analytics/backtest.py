import os
import glob
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
import math

ASSET_MAP = {
    'GOLD': 'GC',
    'S&P 500': 'ES',
    'NASDAQ': 'NQ',
    'GC': 'GC',
    'ES': 'ES',
    'NQ': 'NQ'
}

def load_historical_signals(results_root: str = 'trading_results') -> pd.DataFrame:
    root = Path(results_root)
    if not root.exists():
        return pd.DataFrame()
        
    records = []
    pattern = str(root / '*' / '*' / 'master_bias_report_*.csv')
    files = sorted(glob.glob(pattern))
    
    for fpath in files:
        p = Path(fpath)
        hour = p.parent.name
        date = p.parent.parent.name
        ts_str = f'{date} {hour[:2]}:{hour[2:]}'
        
        try:
            df = pd.read_csv(fpath)
            for _, row in df.iterrows():
                asset = str(row.get('Asset', '')).strip()
                bias = str(row.get('Bias', '')).strip()
                conf = str(row.get('Conf%', '')).replace('%', '').strip()
                price = float(row.get('Price', 0.0) or 0.0)
                iv = str(row.get('IV%', '')).replace('%', '').strip()
                pcr_v = float(row.get('PCR(V)', 0.0) or 0.0)
                skew = str(row.get('Skew%', '')).replace('%', '').strip()
                
                records.append({
                    'timestamp_str': ts_str,
                    'date': date,
                    'hour': hour,
                    'asset': asset,
                    'asset_symbol': ASSET_MAP.get(asset.upper(), asset),
                    'bias': bias,
                    'confidence_pct': float(conf) if conf and conf != '—' else 0.0,
                    'signal_price': price,
                    'iv_pct': float(iv) if iv and iv != '—' else 0.0,
                    'pcr_vol': pcr_v,
                    'skew_pct': float(skew) if skew and skew != '—' else 0.0,
                    'file_path': str(fpath)
                })
        except Exception:
            continue
            
    df_out = pd.DataFrame(records)
    if not df_out.empty:
        df_out['dt'] = pd.to_datetime(df_out['timestamp_str'], errors='coerce')
        df_out = df_out.sort_values('dt').reset_index(drop=True)
    return df_out

def evaluate_signal_performance(
    signals_df: pd.DataFrame,
    candles_dict: Dict[str, pd.DataFrame],
    horizons_hours: List[int] = [1, 3, 6, 24]
) -> Dict[str, Any]:
    if signals_df.empty:
        return {'total_signals': 0, 'evaluated_signals': 0, 'accuracy_pct': 0.0, 'summary': 'No signals found'}
        
    results = []
    
    for _, sig in signals_df.iterrows():
        asset = sig.get('asset_symbol', sig['asset'])
        sig_price = sig['signal_price']
        bias = sig['bias']
        sig_dt = sig.get('dt')
        
        if sig_price <= 0 or not sig_dt or pd.isna(sig_dt):
            continue
            
        is_bull = 'BULL' in bias.upper()
        is_bear = 'BEAR' in bias.upper()
        
        if not is_bull and not is_bear:
            continue
            
        c_df = candles_dict.get(asset)
        if c_df is None or c_df.empty:
            c_df = candles_dict.get(sig['asset'])
            
        if c_df is None or c_df.empty:
            continue
            
        c_df = c_df.copy()
        if not isinstance(c_df.index, pd.DatetimeIndex):
            if 'Datetime' in c_df.columns:
                c_df = c_df.set_index('Datetime')
            elif 'Date' in c_df.columns:
                c_df = c_df.set_index('Date')
                
        if getattr(c_df.index, 'tz', None) is not None:
            c_df.index = c_df.index.tz_localize(None)
            
        forward_returns = {}
        for h in horizons_hours:
            target_dt = sig_dt + pd.Timedelta(hours=h)
            future_bars = c_df[c_df.index >= target_dt]
            if not future_bars.empty:
                f_price = float(future_bars.iloc[0]['Close'])
                ret_pct = ((f_price - sig_price) / sig_price) * 100.0
                win = (ret_pct > 0) if is_bull else (ret_pct < 0)
                forward_returns[f'{h}h_ret_pct'] = ret_pct
                forward_returns[f'{h}h_win'] = win
                
        if '3h_win' in forward_returns or '1h_win' in forward_returns:
            row_res = dict(sig)
            row_res.update(forward_returns)
            results.append(row_res)
            
    res_df = pd.DataFrame(results)
    if res_df.empty:
        return {
            'total_signals': len(signals_df),
            'evaluated_signals': 0,
            'overall_accuracy_pct': 0.0,
            'bull_accuracy_pct': 0.0,
            'bear_accuracy_pct': 0.0,
            'profit_factor': 0.0,
            'sharpe_ratio': 0.0
        }
        
    win_col = '3h_win' if '3h_win' in res_df.columns else ('1h_win' if '1h_win' in res_df.columns else None)
    ret_col = '3h_ret_pct' if '3h_ret_pct' in res_df.columns else ('1h_ret_pct' if '1h_ret_pct' in res_df.columns else None)
    
    if win_col:
        overall_acc = (res_df[win_col].sum() / len(res_df)) * 100.0
        bull_df = res_df[res_df['bias'].str.contains('BULL', case=False, na=False)]
        bear_df = res_df[res_df['bias'].str.contains('BEAR', case=False, na=False)]
        
        bull_acc = (bull_df[win_col].sum() / len(bull_df) * 100.0) if len(bull_df) > 0 else 0.0
        bear_acc = (bear_df[win_col].sum() / len(bear_df) * 100.0) if len(bear_df) > 0 else 0.0
    else:
        overall_acc, bull_acc, bear_acc = 0.0, 0.0, 0.0
        
    if ret_col:
        pnl = res_df.apply(lambda r: r[ret_col] if 'BULL' in r['bias'].upper() else -r[ret_col], axis=1)
        gains = pnl[pnl > 0].sum()
        losses = abs(pnl[pnl < 0].sum())
        profit_factor = round(gains / losses, 2) if losses > 0 else 99.0
        sharpe = round((pnl.mean() / pnl.std()) * math.sqrt(252 * 4), 2) if len(pnl) > 1 and pnl.std() > 0 else 0.0
    else:
        profit_factor, sharpe = 0.0, 0.0
        
    return {
        'total_signals': len(signals_df),
        'evaluated_signals': len(res_df),
        'overall_accuracy_pct': round(overall_acc, 1),
        'bull_accuracy_pct': round(bull_acc, 1),
        'bear_accuracy_pct': round(bear_acc, 1),
        'profit_factor': profit_factor,
        'sharpe_ratio': sharpe,
        'evaluated_df': res_df
    }
