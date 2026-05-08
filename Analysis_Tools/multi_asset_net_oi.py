import asyncio
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Summary
import yfinance as yf

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

async def get_net_oi(session, symbol, strike_min, strike_max):
    print(f"Processing {symbol}...")
    chain = await get_future_option_chain(session, symbol)
    expiry = sorted([d for d in chain.keys() if d >= date.today()])[0]
    options = chain[expiry]
    
    strikes_of_interest = [o for o in options if strike_min <= float(o.strike_price) <= strike_max]
    streamer_symbols = [o.streamer_symbol for o in strikes_of_interest]

    data_list = []
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Summary, streamer_symbols)
        results = {}
        end_time = asyncio.get_event_loop().time() + 4
        while asyncio.get_event_loop().time() < end_time:
            try:
                summary = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.4)
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
        return None, expiry
        
    df_pivot = df.pivot(index='Strike', columns='Type', values='OI').fillna(0)
    # Ensure both columns exist
    if 'Call' not in df_pivot: df_pivot['Call'] = 0
    if 'Put' not in df_pivot: df_pivot['Put'] = 0
    
    df_pivot['Net OI'] = df_pivot['Call'] - df_pivot['Put']
    return df_pivot, expiry

async def main():
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    
    # Dynamic auto-range via yfinance
    YF_MAP = {'/GC': 'GC=F', '/ES': 'ES=F', '/NQ': 'NQ=F'}
    assets = []
    for sym, title in [('/GC', 'Gold (/GC)'), ('/ES', 'S&P 500 (/ES)'), ('/NQ', 'NASDAQ (/NQ)')]:
        yf_sym = YF_MAP[sym]
        try:
            data = yf.Ticker(yf_sym).history(period='1d')
            price = float(data['Close'].iloc[-1]) if not data.empty else None
        except Exception:
            price = None
        if price:
            pct = 0.05
            assets.append({'symbol': sym, 'min': price * (1 - pct), 'max': price * (1 + pct), 'title': title})
            print(f"  {sym} auto-range: {price*(1-pct):.0f} - {price*(1+pct):.0f} (price={price:.2f})")
        else:
            # Fallback: wide range for safety
            fallback = {'/GC': (3000, 6000), '/ES': (4000, 8000), '/NQ': (15000, 35000)}
            lo, hi = fallback[sym]
            assets.append({'symbol': sym, 'min': lo, 'max': hi, 'title': title})
            print(f"  {sym} fallback range: {lo} - {hi}")
    
    fig, axes = plt.subplots(3, 1, figsize=(15, 18))
    
    for i, asset in enumerate(assets):
        df, expiry = await get_net_oi(session, asset['symbol'], asset['min'], asset['max'])
        if df is not None:
            # Color: Green for Positive Net OI (Calls win), Red for Negative (Puts win)
            colors = ['green' if x >= 0 else 'red' for x in df['Net OI']]
            df['Net OI'].plot(kind='bar', ax=axes[i], color=colors, alpha=0.7)
            axes[i].set_title(f"{asset['title']} Net OI (Call - Put) | Expiry: {expiry}", fontsize=14)
            axes[i].set_ylabel('Net Open Interest')
            axes[i].axhline(0, color='black', linewidth=0.8)
            axes[i].grid(axis='y', linestyle='--', alpha=0.3)
            
            # Label the biggest spikes
            max_net = df['Net OI'].abs().max()
            for strike, val in df['Net OI'].items():
                if abs(val) > max_net * 0.6:
                    label = 'Bullish' if val > 0 else 'Bearish'
                    axes[i].text(df.index.get_loc(strike), val, f'{int(val)}', ha='center', va='bottom' if val > 0 else 'top', fontsize=9)
        else:
            axes[i].set_title(f"No Data for {asset['symbol']}")

    plt.tight_layout()
    output_file = 'multi_asset_net_oi.png'
    plt.savefig(output_file)
    print(f"\n[OK] Multi-asset Net OI chart saved as: {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
