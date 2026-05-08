import asyncio
import math
import pandas as pd
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt
from datetime import date, datetime
from pathlib import Path
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain, Future
from tastytrade.dxfeed import Greeks, Quote, Summary

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

YF_MAPPING = {'/GC': 'GC=F', '/ES': 'ES=F', '/NQ': 'NQ=F'}

async def get_price_and_iv(session, symbol_root):
    yf_symbol = YF_MAPPING.get(symbol_root)
    if not yf_symbol: return None, None
    
    # 1. Get Current Price from Yahoo Finance
    try:
        df = yf.download(yf_symbol, period="1d", interval="5m")
        if df.empty: return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        current_price = float(df['Close'].iloc[-1])
    except Exception as e:
        print(f"Error fetching YF price: {e}")
        return None, None

    # 2. Get Minimum IV from nearest Tastytrade Greeks
    min_iv = None
    try:
        chain = await get_future_option_chain(session, symbol_root)
        expiries = sorted([d for d in chain.keys() if d >= date.today()])
        if not expiries: return current_price, None
        
        target_expiry = expiries[0]
        options = chain[target_expiry]
        
        # Filter options within +/- 5% to find the baseline IV (bottom of the smile)
        min_s = current_price * 0.95
        max_s = current_price * 1.05
        relevant_options = [o for o in options if min_s <= float(o.strike_price) <= max_s]
        streamer_symbols = [o.streamer_symbol for o in relevant_options]
        
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Greeks, streamer_symbols)
            end_time = asyncio.get_event_loop().time() + 5.0
            found_vols = []
            while asyncio.get_event_loop().time() < end_time:
                try:
                    event = await asyncio.wait_for(streamer.get_event(Greeks), timeout=0.5)
                    if event.volatility and float(event.volatility) > 0:
                        found_vols.append(float(event.volatility))
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    continue
            
            if found_vols:
                min_iv = min(found_vols)
    except Exception as e:
        print(f"Error fetching IV: {e}")
            
    return current_price, min_iv

async def get_oi_walls(session, symbol, current_price):
    try:
        chain = await get_future_option_chain(session, symbol)
        expiry = sorted([d for d in chain.keys() if d >= date.today()])[0]
        options = chain[expiry]
        
        # Look around +/- 10% of current price for OI walls
        min_s = current_price * 0.90
        max_s = current_price * 1.10
        strikes_of_interest = [o for o in options if min_s <= float(o.strike_price) <= max_s]
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
        if df.empty: return [], []
        
        df_pivot = df.pivot(index='Strike', columns='Type', values='OI').fillna(0)
        if 'Call' not in df_pivot: df_pivot['Call'] = 0
        if 'Put' not in df_pivot: df_pivot['Put'] = 0
        
        top_calls = df_pivot.nlargest(3, 'Call')
        top_puts = df_pivot.nlargest(3, 'Put')
        
        resistances = [(strike, row['Call']) for strike, row in top_calls.iterrows() if row['Call'] > 0]
        supports = [(strike, row['Put']) for strike, row in top_puts.iterrows() if row['Put'] > 0]
        
        return resistances, supports
    except Exception as e:
        print(f"Error fetching OI walls: {e}")
        return [], []

