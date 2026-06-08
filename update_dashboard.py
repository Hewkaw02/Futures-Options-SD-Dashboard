"""
update_dashboard.py — Convert existing trading_results CSVs into dashboard JSON.

Reads from:
  - trading_results/{date}/{hour}/master_bias_report_*.csv
  - trading_results/{date}/{hour}/{asset}/{asset}_data_*.csv

Writes to:
  - docs/data/{date}/{hour}/GC_data.json
  - docs/data/{date}/{hour}/ES_data.json
  - docs/data/{date}/{hour}/NQ_data.json
  - docs/data/manifest.json

This script works WITHOUT API credentials — it uses only existing CSV files
and fetches OHLC candle data from yfinance.
"""

import json
import os
import re
import glob
import math
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

# Try yfinance for candle data (optional)
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

try:
    import pandas as pd
    HAS_PD = True
except ImportError:
    HAS_PD = False

# ── Config ────────────────────────────────────────────────────
SOURCE_ROOT = Path("trading_results")
INTRADAY_ROOT = Path("intraday_results")
OUTPUT_ROOT = Path("docs/data")
ASSETS = ["GC", "ES", "NQ"]

ASSET_NAMES = {
    "GC": "Gold",
    "ES": "S&P 500",
    "NQ": "NASDAQ"
}

YF_MAP = {
    "GC": "GC=F",
    "ES": "ES=F",
    "NQ": "NQ=F",
}


def find_latest_csv(directory, pattern):
    """Find the latest CSV file matching the pattern."""
    files = sorted(glob.glob(str(directory / pattern)))
    return files[-1] if files else None


def parse_bias_csv(csv_path, asset_name):
    """Parse master_bias_report CSV for a specific asset."""
    if not HAS_PD:
        return parse_bias_csv_manual(csv_path, asset_name)

    df = pd.read_csv(csv_path)
    row = df[df['Asset'] == asset_name]
    if row.empty:
        return None

    r = row.iloc[0]
    walls = str(r.get('Wall(R/S)', ''))
    wall_parts = walls.split('/')

    return {
        "label": str(r.get('Bias', '—')),
        "confidence": str(r.get('Conf%', '—')),
        "price": float(r.get('Price', 0)),
        "iv": str(r.get('IV%', '—')),
        "pcr_vol": float(r.get('PCR(V)', 0)),
        "skew": str(r.get('Skew%', '—')),
        "activity": str(r.get('Act%', '—')),
        "gex": str(r.get('GEX', '—')),
        "walls": walls,
        "wall_resistance": float(wall_parts[0]) if len(wall_parts) > 0 else 0,
        "wall_support": float(wall_parts[1]) if len(wall_parts) > 1 else 0,
    }


