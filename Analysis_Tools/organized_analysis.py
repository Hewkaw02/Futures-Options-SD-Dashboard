import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import os
from datetime import date, datetime
from pathlib import Path
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Summary
import yfinance as yf

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

def get_yf_price(symbol_root):
    mapping = {'/GC': 'GC=F', '/ES': 'ES=F', '/NQ': 'NQ=F'}
    yf_sym = mapping.get(symbol_root)
    if not yf_sym: return None
    try:
        data = yf.Ticker(yf_sym).history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception:
        pass
    return None

async def process_asset(session, asset, output_base):
    symbol = asset['symbol']
    clean_name = symbol.replace('/', '')
    now = datetime.now()
    date_str, hour_str, timestamp = now.strftime("%Y-%m-%d"), now.strftime("%H00"), now.strftime("%H%M")
    
    asset_dir = output_base / date_str / hour_str / clean_name
    asset_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Processing {symbol} and saving to {asset_dir}...")
    
    chain = await get_future_option_chain(session, symbol)
    expiry = sorted([d for d in chain.keys() if d >= date.today()])[0]
    options = chain[expiry]
    
    # Use yfinance for price
    price = get_yf_price(symbol)
    if not price:
        strikes = sorted([float(o.strike_price) for o in options])
        price = strikes[len(strikes) // 2]

    # Adjust range based on yf price
    min_s, max_s = price * 0.95, price * 1.05
    strikes_of_interest = [o for o in options if min_s <= float(o.strike_price) <= max_s]
    streamer_symbols = [o.streamer_symbol for o in strikes_of_interest]

    data_list = []
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Summary, streamer_symbols)
        results = {}
        end_time = asyncio.get_event_loop().time() + 5
        while asyncio.get_event_loop().time() < end_time:
            try:
                s = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.4)
                results[s.event_symbol] = s
            except (asyncio.TimeoutError, Exception):
                continue

        for opt in strikes_of_interest:
            s = results.get(opt.streamer_symbol)
            if s:
                data_list.append({
                    'Strike': float(opt.strike_price),
                    'Type': 'Call' if opt.option_type.value == 'C' else 'Put',
                    'OI': float(s.open_interest or 0),
                    'Volume': float(s.prev_day_volume or 0)
                })

    df = pd.DataFrame(data_list)
    if df.empty: return

    df_pivot = df.pivot(index='Strike', columns='Type', values='OI').fillna(0)
    if 'Call' not in df_pivot: df_pivot['Call'] = 0
    if 'Put' not in df_pivot: df_pivot['Put'] = 0
    df_pivot['Net OI'] = df_pivot['Call'] - df_pivot['Put']
    
    asset_dir.mkdir(parents=True, exist_ok=True)
    
    plt.figure(figsize=(12, 6))
    colors = ['green' if x >= 0 else 'red' for x in df_pivot['Net OI']]
    df_pivot['Net OI'].plot(kind='bar', color=colors, alpha=0.7)
    plt.title(f"{asset['title']} Net OI | Price: {price:,.2f} | {timestamp}")
    plt.axhline(0, color='black', linewidth=0.8)
    plt.tight_layout()
    plt.savefig(asset_dir / f"{clean_name.lower()}_net_oi_{timestamp}.png")
    plt.close()

    plt.figure(figsize=(12, 6))
    plt.bar(df_pivot.index - 2, df_pivot['Call'], width=4, label='Call OI', color='green', alpha=0.6)
    plt.bar(df_pivot.index + 2, df_pivot['Put'], width=4, label='Put OI', color='red', alpha=0.6)
    plt.title(f"{asset['title']} OI Walls | Price: {price:,.2f} | {timestamp}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(asset_dir / f"{clean_name.lower()}_oi_walls_{timestamp}.png")
    plt.close()

    df.to_csv(asset_dir / f"{clean_name.lower()}_data_{timestamp}.csv", index=False)
    print(f"[OK] Saved results for {symbol} at {timestamp}")

async def main():
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    output_base = Path("trading_results")
    output_base.mkdir(exist_ok=True)
    assets = [
        {'symbol': '/GC', 'title': 'Gold (/GC)'},
        {'symbol': '/ES', 'title': 'S&P 500 (/ES)'},
        {'symbol': '/NQ', 'title': 'NASDAQ (/NQ)'}
    ]
    for asset in assets:
        await process_asset(session, asset, output_base)

if __name__ == "__main__":
    asyncio.run(main())
