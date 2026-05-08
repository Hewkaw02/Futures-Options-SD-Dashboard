# config.py - Centralized Credentials File
# Loads credentials from .env file for security. Never hard-code secrets.

import os
from dotenv import load_dotenv

load_dotenv()

# Tastytrade OAuth Credentials (from .env)
CLIENT_SECRET = os.getenv("TASTYTRADE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("TASTYTRADE_REFRESH_TOKEN")

if not CLIENT_SECRET or not REFRESH_TOKEN:
    raise RuntimeError(
        "Missing credentials. Create a .env file with:\n"
        "  TASTYTRADE_CLIENT_SECRET=...\n"
        "  TASTYTRADE_REFRESH_TOKEN=...\n"
    )

# Contract multipliers for futures products (CME standard)
# Used in GEX normalization: raw_gex * multiplier = dollar-notional GEX
CONTRACT_MULTIPLIERS = {
    "GC": 100,   # Gold: 100 troy oz per contract
    "ES": 50,    # S&P 500 E-mini: $50 per index point
    "NQ": 20,    # NASDAQ E-mini: $20 per index point
}