def parse_bias_csv_manual(csv_path, asset_name):
    """Manual CSV parsing without pandas."""
    with open(csv_path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 2:
        return None

    headers = lines[0].strip().split(',')
    for line in lines[1:]:
        vals = line.strip().split(',')
        row = dict(zip(headers, vals))
        if row.get('Asset', '') == asset_name:
            walls = row.get('Wall(R/S)', '')
            wall_parts = walls.split('/')
            return {
                "label": row.get('Bias', '—'),
                "confidence": row.get('Conf%', '—'),
                "price": float(row.get('Price', 0)),
                "iv": row.get('IV%', '—'),
                "pcr_vol": float(row.get('PCR(V)', 0)),
                "skew": row.get('Skew%', '—'),
                "activity": row.get('Act%', '—'),
                "gex": row.get('GEX', '—'),
                "walls": walls,
                "wall_resistance": float(wall_parts[0]) if len(wall_parts) > 0 else 0,
                "wall_support": float(wall_parts[1]) if len(wall_parts) > 1 else 0,
            }
    return None


def parse_option_data_csv(csv_path):
    """Parse asset option data CSV (Strike, Type, OI, Volume, optional Greeks)."""
    rows = []
    with open(csv_path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 2:
        return None

    headers = [h.strip() for h in lines[0].strip().split(',')]
    has_greeks = 'GEX' in headers and 'Vanna' in headers
    has_iv = 'IV' in headers
    
    for line in lines[1:]:
        vals = line.strip().split(',')
        if len(vals) < 4:
            continue
        row_dict = {
            'Strike': float(vals[0]),
            'Type': vals[1],
            'OI': float(vals[2]),
            'Volume': float(vals[3]),
        }
        if has_greeks and len(vals) >= 8:
            row_dict['GEX'] = float(vals[4])
            row_dict['Vanna'] = float(vals[5])
            row_dict['DEX'] = float(vals[6])
            row_dict['Charm'] = float(vals[7])
        else:
            row_dict['GEX'] = 0.0
            row_dict['Vanna'] = 0.0
            row_dict['DEX'] = 0.0
            row_dict['Charm'] = 0.0
        if has_iv:
            iv_idx = headers.index('IV')
            if len(vals) > iv_idx:
                row_dict['IV'] = float(vals[iv_idx])
            else:
                row_dict['IV'] = 0.0
        else:
            row_dict['IV'] = 0.0
        rows.append(row_dict)

    if not rows:
        return None

    # Build OI Walls data
    strikes_set = sorted(set(r['Strike'] for r in rows))
    call_oi = {}
    put_oi = {}

    for r in rows:
        s = r['Strike']
        if r['Type'] in ['Call', 'C']:
            call_oi[s] = call_oi.get(s, 0) + r['OI']
        else:
            put_oi[s] = put_oi.get(s, 0) + r['OI']

    # Filter to strikes with any OI
    active_strikes = [s for s in strikes_set if (call_oi.get(s, 0) + put_oi.get(s, 0)) > 0]
    if not active_strikes:
        active_strikes = strikes_set

    oi_walls = {
        "strikes": active_strikes,
        "call_oi": [call_oi.get(s, 0) for s in active_strikes],
        "put_oi": [put_oi.get(s, 0) for s in active_strikes],
    }

    # Net OI
    net_oi = {
        "strikes": active_strikes,
        "net": [call_oi.get(s, 0) - put_oi.get(s, 0) for s in active_strikes],
    }

    # Find top OI resistance (call) and support (put) walls
    resistances = []
    supports = []

    # Top 3 call OI strikes (resistance)
    call_sorted = sorted([(s, call_oi.get(s, 0)) for s in active_strikes], key=lambda x: -x[1])
    for s, oi in call_sorted[:3]:
        if oi > 0:
            resistances.append({"strike": s, "oi": int(oi)})

    # Top 3 put OI strikes (support)
    put_sorted = sorted([(s, put_oi.get(s, 0)) for s in active_strikes], key=lambda x: -x[1])
    for s, oi in put_sorted[:3]:
        if oi > 0:
            supports.append({"strike": s, "oi": int(oi)})

    # Parse GEX & Vanna (Exact vs Proxy)
    gex_values = []
    vanna_values = []
    
    gex_map = {}
    vanna_map = {}
    for r in rows:
        s = r['Strike']
        gex_map[s] = gex_map.get(s, 0.0) + r['GEX']
        vanna_map[s] = vanna_map.get(s, 0.0) + r['Vanna']

    atm = active_strikes[len(active_strikes) // 2]
    for s in active_strikes:
        if has_greeks:
            gex_values.append(gex_map.get(s, 0.0))
            vanna_values.append(vanna_map.get(s, 0.0))
        else:
            # Approximate GEX profile (simplified: call_oi - put_oi weighted by distance from ATM)
            dist = abs(s - atm) / atm if atm > 0 else 1
            gex = (call_oi.get(s, 0) - put_oi.get(s, 0)) * (1 - min(dist, 1))
            gex_values.append(gex)
            
            # Approximate Vanna (call_oi * strike distance from ATM / IV proxy)
            delta_proxy = (s - atm) / atm if atm > 0 else 0
            vanna_approx = (call_oi.get(s, 0) - put_oi.get(s, 0)) * delta_proxy * 100
            vanna_values.append(round(vanna_approx, 2))

    # Find gamma flip price (linear interpolation)
    flip_price = None
    for i in range(len(gex_values) - 1):
        y1, y2 = gex_values[i], gex_values[i + 1]
        if y1 * y2 < 0:
            x1, x2 = active_strikes[i], active_strikes[i + 1]
            flip_price = round(x1 - y1 * (x2 - x1) / (y2 - y1), 2)
            break
        elif y1 == 0:
            flip_price = active_strikes[i]
            break

    gex_profile = {
        "strikes": active_strikes,
        "gex": gex_values,
        "flip_price": flip_price,
    }

    vanna = {
        "strikes": active_strikes,
        "vanna_exp": vanna_values,
    }

    # IV Smile / Skew Curve
    iv_smile = None
    if any(r.get('IV', 0) > 0 for r in rows):
        call_iv_map = {}
        put_iv_map = {}
        for r in rows:
            s = r['Strike']
            iv_val = r.get('IV', 0)
            if iv_val > 0:
                if r['Type'] in ['Call', 'C']:
                    call_iv_map[s] = iv_val
                else:
                    put_iv_map[s] = iv_val
        
        iv_strikes = sorted(set(list(call_iv_map.keys()) + list(put_iv_map.keys())))
        if len(iv_strikes) >= 3:
            iv_smile = {
                "strikes": iv_strikes,
                "call_iv": [round(call_iv_map.get(s, 0) * 100, 2) for s in iv_strikes],
                "put_iv": [round(put_iv_map.get(s, 0) * 100, 2) for s in iv_strikes],
            }

    # Max Pain Calculation
    max_pain_result = None
    if active_strikes and (any(call_oi.get(s, 0) > 0 for s in active_strikes) or any(put_oi.get(s, 0) > 0 for s in active_strikes)):
        min_pain = float('inf')
        best_strike = active_strikes[len(active_strikes) // 2]
        
        for settle_price in active_strikes:
            total_pain = 0
            for s in active_strikes:
                # Call pain: if settle > strike, calls are ITM
                if settle_price > s:
                    total_pain += call_oi.get(s, 0) * (settle_price - s)
                # Put pain: if settle < strike, puts are ITM  
                if settle_price < s:
                    total_pain += put_oi.get(s, 0) * (s - settle_price)
            
            if total_pain < min_pain:
                min_pain = total_pain
                best_strike = settle_price
        
        max_pain_result = {
            "price": best_strike,
            "total_pain": round(min_pain, 0),
        }

    # Find top Volume resistance (call) and support (put) walls
    vol_resistances = []
    vol_supports = []
    
    # Top 3 call Vol strikes
    vol_c_sorted = sorted([(r['Strike'], r['Volume']) for r in rows if r['Type'] in ['Call', 'C']], key=lambda x: -x[1])
    for s, v in vol_c_sorted[:3]:
        if v > 0: vol_resistances.append([float(s), float(v)])
        
    # Top 3 put Vol strikes
    vol_p_sorted = sorted([(r['Strike'], r['Volume']) for r in rows if r['Type'] in ['Put', 'P']], key=lambda x: -x[1])
    for s, v in vol_p_sorted[:3]:
        if v > 0: vol_supports.append([float(s), float(v)])

    # Build Volume Profile
    profile = []
    all_strikes = sorted(set(r['Strike'] for r in rows))
    for s in all_strikes:
        c_v = sum(r['Volume'] for r in rows if r['Strike'] == s and r['Type'] in ['Call', 'C'])
        p_v = sum(r['Volume'] for r in rows if r['Strike'] == s and r['Type'] in ['Put', 'P'])
        if c_v > 0 or p_v > 0:
            profile.append({"strike": float(s), "call_vol": float(c_v), "put_vol": float(p_v)})

    return {
        "oi_walls": oi_walls,
        "net_oi": net_oi,
        "resistances": resistances,
        "supports": supports,
        "gex_profile": gex_profile,
        "vanna": vanna,
        "vol_resistances": vol_resistances,
        "vol_supports": vol_supports,
        "volume_profile": profile,
        "iv_smile": iv_smile,
        "max_pain": max_pain_result,
    }


# In-memory cache for yfinance downloads to prevent redundant API calls
YF_CACHE = {}


def get_multi_timeframe_candles(asset_symbol):
    """Fetch multi-timeframe candlestick data from yfinance and calculate VWAP."""
    if asset_symbol in YF_CACHE:
        return YF_CACHE[asset_symbol]

    yf_symbol = {"GC": "GC=F", "ES": "ES=F", "NQ": "NQ=F"}.get(asset_symbol)
    if not yf_symbol:
        return {}

    configs = [
        {"tf": "1d", "period": "3mo", "interval": "1d"},
        {"tf": "1h", "period": "1mo", "interval": "1h"},
        {"tf": "15m", "period": "5d", "interval": "15m"},
        {"tf": "5m", "period": "5d", "interval": "5m"}
    ]
    
    result = {}
    for conf in configs:
        try:
            df = yf.download(yf_symbol, period=conf["period"], interval=conf["interval"], progress=False)
            if df.empty:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # Ensure columns exist and are float
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col in df.columns:
                    df[col] = df[col].astype(float)
                else:
                    df[col] = 0.0

            # Construct standard OHLC array [timestamp, O, H, L, C, V] for ApexCharts
            ohlcv = []
            for i in range(len(df)):
                # Convert string to timestamp ms for JS
                ts = int(df.index[i].timestamp() * 1000)
                ohlcv.append([
                    ts,
                    round(df['Open'].iloc[i], 2),
                    round(df['High'].iloc[i], 2),
                    round(df['Low'].iloc[i], 2),
                    round(df['Close'].iloc[i], 2),
                    round(df['Volume'].iloc[i], 2)
                ])
                
            vwap_list = []
            if conf["interval"] in ["1h", "15m", "5m"] and df['Volume'].sum() > 0:
                df['Typical_Price'] = (df['High'] + df['Low'] + df['Close']) / 3
                df['Volume_TP'] = df['Volume'] * df['Typical_Price']
                df['Trade_Date'] = df.index.date
                df['VWAP'] = df.groupby('Trade_Date')['Volume_TP'].cumsum() / df.groupby('Trade_Date')['Volume'].cumsum()
                
                for i in range(len(df)):
                    ts = int(df.index[i].timestamp() * 1000)
                    vwap_val = df['VWAP'].iloc[i]
                    if pd.isna(vwap_val):
                        vwap_list.append([ts, None])
                    else:
                        vwap_list.append([ts, round(vwap_val, 2)])

            result[conf["tf"]] = {
                "ohlcv": ohlcv,
                "vwap": vwap_list if vwap_list else None
            }

        except Exception as e:
            print(f"    [WARN] Failed to fetch {conf['tf']} data for {yf_symbol}: {e}")
            
    YF_CACHE[asset_symbol] = result
    return result


def get_intraday_data(date_str, hour_str, asset):
    """Parse intraday CSV to extract Support/Resistance and Volume Profile."""
    src_dir = INTRADAY_ROOT / date_str / hour_str / asset
    if not src_dir.exists():
        return None
        
    pattern = f"{asset.lower()}_intraday_*.csv"
    matches = sorted(glob.glob(str(src_dir / pattern)))
    if not matches:
        return None
        
    latest_csv = matches[-1]
    try:
        df = pd.read_csv(latest_csv)
        if df.empty:
            return None
            
        # Parse S/R levels
        df_c_oi = df[df['Type'] == 'C'].nlargest(3, 'Open_Interest')
        df_p_oi = df[df['Type'] == 'P'].nlargest(3, 'Open_Interest')
        oi_resistances = [[float(row['Strike']), float(row['Open_Interest'])] for _, row in df_c_oi.iterrows() if row['Open_Interest'] > 0]
        oi_supports = [[float(row['Strike']), float(row['Open_Interest'])] for _, row in df_p_oi.iterrows() if row['Open_Interest'] > 0]
        
        df_c_vol = df[df['Type'] == 'C'].nlargest(3, 'Today_Volume')
        df_p_vol = df[df['Type'] == 'P'].nlargest(3, 'Today_Volume')
        vol_resistances = [[float(row['Strike']), float(row['Today_Volume'])] for _, row in df_c_vol.iterrows() if row['Today_Volume'] > 0]
        vol_supports = [[float(row['Strike']), float(row['Today_Volume'])] for _, row in df_p_vol.iterrows() if row['Today_Volume'] > 0]
        
        # Parse volume profile
        profile = []
        df_pivot = df.pivot(index='Strike', columns='Type', values='Today_Volume').fillna(0)
        # Ensure Call/Put columns exist
        if 'C' not in df_pivot: df_pivot['C'] = 0
        if 'P' not in df_pivot: df_pivot['P'] = 0
        
        for strike, row in df_pivot.iterrows():
            profile.append({
                "strike": float(strike),
                "call_vol": float(row['C']),
                "put_vol": float(row['P'])
            })
            
        return {
            "oi_resistances": oi_resistances,
            "oi_supports": oi_supports,
            "vol_resistances": vol_resistances,
            "vol_supports": vol_supports,
            "volume_profile": profile
        }
    except Exception as e:
        print(f"    [WARN] Failed to parse {latest_csv}: {e}")
        return None


def compute_sd_bands(price, iv, candle_data=None):
    """Compute SD bands using IV (Primary) or Historical Volatility (Fallback)."""
    if price <= 0:
        return None

    # Calculate SD based on IV if available
    if iv > 0:
        # Standard Daily SD formula: Price * IV * sqrt(DTE/365)
        # For a "daily" view, we use 1/365
        sd1 = price * iv * math.sqrt(1.0 / 365.0)
        daily_vol = iv * math.sqrt(1.0 / 365.0)
    elif candle_data and candle_data.get('ohlc'):
        # Fallback to historical volatility
        closes = [c['y'][3] if isinstance(c, dict) and 'y' in c else c[3] for c in candle_data['ohlc']]
        if len(closes) < 5: return None
        
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
        
        if not returns: return None
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        daily_vol = math.sqrt(variance)
        sd1 = price * daily_vol
    else:
        return None

    return {
        "price": round(price, 2),
        "sd1": round(sd1, 2),
        "daily_vol_pct": round(daily_vol * 100, 2),
        "levels": {
            "+1SD": round(price + sd1, 2),
            "+2SD": round(price + 2 * sd1, 2),
            "+3SD": round(price + 3 * sd1, 2),
            "-1SD": round(price - sd1, 2),
            "-2SD": round(price - 2 * sd1, 2),
            "-3SD": round(price - 3 * sd1, 2),
        },
    }


def get_atm_iv_from_csv(csv_path, price):
    """Compute the average IV of options at the strike closest to the underlying price."""
    if not csv_path or price <= 0:
        return 0.0
    try:
        df = pd.read_csv(csv_path) if HAS_PD else None
        if df is not None:
            if 'IV' not in df.columns:
                return 0.0
            # Find closest strike
            df['dist'] = (df['Strike'] - price).abs()
            closest_strike = df.loc[df['dist'].idxmin()]['Strike']
            closest_rows = df[df['Strike'] == closest_strike]
            valid_ivs = closest_rows[closest_rows['IV'] > 0]['IV']
            if not valid_ivs.empty:
                return float(valid_ivs.mean())
        else:
            # Manual fallback
            with open(csv_path, 'r') as f:
                lines = f.readlines()
            if len(lines) < 2: return 0.0
            headers = lines[0].strip().split(',')
            if 'Strike' not in headers or 'IV' not in headers:
                return 0.0
            strike_idx = headers.index('Strike')
            iv_idx = headers.index('IV')
            
            closest_strike = None
            min_dist = float('inf')
            strike_ivs = {} # strike -> list of IVs
            
            for line in lines[1:]:
                vals = line.strip().split(',')
                if len(vals) <= max(strike_idx, iv_idx): continue
                s = float(vals[strike_idx])
                try:
                    iv_val = float(vals[iv_idx])
                except ValueError:
                    continue
                if iv_val > 0:
                    dist = abs(s - price)
                    if dist < min_dist:
                        min_dist = dist
                        closest_strike = s
                    if s not in strike_ivs:
                        strike_ivs[s] = []
                    strike_ivs[s].append(iv_val)
            
            if closest_strike is not None and closest_strike in strike_ivs:
                vals = strike_ivs[closest_strike]
                return sum(vals) / len(vals)
    except Exception as e:
        print(f"      [WARN] Failed to get ATM IV from {csv_path}: {e}")
    return 0.0


def find_previous_csv(date_str, hour_str, asset, asset_lower):
    """Find the most recent previous CSV for the same asset."""
    src_root = Path("trading_results")
    
    # Collect all available timestamp directories
    all_timestamps = []
    for d_dir in sorted(src_root.iterdir()):
        if not d_dir.is_dir() or not re.match(r'\d{4}-\d{2}-\d{2}', d_dir.name):
            continue
        for h_dir in sorted(d_dir.iterdir()):
            if not h_dir.is_dir():
                continue
            all_timestamps.append((d_dir.name, h_dir.name))
    
    # Find current position and look backwards
    current = (date_str, hour_str)
    for i, ts in enumerate(all_timestamps):
        if ts == current and i > 0:
            prev_date, prev_hour = all_timestamps[i - 1]
            prev_dir = src_root / prev_date / prev_hour / asset
            pattern = f"{asset_lower}_data_*.csv"
            matches = sorted(glob.glob(str(prev_dir / pattern)))
            return matches[-1] if matches else None
    
    return None


def process_timestamp(date_str, hour_str):
    """Process a single timestamp directory into JSON."""
    src_dir = SOURCE_ROOT / date_str / hour_str
    if not src_dir.exists():
        return False

    out_dir = OUTPUT_ROOT / date_str / hour_str
    out_dir.mkdir(parents=True, exist_ok=True)

    # Find the latest bias CSV
    bias_csv = find_latest_csv(src_dir, "master_bias_report_*.csv")

    for asset in ASSETS:
        asset_lower = asset.lower()
        asset_name = ASSET_NAMES[asset]
        asset_dir = src_dir / asset

        data = {}

        # 1. Bias data
        if bias_csv:
            bias = parse_bias_csv(bias_csv, asset_name)
            data["bias"] = bias or {}
        else:
            data["bias"] = {}

        # 2. Option data (OI, Net OI, GEX, Vanna)
        opt_csv = find_latest_csv(asset_dir, f"{asset_lower}_data_*.csv")
        opt_data = None
        if opt_csv:
            opt_data = parse_option_data_csv(opt_csv)
            if opt_data:
                data["oi_walls"] = opt_data["oi_walls"]
                data["net_oi"] = opt_data["net_oi"]
                data["resistances"] = opt_data["resistances"]
                data["supports"] = opt_data["supports"]
                data["gex_profile"] = opt_data["gex_profile"]
                data["vanna"] = opt_data["vanna"]
                data["iv_smile"] = opt_data.get("iv_smile")
                data["max_pain"] = opt_data.get("max_pain")
            else:
                data["oi_walls"] = None
                data["net_oi"] = None
                data["resistances"] = []
                data["supports"] = []
                data["gex_profile"] = None
                data["vanna"] = None
                data["iv_smile"] = None
                data["max_pain"] = None
        else:
            data["oi_walls"] = None
            data["net_oi"] = None
            data["resistances"] = []
            data["supports"] = []
            data["gex_profile"] = None
            data["vanna"] = None
            data["iv_smile"] = None
            data["max_pain"] = None

        # 2b. ΔOI — Compare current OI with previous snapshot
        data["oi_change"] = None
        if opt_csv and opt_data:
            # Find previous hour's CSV for the same asset
            prev_csv = find_previous_csv(date_str, hour_str, asset, asset_lower)
            if prev_csv:
                prev_data = parse_option_data_csv(prev_csv)
                if prev_data and prev_data["oi_walls"]:
                    prev_call_oi = dict(zip(prev_data["oi_walls"]["strikes"], prev_data["oi_walls"]["call_oi"]))
                    prev_put_oi = dict(zip(prev_data["oi_walls"]["strikes"], prev_data["oi_walls"]["put_oi"]))
                    
                    curr_strikes = opt_data["oi_walls"]["strikes"]
                    curr_call = dict(zip(curr_strikes, opt_data["oi_walls"]["call_oi"]))
                    curr_put = dict(zip(curr_strikes, opt_data["oi_walls"]["put_oi"]))
                    
                    all_strikes = sorted(set(list(curr_call.keys()) + list(prev_call_oi.keys())))
                    call_change = [curr_call.get(s, 0) - prev_call_oi.get(s, 0) for s in all_strikes]
                    put_change = [curr_put.get(s, 0) - prev_put_oi.get(s, 0) for s in all_strikes]
                    
                    # Only export if there are actual changes
                    if any(c != 0 for c in call_change) or any(c != 0 for c in put_change):
                        data["oi_change"] = {
                            "strikes": all_strikes,
                            "call_change": call_change,
                            "put_change": put_change,
                        }

        # 3. Candlestick & VWAP Data from yfinance
        multi_candles = get_multi_timeframe_candles(asset)
        data["candlesticks"] = multi_candles

        # Backwards compatibility for SD chart
        if "1d" in multi_candles:
            # Convert [timestamp, O, H, L, C, V] back to old {"x": date, "y": [O,H,L,C]} for the old renderer
            old_ohlc = []
            for row in multi_candles["1d"]["ohlcv"]:
                old_ohlc.append({
                    "x": datetime.fromtimestamp(row[0]/1000).strftime('%Y-%m-%d'),
                    "y": [row[1], row[2], row[3], row[4]]
                })
            data["candlestick"] = {"dates": [d["x"] for d in old_ohlc], "ohlc": old_ohlc}
        else:
            data["candlestick"] = {"dates": [], "ohlc": []}

        # 4. SD bands (Primary: IV-based)
        price = data.get("bias", {}).get("price", 0)
        if price <= 0 and "candlesticks" in data and "1d" in data["candlesticks"]:
            ohlcv = data["candlesticks"]["1d"]["ohlcv"]
            if ohlcv:
                price = ohlcv[-1][4]  # Daily close price of underlying
                if "price" not in data["bias"] or data["bias"]["price"] <= 0:
                    data["bias"]["price"] = price

        iv_str = data.get("bias", {}).get("iv", "0%")
        iv = float(iv_str.replace('%', '')) / 100 if iv_str and '%' in iv_str else 0
        if iv <= 0 and opt_csv and price > 0:
            iv = get_atm_iv_from_csv(opt_csv, price)
            if "iv" not in data["bias"] or data["bias"]["iv"] in ["0%", "—", ""]:
                data["bias"]["iv"] = f"{round(iv * 100, 2)}%"
        
        data["sd_bands"] = compute_sd_bands(price, iv, data.get("candlestick"))
            
        # Add 1 SD step calculation for intraday master
        data["sd_step"] = price * iv * math.sqrt(1.0 / 365) if iv else 0

        # 5. Intraday Levels (OI & Vol) and Volume Profile
        intraday_data = get_intraday_data(date_str, hour_str, asset)
        if intraday_data:
            data["intraday_levels"] = {
                "oi_resistances": intraday_data["oi_resistances"],
                "oi_supports": intraday_data["oi_supports"],
                "vol_resistances": intraday_data["vol_resistances"],
                "vol_supports": intraday_data["vol_supports"]
            }
            data["intraday_volume_profile"] = intraday_data["volume_profile"]
        elif opt_data:
            # Fallback to option data if intraday file is missing
            data["intraday_levels"] = {
                "oi_resistances": [[r["strike"], r["oi"]] for r in opt_data["resistances"]],
                "oi_supports": [[r["strike"], r["oi"]] for r in opt_data["supports"]],
                "vol_resistances": opt_data["vol_resistances"],
                "vol_supports": opt_data["vol_supports"]
            }
            data["intraday_volume_profile"] = opt_data["volume_profile"]
        else:
            data["intraday_levels"] = None
            data["intraday_volume_profile"] = None

        # Write JSON
        out_file = out_dir / f"{asset}_data.json"
        with open(out_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"  [OK] {out_file}")

    return True


def cleanup_old_data(days=90):
    """Delete date directories older than the specified number of days."""
    cutoff_date = datetime.now() - timedelta(days=days)
    directories_to_clean = [SOURCE_ROOT, INTRADAY_ROOT, OUTPUT_ROOT]
    
    print(f"\n[CLEANUP] Checking for data older than {days} days (before {cutoff_date.strftime('%Y-%m-%d')})...")
    
    deleted_count = 0
    for root_dir in directories_to_clean:
        if not root_dir.exists():
            continue
            
        for date_dir in list(root_dir.iterdir()):
            if not date_dir.is_dir():
                continue
                
            date_name = date_dir.name
            if not re.match(r'\d{4}-\d{2}-\d{2}', date_name):
                continue
                
            try:
                folder_date = datetime.strptime(date_name, '%Y-%m-%d')
                if folder_date < cutoff_date:
                    print(f"  Deleting old data: {date_dir}")
                    shutil.rmtree(date_dir)
                    deleted_count += 1
            except Exception as e:
                print(f"  [WARN] Failed to delete {date_dir}: {e}")
                
    if deleted_count > 0:
        print(f"[OK] Deleted {deleted_count} old directory(ies).")
    else:
        print("[OK] No old data found to delete.")


def update_manifest():
    """Scan docs/data/ for all timestamps and update manifest.json."""
    timestamps = []

    if not OUTPUT_ROOT.exists():
        return

    for date_dir in sorted(OUTPUT_ROOT.iterdir()):
        if not date_dir.is_dir():
            continue
        date_name = date_dir.name
        # Validate date format
        if not re.match(r'\d{4}-\d{2}-\d{2}', date_name):
            continue
        for hour_dir in sorted(date_dir.iterdir()):
            if not hour_dir.is_dir():
                continue
            hour_name = hour_dir.name
            # Check for at least one JSON file
            jsons = list(hour_dir.glob("*_data.json"))
            if jsons:
                timestamps.append(f"{date_name}/{hour_name}")

    manifest = {
        "timestamps": timestamps,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "assets": ASSETS,
    }

    manifest_file = OUTPUT_ROOT / "manifest.json"
    with open(manifest_file, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"\n[OK] Manifest updated: {len(timestamps)} timestamps")
    print(f"     -> {manifest_file}")


def main():
    print("=" * 60)
    print("  UPDATE DASHBOARD -- CSV -> Dashboard JSON")
    print("=" * 60)

    if not SOURCE_ROOT.exists():
        print(f"[ERROR] Source directory not found: {SOURCE_ROOT}")
        return

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Discover all date/hour directories
    processed = 0
    for date_dir in sorted(SOURCE_ROOT.iterdir()):
        if not date_dir.is_dir():
            continue
        date_name = date_dir.name
        if not re.match(r'\d{4}-\d{2}-\d{2}', date_name):
            continue

        for hour_dir in sorted(date_dir.iterdir()):
            if not hour_dir.is_dir():
                continue
            hour_name = hour_dir.name

            print(f"\nProcessing {date_name}/{hour_name}...")
            if process_timestamp(date_name, hour_name):
                processed += 1

    if processed == 0:
        print("\n[WARN] No timestamp directories found to process.")
    else:
        print(f"\n[OK] Processed {processed} timestamp(s)")

    # Run cleanup for 90 days (approx. 3 months)
    cleanup_old_data(days=90)

    # Update manifest
    update_manifest()
    print("\nDone!")


if __name__ == "__main__":
    main()
