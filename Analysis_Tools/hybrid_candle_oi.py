import asyncio
import pandas as pd
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt
from datetime import date, datetime
from pathlib import Path
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Summary

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

# Mapping Tastytrade Symbols to Yahoo Finance Symbols
YF_MAPPING = {
    '/GC': 'GC=F',
    '/ES': 'ES=F',
    '/NQ': 'NQ=F'
}

async def get_oi_walls(session, asset):
    symbol = asset['symbol']
    print(f"Fetching Option OI for {symbol}...")
    
    # 1. Fetch Option Chain
    chain = await get_future_option_chain(session, symbol)
    expiry = sorted([d for d in chain.keys() if d >= date.today()])[0]
    options = chain[expiry]
    
    strikes_of_interest = [o for o in options if asset['min'] <= float(o.strike_price) <= asset['max']]
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
    if df.empty: return [], [], expiry

    df_pivot = df.pivot(index='Strike', columns='Type', values='OI').fillna(0)
    if 'Call' not in df_pivot: df_pivot['Call'] = 0
    if 'Put' not in df_pivot: df_pivot['Put'] = 0
    
    # Find Top 3 Resistance (Call) and Support (Put)
    top_calls = df_pivot.nlargest(3, 'Call')
    top_puts = df_pivot.nlargest(3, 'Put')
    
    resistances = [(strike, row['Call']) for strike, row in top_calls.iterrows() if row['Call'] > 0]
    supports = [(strike, row['Put']) for strike, row in top_puts.iterrows() if row['Put'] > 0]
    
    return resistances, supports, expiry

