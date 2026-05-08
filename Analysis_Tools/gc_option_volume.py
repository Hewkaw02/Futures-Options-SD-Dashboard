import asyncio
from datetime import date
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Summary
import yfinance as yf

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

async def main():
    print("Connecting to Tastytrade...")
    try:
        session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
        print("[OK] Session Established")
    except Exception as e:
        print(f"[FAIL] Login Failed: {e}")
        return

    symbol = "/GC"
    print(f"Fetching Option Chain for {symbol}...")
    chain = await get_future_option_chain(session, symbol)
    
    # Get the nearest expiry
    all_expiries = sorted(chain.keys())
    # Filter for future expiries
    today = date.today()
    future_expiries = [d for d in all_expiries if d >= today]
    
    if not future_expiries:
        print("No future expiries found.")
        return
        
    target_expiry = future_expiries[0]
    options = chain[target_expiry]
    print(f"Target Expiry: {target_expiry} (Found {len(options)} options)")

    # Auto-range: use yfinance to get current Gold price, then +/-5%
    try:
        data = yf.Ticker('GC=F').history(period='1d')
        current_price = float(data['Close'].iloc[-1]) if not data.empty else None
    except Exception:
        current_price = None

    if current_price:
        strike_min = current_price * 0.95
        strike_max = current_price * 1.05
        print(f"  Auto-range: {strike_min:.0f} - {strike_max:.0f} (based on price {current_price:.2f})")
    else:
        # Fallback: use median strike from chain
        all_strikes = sorted([float(o.strike_price) for o in options])
        mid = all_strikes[len(all_strikes) // 2]
        strike_min, strike_max = mid * 0.95, mid * 1.05
        print(f"  Fallback range: {strike_min:.0f} - {strike_max:.0f}")

    strikes_of_interest = [o for o in options if strike_min <= float(o.strike_price) <= strike_max]
    streamer_symbols = [o.streamer_symbol for o in strikes_of_interest]
    
    if not streamer_symbols:
        print("No options found in the specified strike range.")
        return

    print(f"Subscribing to {len(streamer_symbols)} symbols...")
    
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Summary, streamer_symbols)
        
        print(f"\n{'Strike':<8} | {'Type':<4} | {'Volume':<8} | {'Open Int':<10}")
        print("-" * 40)
        
        # We'll try to collect data for a few seconds since events come in asynchronously
        results = {}
        try:
            # Wait for up to 5 seconds to gather data
            end_time = asyncio.get_event_loop().time() + 5
            while asyncio.get_event_loop().time() < end_time:
                try:
                    summary = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.5)
                    results[summary.event_symbol] = summary
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            print(f"Data collection ended: {e}")

        # Display results
        # Sort options to display neatly
        strikes_of_interest.sort(key=lambda x: (float(x.strike_price), x.option_type.value))
        
        for opt in strikes_of_interest:
            summary = results.get(opt.streamer_symbol)
            if summary:
                vol = summary.prev_day_volume if summary.prev_day_volume else 0
                oi = summary.open_interest if summary.open_interest else 0
                print(f"{float(opt.strike_price):<8} | {opt.option_type.value:<4} | {vol:<8} | {oi:<10}")
            else:
                # If no summary received yet
                pass

if __name__ == "__main__":
    asyncio.run(main())
