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
    print("Generating Focused Open Interest Chart...")
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    
    symbol = "/GC"
    chain = await get_future_option_chain(session, symbol)
    expiry = sorted([d for d in chain.keys() if d >= date.today()])[0]
    options = chain[expiry]
    
    # Auto-range: use yfinance to get current price, then +/-5% for strike range
    try:
        data = yf.Ticker('GC=F').history(period='1d')
        current_price = float(data['Close'].iloc[-1]) if not data.empty else None
    except Exception:
        current_price = None
    
    if current_price:
        range_pct = 0.05
        strike_min = current_price * (1 - range_pct)
        strike_max = current_price * (1 + range_pct)
        print(f"  Auto-range: {strike_min:.0f} - {strike_max:.0f} (based on price {current_price:.2f})")
    else:
        # Fallback: use median strike from chain
        all_strikes = sorted([float(o.strike_price) for o in options])
        mid = all_strikes[len(all_strikes) // 2]
        strike_min, strike_max = mid * 0.95, mid * 1.05
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
                    'Type': 'Call' if opt.option_type.value == 'C' else 'Put',
                    'OI': float(s.open_interest or 0)
                })

    df = pd.DataFrame(data_list)
    if df.empty:
        print("No data collected.")
        return

    # Pivot for plotting
    df_plot = df.pivot(index='Strike', columns='Type', values='OI').fillna(0)

    # Plotting focused OI chart
    plt.figure(figsize=(14, 7))
    
    # Side-by-side bar chart
    width = 3.0  # Width of bars
    plt.bar(df_plot.index - width/2, df_plot['Call'], width=width, label='Call OI', color='green', alpha=0.8)
    plt.bar(df_plot.index + width/2, df_plot['Put'], width=width, label='Put OI', color='red', alpha=0.8)

    plt.title(f'Gold (/GC) Open Interest Walls - Expiry: {expiry}', fontsize=14)
    plt.xlabel('Strike Price', fontsize=12)
    plt.ylabel('Open Interest (Contracts)', fontsize=12)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.3)
    
    # Add labels to the highest walls
    max_oi = df_plot.max().max()
    for strike, row in df_plot.iterrows():
        if row['Call'] > max_oi * 0.7:
            plt.text(strike, row['Call'], f'Call Wall\n{int(row["Call"])}', ha='center', va='bottom', fontsize=8, color='darkgreen')
        if row['Put'] > max_oi * 0.7:
            plt.text(strike, row['Put'], f'Put Wall\n{int(row["Put"])}', ha='center', va='bottom', fontsize=8, color='darkred')

    plt.tight_layout()
    output_file = 'gc_oi_walls.png'
    plt.savefig(output_file)
    print(f"\n[OK] Focused OI chart saved as: {output_file}")
    
    # Find the biggest walls via Pandas
    print("\n--- Top 3 Open Interest Walls ---")
    top_calls = df[df['Type'] == 'Call'].nlargest(3, 'OI')
    top_puts = df[df['Type'] == 'Put'].nlargest(3, 'OI')
    
    print("\n[Call Walls - Resistance]")
    for _, row in top_calls.iterrows():
        print(f"  Strike {row['Strike']}: {int(row['OI'])} contracts")
        
    print("\n[Put Walls - Support]")
    for _, row in top_puts.iterrows():
        print(f"  Strike {row['Strike']}: {int(row['OI'])} contracts")

if __name__ == "__main__":
    asyncio.run(main())