async def generate_hybrid_chart(session, asset, output_base):
    tt_symbol = asset['symbol']
    yf_symbol = YF_MAPPING.get(tt_symbol)
    if not yf_symbol: return
    
    clean_name = tt_symbol.replace('/', '')
    
    # Create Date/Hour folder structure
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    hour_str = now.strftime('%H00')
    timestamp = now.strftime('%H%M')
    asset_dir = output_base / date_str / hour_str / clean_name
    asset_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Get Support/Resistance from Tastytrade OI
    resistances, supports, expiry = await get_oi_walls(session, asset)
    
    # Define timeframes to generate
    timeframes = [
        {"name": "15m", "interval": "15m", "period": "5d"},
        {"name": "1H", "interval": "1h", "period": "1mo"}, # Using 1H instead of 4H due to YF limitations
        {"name": "1D", "interval": "1d", "period": "3mo"}
    ]
    
    for tf in timeframes:
        tf_name = tf["name"]
        interval = tf["interval"]
        period = tf["period"]
        
        print(f"Fetching {tf_name} Candlestick data for {yf_symbol}...")
        df_candles = yf.download(yf_symbol, period=period, interval=interval)
        
        if df_candles.empty:
            print(f"  [WARN] Failed to fetch Yahoo Finance data for {yf_symbol} ({tf_name})")
            continue
            
        # Fix yfinance MultiIndex columns if present
        if isinstance(df_candles.columns, pd.MultiIndex):
            df_candles.columns = df_candles.columns.get_level_values(0)
        
        # Ensure columns are float
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col in df_candles.columns:
                df_candles[col] = df_candles[col].astype(float)

        # Calculate VWAP (Volume Weighted Average Price) if Volume exists
        addplots = []
        if 'Volume' in df_candles.columns and df_candles['Volume'].sum() > 0:
            df_candles['Typical_Price'] = (df_candles['High'] + df_candles['Low'] + df_candles['Close']) / 3
            df_candles['Volume_TP'] = df_candles['Volume'] * df_candles['Typical_Price']
            df_candles['Trade_Date'] = df_candles.index.date
            df_candles['VWAP'] = df_candles.groupby('Trade_Date')['Volume_TP'].cumsum() / df_candles.groupby('Trade_Date')['Volume'].cumsum()
            # Only add VWAP for intraday charts (15m, 1h)
            if interval in ['15m', '1h']:
                addplots.append(mpf.make_addplot(df_candles['VWAP'], color='fuchsia', width=1.5))

        # Prepare Horizontal Lines
        lines = []
        colors = []
        for strike, oi in resistances:
            lines.append(strike)
            colors.append('red')
        for strike, oi in supports:
            lines.append(strike)
            colors.append('green')

        # 3. Plot the chart using mplfinance
        print(f"Generating {tf_name} Hybrid Chart for {tt_symbol}...")
        title = f"{asset['title']} - {tf_name} Candle & OI S/R Zones\nExpiry: {expiry} | {timestamp}"
        
        # Custom styling
        mc = mpf.make_marketcolors(up='green', down='red', edge='black', wick='black')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', gridcolor='gray', gridaxis='both')
        
        kwargs = dict(
            type='candle',
            volume=False,
            title=title,
            style=s,
            figsize=(14, 6),
            tight_layout=True,
            ylabel='Price',
            returnfig=True
        )
        if addplots:
            kwargs['addplot'] = addplots
        
        fig, axlist = mpf.plot(df_candles, **kwargs)
        
        # Add rectangular zones (axhspan)
        ax = axlist[0]
        import numpy as np
        
        # Calculate visual boundaries to filter out extreme out-of-bounds data
        y_min = df_candles['Low'].min()
        y_max = df_candles['High'].max()
        padding = (y_max - y_min) * 0.15
        view_min = y_min - padding
        view_max = y_max + padding
        
        # Lock the Y-axis so out-of-bounds drawings don't stretch the chart vertically
        ax.set_ylim(view_min, view_max)
        
        all_strikes = sorted(set([s for s, _ in resistances] + [s for s, _ in supports]))
        strike_diff = np.median(np.diff(all_strikes)) if len(all_strikes) > 1 else 10.0
        span_half = max(strike_diff / 4.0, 1.0)

        for strike, oi in resistances:
            if view_min <= strike <= view_max:
                ax.axhspan(strike - span_half, strike + span_half, color='red', alpha=0.2)
                ax.axhline(strike, color='red', linestyle='--', alpha=0.5, linewidth=1)
                ax.text(len(df_candles) - 1, strike, f' Res: {strike} (OI:{int(oi)})', color='darkred', va='center', ha='left', fontweight='bold', fontsize=9, bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'))
            
        for strike, oi in supports:
            if view_min <= strike <= view_max:
                ax.axhspan(strike - span_half, strike + span_half, color='green', alpha=0.2)
                ax.axhline(strike, color='green', linestyle='--', alpha=0.5, linewidth=1)
                ax.text(len(df_candles) - 1, strike, f' Sup: {strike} (OI:{int(oi)})', color='darkgreen', va='center', ha='left', fontweight='bold', fontsize=9, bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'))

        # Add extra padding on the right for the text labels
        ax.set_xlim(ax.get_xlim()[0], len(df_candles) + (len(df_candles) * 0.15))

        plot_file = asset_dir / f"{clean_name.lower()}_hybrid_{tf_name.lower()}_{timestamp}.png"
        fig.savefig(plot_file, bbox_inches='tight')
        plt.close(fig)
        print(f"[OK] {tf_name} Chart saved as: {plot_file}")

async def main():
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    output_base = Path("trading_results")
    output_base.mkdir(exist_ok=True)
    
    assets = [
        {'symbol': '/GC', 'min': 4550, 'max': 4850, 'title': 'Gold (/GC)'},
        {'symbol': '/ES', 'min': 6500, 'max': 7100, 'title': 'S&P 500 (/ES)'},
        {'symbol': '/NQ', 'min': 26000, 'max': 28500, 'title': 'NASDAQ (/NQ)'}
    ]
    
    for asset in assets:
        await generate_hybrid_chart(session, asset, output_base)

if __name__ == "__main__":
    asyncio.run(main())
