import asyncio
from tastytrade import Session, DXLinkStreamer
from tastytrade.dxfeed import Trade

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN


async def main():
    """Fetch real-time trade data for front-month Gold, NASDAQ, and S&P 500 futures."""
    print("Connecting to Tastytrade...")
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    print("[OK] Session Established\n")

    # Use front-month symbols — update these when contracts roll
    symbols = ["/GCJ6", "/NQM6", "/ESM6"]

    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Trade, symbols)

        for _ in range(len(symbols)):  # รับทีละ symbol
            try:
                trade = await asyncio.wait_for(streamer.get_event(Trade), timeout=10.0)
                print(f"{trade.event_symbol}")
                print(f"  last price   : {trade.price}")
                print(f"  day volume   : {trade.day_volume}")      # contracts traded today
                print(f"  day turnover : {trade.day_turnover}")    # notional value
                print()
            except asyncio.TimeoutError:
                print("  [WARN] Timeout waiting for trade data")


if __name__ == "__main__":
    asyncio.run(main())