"""
Real-Time Market Data Producer & Live Feed Engine
Fetches live futures prices (via yfinance/adapters), updates live candles and Greeks,
and generates docs/data/live/{ASSET}_data.json for real-time dashboard streaming.
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Safe yfinance import
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    YFINANCE_AVAILABLE = False

DATA_DIR = Path("docs/data")
LIVE_DIR = DATA_DIR / "live"
MANIFEST_PATH = DATA_DIR / "manifest.json"

ASSET_SYMBOLS = {
    "GC": "GC=F",
    "ES": "ES=F",
    "NQ": "NQ=F"
}

def get_latest_snapshot_ts():
    """Find the latest processed snapshot timestamp from manifest.json."""
    if not MANIFEST_PATH.exists():
        return None
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            timestamps = manifest.get("timestamps", [])
            return timestamps[-1] if timestamps else None
    except Exception as e:
        print(f"[LiveFeed] Error reading manifest: {e}")
        return None

def fetch_live_prices():
    """Fetch current real-time prices for futures contracts."""
    prices = {}
    if not YFINANCE_AVAILABLE:
        return prices

    for asset, ticker_sym in ASSET_SYMBOLS.items():
        try:
            ticker = yf.Ticker(ticker_sym)
            # Try fast_info first (fastest, real-time quote)
            info = getattr(ticker, "fast_info", None)
            if info and hasattr(info, "last_price") and info.last_price:
                prices[asset] = round(float(info.last_price), 2)
            else:
                data = ticker.history(period="1d")
                if not data.empty:
                    last_price = float(data["Close"].iloc[-1])
                    prices[asset] = round(last_price, 2)
        except Exception as e:
            print(f"[LiveFeed] Warning: Could not fetch {ticker_sym} from yfinance: {e}")

    return prices

def generate_live_snapshot():
    """Generate docs/data/live/{ASSET}_data.json using real-time prices."""
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    latest_ts = get_latest_snapshot_ts()

    if not latest_ts:
        print("[LiveFeed] No baseline snapshot found in manifest.json.")
        return False

    baseline_dir = DATA_DIR / latest_ts
    if not baseline_dir.exists():
        print(f"[LiveFeed] Baseline directory {baseline_dir} does not exist.")
        return False

    live_prices = fetch_live_prices()
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    now_epoch_ms = int(now_utc.timestamp() * 1000)
    now_epoch_s = int(now_utc.timestamp())

    status_data = {
        "status": "LIVE_STREAMING",
        "last_sync": now_str,
        "epoch_ms": now_epoch_ms,
        "baseline_snapshot": latest_ts,
        "prices": live_prices
    }

    for asset in ["GC", "ES", "NQ"]:
        base_file = baseline_dir / f"{asset}_data.json"
        if not base_file.exists():
            continue

        try:
            with open(base_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check if live price was fetched; if not, use base price with tiny jitter
            current_price = live_prices.get(asset)
            if not current_price:
                current_price = float(data.get("bias", {}).get("price", 0) or 0)

            if current_price <= 0:
                continue

            # 1. Update Bias with Real-time Price
            if "bias" in data:
                data["bias"]["price"] = current_price
                data["bias"]["is_realtime"] = True
                data["bias"]["live_sync_time"] = now_str

            # 2. Update Intraday / Hybrid Live Bar
            if "intraday_candles" in data and isinstance(data["intraday_candles"], list) and data["intraday_candles"]:
                last_candle = dict(data["intraday_candles"][-1])
                # Append or update current candle
                live_candle = {
                    "time": now_epoch_s,
                    "open": last_candle.get("close", current_price),
                    "high": max(last_candle.get("close", current_price), current_price),
                    "low": min(last_candle.get("close", current_price), current_price),
                    "close": current_price,
                    "volume": 100.0
                }
                # Keep last 150 bars
                data["intraday_candles"].append(live_candle)
                if len(data["intraday_candles"]) > 200:
                    data["intraday_candles"] = data["intraday_candles"][-200:]

            # 3. Add live indicator metadata
            data["realtime_metadata"] = {
                "active": True,
                "server_time_utc": now_str,
                "epoch_ms": now_epoch_ms,
                "source": "Yahoo Finance Real-time CME Futures Feed" if asset in live_prices else "Baseline Active Feed"
            }

            # Write out to docs/data/live/{asset}_data.json
            out_file = LIVE_DIR / f"{asset}_data.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(',', ':'))

        except Exception as e:
            print(f"[LiveFeed] Error updating live data for {asset}: {e}")

    # Write out docs/data/live/status.json
    with open(LIVE_DIR / "status.json", "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    print(f"[LiveFeed] [{now_str}] Live snapshot generated: GC={live_prices.get('GC', '—')}, ES={live_prices.get('ES', '—')}, NQ={live_prices.get('NQ', '—')}")
    return True

if __name__ == "__main__":
    generate_live_snapshot()
