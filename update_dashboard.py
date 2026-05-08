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
    """Parse asset option data CSV (Strike, Type, OI, Volume)."""
    rows = []
    with open(csv_path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 2:
        return None

    headers = lines[0].strip().split(',')
    for line in lines[1:]:
        vals = line.strip().split(',')
        if len(vals) < 4:
            continue
        rows.append({
            'Strike': float(vals[0]),
            'Type': vals[1],
            'OI': float(vals[2]),
            'Volume': float(vals[3]),
        })

    if not rows:
        return None

    # Build OI Walls data
    strikes_set = sorted(set(r['Strike'] for r in rows))
    call_oi = {}
    put_oi = {}

    for r in rows:
        s = r['Strike']
        if r['Type'] == 'Call':
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

    # Approximate GEX profile (simplified: call_oi - put_oi weighted by distance from ATM)
    # Find approximate ATM
    atm = active_strikes[len(active_strikes) // 2]
    gex_values = []
    for s in active_strikes:
        dist = abs(s - atm) / atm if atm > 0 else 1
        gex = (call_oi.get(s, 0) - put_oi.get(s, 0)) * (1 - min(dist, 1))
        gex_values.append(gex)

    # Find gamma flip (where GEX crosses zero)
    flip_price = None
    for i in range(len(gex_values) - 1):
        if gex_values[i] * gex_values[i + 1] < 0:
            flip_price = active_strikes[i]
            break

    gex_profile = {
        "strikes": active_strikes,
        "gex": gex_values,
        "flip_price": flip_price,
    }

    # Approximate Vanna (call_oi * strike distance from ATM / IV proxy)
    vanna_values = []
    for s in active_strikes:
        delta_proxy = (s - atm) / atm if atm > 0 else 0
        vanna_approx = (call_oi.get(s, 0) - put_oi.get(s, 0)) * delta_proxy * 100
        vanna_values.append(round(vanna_approx, 2))

    vanna = {
        "strikes": active_strikes,
        "vanna_exp": vanna_values,
    }

    return oi_walls, net_oi, resistances, supports, gex_profile, vanna


def get_multi_timeframe_candles(asset_symbol):
    """Fetch multi-timeframe candlestick data from yfinance and calculate VWAP."""
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
            "-1SD": round(price - sd1, 2),
            "-2SD": round(price - 2 * sd1, 2),
        },
    }


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
        if opt_csv:
            result = parse_option_data_csv(opt_csv)
            if result:
                oi_walls, net_oi, resistances, supports, gex_profile, vanna = result
                data["oi_walls"] = oi_walls
                data["net_oi"] = net_oi
                data["resistances"] = resistances
                data["supports"] = supports
                data["gex_profile"] = gex_profile
                data["vanna"] = vanna
            else:
                data["oi_walls"] = None
                data["net_oi"] = None
                data["resistances"] = []
                data["supports"] = []
                data["gex_profile"] = None
                data["vanna"] = None
        else:
            data["oi_walls"] = None
            data["net_oi"] = None
            data["resistances"] = []
            data["supports"] = []
            data["gex_profile"] = None
            data["vanna"] = None

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
        iv_str = data.get("bias", {}).get("iv", "0%")
        iv = float(iv_str.replace('%', '')) / 100 if iv_str and '%' in iv_str else 0
        
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
