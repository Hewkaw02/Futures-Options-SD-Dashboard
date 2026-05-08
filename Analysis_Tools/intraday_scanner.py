import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
from datetime import date, datetime
from pathlib import Path
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain, Future
from tastytrade.dxfeed import Trade, Summary, Greeks, Underlying, Quote

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

# Mapping Tastytrade Symbols to Yahoo Finance Symbols
YF_MAPPING = {'/GC': 'GC=F', '/ES': 'ES=F', '/NQ': 'NQ=F'}

async def get_auto_range(session, symbol_root):
    """Find current price using Yahoo Finance for accuracy."""
    print(f"Finding current price for {symbol_root} using yfinance...")
    try:
        yf_sym = YF_MAPPING.get(symbol_root)
        if not yf_sym:
            return None, None, None
            
        ticker = yf.Ticker(yf_sym)
        data = ticker.history(period='1d')
        if data.empty:
            print(f"  [WARN] No yfinance data for {yf_sym}")
            return None, None, None
            
        current_price = float(data['Close'].iloc[-1])
        
        # Calculate Range
        perc = 0.03 if 'GC' in symbol_root else 0.05
        min_s = current_price * (1 - perc)
        max_s = current_price * (1 + perc)
        
        return current_price, min_s, max_s
    except Exception as e:
        print(f"  [WARN] Error in get_auto_range: {e}")
        return None, None, None

async def scan_intraday(session, symbol_root, asset_title, output_base):
    clean_name = symbol_root.replace('/', '')
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    hour_str = now.strftime("%H00")
    timestamp = now.strftime("%H%M")
    
    asset_dir = output_base / date_str / hour_str / clean_name
    asset_dir.mkdir(parents=True, exist_ok=True)
    
    current_price, min_s, max_s = await get_auto_range(session, symbol_root)
    if not current_price:
        return

    print(f"  Current Price: {current_price:,.2f} | Range: {min_s:,.0f} - {max_s:,.0f}")

    # 1. Fetch Option Chain
    chain = await get_future_option_chain(session, symbol_root)
    expiry_dates = sorted([d for d in chain.keys() if d >= date.today()])
    if not expiry_dates:
        print(f"  [WARN] No active expiry found for {symbol_root}")
        return
    expiry = expiry_dates[0]
    options = [o for o in chain[expiry] if min_s <= float(o.strike_price) <= max_s]
    
    # Limit strikes for NQ/ES to prevent overwhelming the streamer
    if len(options) > 300:
        print(f"  [WARN] Too many strikes ({len(options)}), limiting to 300 nearest to ATM...")
        options = sorted(options, key=lambda o: abs(float(o.strike_price) - current_price))[:300]
        
    streamer_symbols = [o.streamer_symbol for o in options]

    intraday_data = {}
    try:
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Trade, streamer_symbols)
            await streamer.subscribe(Summary, streamer_symbols)
            
            print(f"  Monitoring {len(streamer_symbols)} active strikes for {asset_title}...")
            wait_time = 20 # Wait 20 seconds for data
            end_time = asyncio.get_event_loop().time() + wait_time
            
            while asyncio.get_event_loop().time() < end_time:
                # Try getting Summary
                try:
                    s_event = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.2)
                    sym = s_event.event_symbol
                    if sym not in intraday_data: intraday_data[sym] = {'today_vol': 0, 'oi': 0}
                    intraday_data[sym]['oi'] = float(s_event.open_interest or 0)
                except (asyncio.TimeoutError, Exception): pass

                # Try getting Trade
                try:
                    t_event = await asyncio.wait_for(streamer.get_event(Trade), timeout=0.2)
                    sym = t_event.event_symbol
                    if sym not in intraday_data: intraday_data[sym] = {'today_vol': 0, 'oi': 0}
                    intraday_data[sym]['today_vol'] = float(t_event.day_volume or 0)
                except (asyncio.TimeoutError, Exception): pass
    except Exception as e:
        if "LOCAL_CLOSING" not in str(e):
            print(f"  [WARN] Streamer issue for {symbol_root}: {e}")

    # 2. Process and Save
    records = []
    for opt in options:
        d = intraday_data.get(opt.streamer_symbol, {'today_vol': 0, 'oi': 0})
        records.append({
            'Strike': float(opt.strike_price),
            'Type': opt.option_type.value,
            'Today_Volume': d['today_vol'],
            'Open_Interest': d['oi']
        })
    
    df = pd.DataFrame(records)
    if df.empty: 
        print(f"  [WARN] No data collected for {symbol_root}")
        return

    # 3. Visualization
    df_pivot = df.pivot(index='Strike', columns='Type', values='Today_Volume').fillna(0)
    plt.figure(figsize=(12, 6))
    if not df_pivot.empty:
        df_pivot.plot(kind='bar', ax=plt.gca(), color={'C': 'lime', 'P': 'orange'}, alpha=0.8)
    plt.title(f"Intraday Volume - {asset_title}\nPrice: {current_price:,.2f} | {timestamp}")
    plt.tight_layout()
    plt.savefig(asset_dir / f"{clean_name.lower()}_intraday_vol_{timestamp}.png")
    plt.close()

    df.to_csv(asset_dir / f"{clean_name.lower()}_intraday_{timestamp}.csv", index=False)
    print(f"[OK] Results saved to {asset_dir}")

async def main():
    try:
        session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    except Exception as e:
        print(f"Failed to authenticate: {e}")
        return
    
    output_base = Path("intraday_results")
    output_base.mkdir(exist_ok=True)
    
    assets = [
        ('/GC', 'Gold'),
        ('/ES', 'S&P 500'),
        ('/NQ', 'NASDAQ')
    ]
    
    for symbol, title in assets:
        try:
            await scan_intraday(session, symbol, title, output_base)
        except Exception as e:
            if "LOCAL_CLOSING" not in str(e):
                print(f"  [WARN] Error scanning {symbol}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
