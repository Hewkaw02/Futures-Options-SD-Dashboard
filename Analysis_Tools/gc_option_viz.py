import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
from datetime import date
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Summary

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

async def main():
    print("Fetching and Visualizing Option Data...")
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    
    symbol = "/GC"
    chain = await get_future_option_chain(session, symbol)
    expiry = sorted([d for d in chain.keys() if d >= date.today()])[0]
    options = chain[expiry]
    
    # Auto-range: use yfinance to get current price, then +/-4% for strike range
    try:
        data = yf.Ticker('GC=F').history(period='1d')
        current_price = float(data['Close'].iloc[-1]) if not data.empty else None
    except Exception:
        current_price = None
    
    if current_price:
        range_pct = 0.04
        strike_min = current_price * (1 - range_pct)
        strike_max = current_price * (1 + range_pct)
        print(f"  Auto-range: {strike_min:.0f} - {strike_max:.0f} (based on price {current_price:.2f})")
    else:
        all_strikes = sorted([float(o.strike_price) for o in options])
        mid = all_strikes[len(all_strikes) // 2]
        strike_min, strike_max = mid * 0.96, mid * 1.04
        print(f"  Fallback range: {strike_min:.0f} - {strike_max:.0f}")
    
    strikes_of_interest = [o for o in options if strike_min <= float(o.strike_price) <= strike_max]
    streamer_symbols = [o.streamer_symbol for o in strikes_of_interest]

    data_list = []
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Summary, streamer_symbols)
        results = {}
        end_time = asyncio.get_event_loop().time() + 5
        while asyncio.get_event_loop().time() < end_time:
            try:
                summary = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.5)
                results[summary.event_symbol] = summary
            except (asyncio.TimeoutError, Exception):
                continue

        for opt in strikes_of_interest:
            s = results.get(opt.streamer_symbol)
            if s:
                data_list.append({
                    'Strike': float(opt.strike_price),
                    'Type': opt.option_type.value,
                    'Volume': float(s.prev_day_volume or 0),
                    'OI': float(s.open_interest or 0)
                })

    # Create DataFrame
    df = pd.DataFrame(data_list)
    if df.empty:
        print("No data collected.")
        return

    # Pivot for plotting
    df_vol = df.pivot(index='Strike', columns='Type', values='Volume').fillna(0)
    df_oi = df.pivot(index='Strike', columns='Type', values='OI').fillna(0)

    # Plotting
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

    # Volume Chart
    df_vol.plot(kind='bar', ax=ax1, color={'C': 'green', 'P': 'red'}, alpha=0.7)
    ax1.set_title(f'Option Volume by Strike - {symbol} ({expiry})')
    ax1.set_ylabel('Volume')
    ax1.grid(axis='y', linestyle='--', alpha=0.5)

    # Open Interest Chart
    df_oi.plot(kind='bar', ax=ax2, color={'C': 'darkgreen', 'P': 'darkred'}, alpha=0.7)
    ax2.set_title(f'Open Interest by Strike - {symbol} ({expiry})')
    ax2.set_ylabel('Open Interest')
    ax2.set_xlabel('Strike Price')
    ax2.grid(axis='y', linestyle='--', alpha=0.5)

    plt.tight_layout()
    plot_file = 'gc_option_chart.png'
    plt.savefig(plot_file)
    print(f"\n[OK] Chart saved as: {plot_file}")
    
    # Display some summary stats via Pandas
    print("\n--- Pandas Summary Stats ---")
    print(df.groupby('Type')[['Volume', 'OI']].sum())

if __name__ == "__main__":
    asyncio.run(main())