async def generate_sd_chart(session, asset, output_base):
    tt_symbol = asset['symbol']
    yf_symbol = YF_MAPPING.get(tt_symbol)
    
    clean_name = tt_symbol.replace('/', '')
    
    # Create Date/Hour folder structure
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    hour_str = now.strftime('%H00')
    timestamp = now.strftime('%H%M')
    asset_dir = output_base / date_str / hour_str / clean_name
    asset_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Fetching Price and IV for {tt_symbol}...")
    price, iv = await get_price_and_iv(session, tt_symbol)
    
    if not price or not iv:
        print(f"  [WARN] Missing price or IV data for {tt_symbol}. Price: {price}, IV: {iv}")
        return
        
    print(f"Fetching OI Walls for {tt_symbol}...")
    resistances, supports = await get_oi_walls(session, tt_symbol, price)
        
    # SD Move = Price * IV * sqrt(Days / 365) — CME futures trade ~23hrs/day, use calendar days
    sd1 = price * iv * math.sqrt(1.0 / 365)
    
    timeframes = [
        {"name": "4H", "interval": "1h", "period": "1mo", "resample": "4h"}, # Will resample 1h to 4h
        {"name": "1D", "interval": "1d", "period": "3mo", "resample": None}
    ]
    
    for tf in timeframes:
        tf_name = tf["name"]
        
        print(f"Fetching {tf_name} Candlestick data for {yf_symbol}...")
        df = yf.download(yf_symbol, period=tf["period"], interval=tf["interval"])
        if df.empty: continue
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close']].astype(float)
        
        # Perform Resampling for 4H
        if tf["resample"]:
            # '4h' resampling rule groups data into 4-hour buckets
            df = df.resample(tf["resample"]).agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'})
            df = df.dropna()
            
        print(f"Generating {tf_name} Master Chart for {tt_symbol}...")
        title = f"{asset['title']} - {tf_name} Chart w/ Daily SD Bands & OI Walls\nPrice: {price:,.2f} | Daily Expected Move (1SD): +/-{sd1:,.2f} | {timestamp}"
        
        mc = mpf.make_marketcolors(up='green', down='red', edge='black', wick='black')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', gridcolor='gray', gridaxis='both')
        
        kwargs = dict(
            type='candle', volume=False, title=title, style=s,
            figsize=(14, 7), tight_layout=True, ylabel='Price', returnfig=True
        )
        
        fig, axlist = mpf.plot(df, **kwargs)
        ax = axlist[0]
        
        # Calculate visual boundaries to filter out extreme out-of-bounds data
        y_min = df['Low'].min()
        y_max = df['High'].max()
        padding = (y_max - y_min) * 0.15
        view_min = y_min - padding
        view_max = y_max + padding
        
        # Lock the Y-axis so out-of-bounds drawings don't stretch the chart vertically
        ax.set_ylim(view_min, view_max)
        
        x_pos = len(df) - 1
        bbox_props = dict(facecolor='white', alpha=0.7, edgecolor='none')
        
        # Draw Current Price Line
        if view_min <= price <= view_max:
            ax.axhline(price, color='black', linestyle='--', linewidth=1.5)
            ax.text(x_pos, price, f' Current: {price:,.1f}', color='black', va='center', fontweight='bold', fontsize=9, bbox=bbox_props)
        
        # Define SD Levels
        sd_levels = [
            (1, 'blue', '1SD', 0.15),
            (2, 'darkorange', '2SD', 0.10),
            (3, 'darkred', '3SD', 0.05)
        ]
        
        # Draw SD Bands & Text (Only if within View bounds)
        for multiplier, color, label, alpha in sd_levels:
            upper_bound = price + (multiplier * sd1)
            lower_bound = price - (multiplier * sd1)
            
            # Fill between previous SD and current SD
            prev_upper = price + ((multiplier-1) * sd1)
            prev_lower = price - ((multiplier-1) * sd1)
            
            if view_min <= upper_bound <= view_max or view_min <= prev_upper <= view_max:
                ax.axhspan(prev_upper, upper_bound, color=color, alpha=alpha)
            if view_min <= upper_bound <= view_max:
                ax.text(x_pos, upper_bound, f' +{label}: {upper_bound:,.1f}', color=color, va='bottom', fontweight='bold', fontsize=9, bbox=bbox_props)
                
            if view_min <= lower_bound <= view_max or view_min <= prev_lower <= view_max:
                ax.axhspan(lower_bound, prev_lower, color=color, alpha=alpha)
            if view_min <= lower_bound <= view_max:
                ax.text(x_pos, lower_bound, f' -{label}: {lower_bound:,.1f}', color=color, va='top', fontweight='bold', fontsize=9, bbox=bbox_props)

        # Draw OI Walls (Supports / Resistances)
        # Using solid thick lines for OI to distinguish from SD bands
        for strike, oi in resistances:
            if view_min <= strike <= view_max:
                ax.axhline(strike, color='red', linestyle='-', linewidth=2, alpha=0.6)
                ax.text(x_pos * 0.02, strike, f' OI RES: {strike:,.1f} ({int(oi)})', color='white', va='center', fontweight='bold', fontsize=8, bbox=dict(facecolor='red', alpha=0.8, edgecolor='none'))

        for strike, oi in supports:
            if view_min <= strike <= view_max:
                ax.axhline(strike, color='green', linestyle='-', linewidth=2, alpha=0.6)
                ax.text(x_pos * 0.02, strike, f' OI SUP: {strike:,.1f} ({int(oi)})', color='white', va='center', fontweight='bold', fontsize=8, bbox=dict(facecolor='green', alpha=0.8, edgecolor='none'))

        # Add horizontal padding to the right for SD labels
        ax.set_xlim(ax.get_xlim()[0], len(df) + (len(df) * 0.15))
        
        plot_file = asset_dir / f"{clean_name.lower()}_{tf_name.lower()}_master_chart_{timestamp}.png"
        fig.savefig(plot_file, bbox_inches='tight')
        plt.close(fig)
        print(f"[OK] Master Chart saved as: {plot_file}")

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
        await generate_sd_chart(session, asset, output_base)

if __name__ == "__main__":
    asyncio.run(main())
