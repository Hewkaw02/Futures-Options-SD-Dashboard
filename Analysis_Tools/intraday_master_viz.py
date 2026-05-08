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
from tastytrade.dxfeed import Greeks, Quote, Summary, Trade

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

YF_MAPPING = {'/GC': 'GC=F', '/ES': 'ES=F', '/NQ': 'NQ=F'}

async def get_trading_data(session, symbol_root):
    yf_symbol = YF_MAPPING.get(symbol_root)
    print(f"  >>> Fetching market data for {symbol_root}...")
    
    # 1. Get Current Price & Candles (5m and 1h for higher detail & overview)
    df_5m = yf.download(yf_symbol, period="3d", interval="5m")
    df_1h = yf.download(yf_symbol, period="2wk", interval="1h")
    
    if df_5m.empty or df_1h.empty: return None
    
    for _df in [df_5m, df_1h]:
        if isinstance(_df.columns, pd.MultiIndex):
            _df.columns = _df.columns.get_level_values(0)
            
    df_5m = df_5m[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    df_1h = df_1h[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    current_price = float(df_5m['Close'].iloc[-1])

    # 2. Get IV for SD Bands
    iv = None
    resistances, supports = [], []
    vol_resistances, vol_supports = [], []
    expiry_label = ""
    
    try:
        chain = await get_future_option_chain(session, symbol_root)
        # Use 0 DTE (Today's expiration) to capture today's specific expected move
        expiries = sorted([d for d in chain.keys() if d >= date.today()])
        
        target_expiry = expiries[0]
        expiry_label = target_expiry.strftime('%Y-%m-%d')
        options = chain[target_expiry]
        
        # Filter strikes around ATM and LIMIT to 100 nearest to avoid streamer crashes
        all_options_sorted = sorted(options, key=lambda o: abs(float(o.strike_price) - current_price))
        strikes_of_interest = all_options_sorted[:100] 
        streamer_symbols = [o.streamer_symbol for o in strikes_of_interest]

        async with DXLinkStreamer(session) as streamer:
            # Subscribe to Greeks for all active strikes to find the lowest IV
            await streamer.subscribe(Greeks, streamer_symbols)
            # Subscribe to Summary for OI Walls and Trade for Intraday Volume
            await streamer.subscribe(Summary, streamer_symbols)
            await streamer.subscribe(Trade, streamer_symbols)
            
            results_oi = {}
            results_vol = {}
            results_iv = []
            # Increase wait time to 8 seconds for better data capture
            end_time = asyncio.get_event_loop().time() + 8
            while asyncio.get_event_loop().time() < end_time:
                try:
                    try:
                        s_event = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.2)
                        results_oi[s_event.event_symbol] = s_event
                    except (asyncio.TimeoutError, Exception):
                        pass
                    
                    try:
                        t_event = await asyncio.wait_for(streamer.get_event(Trade), timeout=0.2)
                        results_vol[t_event.event_symbol] = t_event
                    except (asyncio.TimeoutError, Exception):
                        pass
                    
                    try:
                        g_event = await asyncio.wait_for(streamer.get_event(Greeks), timeout=0.2)
                        if g_event and g_event.volatility: 
                            results_iv.append(float(g_event.volatility))
                    except (asyncio.TimeoutError, Exception):
                        pass
                except Exception:
                    continue

        if results_iv:
            valid_ivs = [v for v in results_iv if v > 0]
            if valid_ivs:
                iv = min(valid_ivs)

        # Process OI and Volume Walls
        merged_data = []
        for opt in strikes_of_interest:
            s = results_oi.get(opt.streamer_symbol)
            t = results_vol.get(opt.streamer_symbol)
            vol_val = float(t.day_volume) if t and t.day_volume else 0
            oi_val = float(s.open_interest) if s and s.open_interest else 0
            
            if oi_val > 0 or vol_val > 0:
                merged_data.append({
                    'Strike': float(opt.strike_price),
                    'Type': 'Call' if opt.option_type.value == 'C' else 'Put',
                    'OI': oi_val,
                    'Vol': vol_val
                })
        
        if merged_data:
            df_merged = pd.DataFrame(merged_data)
            df_oi_c = df_merged[df_merged['Type'] == 'Call'].nlargest(3, 'OI')
            df_oi_p = df_merged[df_merged['Type'] == 'Put'].nlargest(3, 'OI')
            resistances = [(row['Strike'], row['OI']) for _, row in df_oi_c.iterrows()]
            supports = [(row['Strike'], row['OI']) for _, row in df_oi_p.iterrows()]
            
            df_vol_c = df_merged[df_merged['Type'] == 'Call'].nlargest(3, 'Vol')
            df_vol_p = df_merged[df_merged['Type'] == 'Put'].nlargest(3, 'Vol')
            vol_resistances = [(row['Strike'], row['Vol']) for _, row in df_vol_c.iterrows() if row['Vol'] > 0]
            vol_supports = [(row['Strike'], row['Vol']) for _, row in df_vol_p.iterrows() if row['Vol'] > 0]

    except Exception as e:
        print(f"    [WARN] Error fetching Tastytrade data: {e}")

    return {
        'df_5m': df_5m,
        'df_1h': df_1h,
        'price': current_price,
        'iv': iv,
        'resistances': resistances,
        'supports': supports,
        'vol_resistances': vol_resistances,
        'vol_supports': vol_supports,
        'expiry': expiry_label
    }

async def generate_intraday_master(session, asset, output_base):
    data = await get_trading_data(session, asset['symbol'])
    if not data: return
    
    price = data['price']
    iv = data['iv']
    
    clean_name = asset['symbol'].replace('/', '')
    
    # Create Date/Hour folder structure
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    hour_str = now.strftime('%H00')
    timestamp = now.strftime('%H%M')
    asset_dir = output_base / date_str / hour_str / clean_name
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Calculate SD Bands (365 calendar days — CME futures trade ~23hrs/day)
    sd1 = price * iv * math.sqrt(1.0 / 365) if iv else 0
    iv_text = f"{iv*100:.1f}%" if iv else "N/A"

    for tf_name, df_raw in [("5m", data['df_5m']), ("1h", data['df_1h'])]:
        df = df_raw.copy()
        
        # 1. Calculate VWAP
        df['Typical_Price'] = (df['High'] + df['Low'] + df['Close']) / 3
        df['Volume_TP'] = df['Volume'] * df['Typical_Price']
        df['Trade_Date'] = df.index.date
        df['VWAP'] = df.groupby('Trade_Date')['Volume_TP'].cumsum() / df.groupby('Trade_Date')['Volume'].cumsum()

        # ZOOM LOGIC: Take only the last N candles
        zoom_candles = 48 if tf_name == "5m" else 72
        df_plot = df.tail(zoom_candles).copy()
        
        title = f"INTRADAY MASTER (ZOOM) - {asset['title']} ({tf_name})\nPrice: {price:,.2f} | IV: {iv_text} | {timestamp}"
        mc = mpf.make_marketcolors(up='green', down='red', edge='black', wick='black')
        style = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', gridcolor='gray')
        
        # Visual Bounds based on zoomed data
        y_min, y_max = df_plot['Low'].min(), df_plot['High'].max()
        view_pad = (y_max - y_min) * (0.08 if tf_name == "5m" else 0.15)
        view_min, view_max = y_min - view_pad, y_max + view_pad

        addplots = [mpf.make_addplot(df_plot['VWAP'], color='fuchsia', width=1.5, label='VWAP')]
        
        fig, axlist = mpf.plot(
            df_plot, type='candle', style=style, title=title,
            figsize=(15, 10), tight_layout=True,
            addplot=addplots, returnfig=True
        )
        ax = axlist[0]
        ax.set_ylim(view_min, view_max)

        # Highlight Today's Section
        today_data = df_plot.index[df_plot.index.date == date.today()]
        if not today_data.empty:
            # Find the index of the first 'today' candle in the zoomed view
            first_today_ts = today_data[0]
            try:
                # Find its integer position in the df_plot index
                idx_pos = df_plot.index.get_loc(first_today_ts)
                # Highlight from today's start to the end of the chart
                ax.axvspan(idx_pos - 0.5, len(df_plot) + 20, color='gold', alpha=0.08)
                # Add a vertical divider
                ax.axvline(idx_pos - 0.5, color='orange', linestyle='--', alpha=0.4, linewidth=1)
            except:
                pass
        
        x_pos = len(df_plot) - 1
        bbox_props = dict(facecolor='white', alpha=0.7, edgecolor='none')

        # Draw SD Bands
        if iv and sd1 > 0:
            sd_lvls = [(1, 'blue', 0.1), (2, 'orange', 0.08), (3, 'red', 0.05)]
            for m, col, alpha in sd_lvls:
                up, lo = price + m*sd1, price - m*sd1
                prev_up, prev_lo = price + (m-1)*sd1, price - (m-1)*sd1
                if view_min <= up <= view_max or view_min <= prev_up <= view_max:
                    ax.axhspan(prev_up, up, color=col, alpha=alpha)
                if view_min <= lo <= view_max or view_min <= prev_lo <= view_max:
                    ax.axhspan(lo, prev_lo, color=col, alpha=alpha)

            if view_min <= price + sd1 <= view_max: ax.text(x_pos, price + sd1, f' +1 SD: {price+sd1:,.1f}', color='blue', va='bottom', fontweight='bold', fontsize=9, bbox=bbox_props)
            if view_min <= price - sd1 <= view_max: ax.text(x_pos, price - sd1, f' -1 SD: {price-sd1:,.1f}', color='blue', va='top', fontweight='bold', fontsize=9, bbox=bbox_props)
        
        # Draw OI Walls (Solid Lines)
        for strike, oi in data['resistances']:
            if view_min <= strike <= view_max:
                ax.axhline(strike, color='red', linewidth=2.5, alpha=0.6)
                ax.text(x_pos * 0.05, strike, f' OI RES: {strike} (OI:{int(oi)})', color='white', fontweight='bold', fontsize=8, bbox=dict(facecolor='red', alpha=0.8, edgecolor='none'))
                
        for strike, oi in data['supports']:
            if view_min <= strike <= view_max:
                ax.axhline(strike, color='green', linewidth=2.5, alpha=0.6)
                ax.text(x_pos * 0.05, strike, f' SUP: {strike} (OI:{int(oi)})', color='white', fontweight='bold', fontsize=8, bbox=dict(facecolor='green', alpha=0.7, edgecolor='none'))

        # Draw Intraday Volume Walls (Dashed Lines)
        for strike, vol in data['vol_resistances']:
            if view_min <= strike <= view_max:
                ax.axhline(strike, color='red', linestyle='--', linewidth=1.5, alpha=0.8)
                ax.text(x_pos * 0.4, strike, f' VOL RES: {strike} (V:{int(vol)})', color='red', fontweight='bold', fontsize=8, bbox=dict(facecolor='white', alpha=0.7, edgecolor='red'))
                
        for strike, vol in data['vol_supports']:
            if view_min <= strike <= view_max:
                ax.axhline(strike, color='green', linestyle='--', linewidth=1.5, alpha=0.8)
                ax.text(x_pos * 0.4, strike, f' VOL SUP: {strike} (V:{int(vol)})', color='green', fontweight='bold', fontsize=8, bbox=dict(facecolor='white', alpha=0.7, edgecolor='green'))

        # Current Price Label
        if view_min <= price <= view_max:
            ax.axhline(price, color='black', linestyle=':', alpha=0.5)
            ax.text(x_pos, price, f' CURRENT: {price:,.2f}', color='black', fontweight='bold', ha='left', va='center', bbox=dict(facecolor='white', alpha=0.8))

        # Padding for labels
        x_pad = 0.12 if tf_name == "5m" else 0.20
        ax.set_xlim(ax.get_xlim()[0], len(df_plot) + (len(df_plot) * x_pad))

        plot_file = asset_dir / f"{clean_name.lower()}_intraday_master_{tf_name}_{timestamp}.png"
        fig.savefig(plot_file, bbox_inches='tight')
        plt.close(fig)
        print(f"[OK] Intraday Master Chart ({tf_name}) saved: {plot_file}")

async def main():
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    output_base = Path("intraday_results")
    assets = [
        {'symbol': '/GC', 'title': 'Gold'},
        {'symbol': '/ES', 'title': 'S&P 500'},
        {'symbol': '/NQ', 'title': 'NASDAQ'}
    ]
    for asset in assets:
        await generate_intraday_master(session, asset, output_base)

if __name__ == "__main__":
    asyncio.run(main())
