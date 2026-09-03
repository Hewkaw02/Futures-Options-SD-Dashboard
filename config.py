# config.py - Centralized Credentials File (Multi-Provider)
# Loads credentials from .env file for security. Never hard-code secrets.

import os
from dotenv import load_dotenv

load_dotenv()

# === Active Provider Selection ===
# Options:
#   1. tastytrade  - Default (CME Futures Options: GC, ES, NQ)
#   2. databento   - Direct CME Globex Feed ($125 free credits)
#   3. ibkr        - Interactive Brokers via TWS/Gateway
#   4. yfinance    - Free Futures Price Data & Candles (No Options)
#   5. deribit     - Free Crypto Options (BTC, ETH - No Key Needed)
ACTIVE_PROVIDER = os.getenv("ACTIVE_PROVIDER", "tastytrade")

# === Tastytrade OAuth Credentials (from .env) ===
CLIENT_SECRET = os.getenv("TASTYTRADE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("TASTYTRADE_REFRESH_TOKEN")

# Only enforce Tastytrade credentials if it's the active provider
if ACTIVE_PROVIDER == "tastytrade":
    if not CLIENT_SECRET or not REFRESH_TOKEN:
        raise RuntimeError(
            "Missing Tastytrade credentials. Create a .env file with:\n"
            "  TASTYTRADE_CLIENT_SECRET=...\n"
            "  TASTYTRADE_REFRESH_TOKEN=...\n"
            "Or set ACTIVE_PROVIDER to another provider in .env (e.g. databento, deribit, yfinance).\n"
            "See docs/ADAPTERS.md for setup instructions."
        )

# Contract multipliers for futures & crypto products
# Used in GEX normalization: raw_gex * multiplier = dollar-notional GEX
CONTRACT_MULTIPLIERS = {
    "GC": 100,   # Gold: 100 troy oz per contract
    "ES": 50,    # S&P 500 E-mini: $50 per index point
    "NQ": 20,    # NASDAQ E-mini: $20 per index point
    "BTC": 1,    # Bitcoin: 1 BTC per contract (Deribit)
    "ETH": 1,    # Ethereum: 1 ETH per contract (Deribit)
}
