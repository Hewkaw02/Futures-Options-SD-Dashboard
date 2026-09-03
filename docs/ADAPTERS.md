# Data Provider Connection Guide

> **Quick Start:** Set `ACTIVE_PROVIDER` in `.env` → add credentials → run `python run_all.py`

This project is curated to support **5 proven data providers** covering CME Futures Options (/GC, /ES, /NQ), futures pricing, and crypto options.

---

## Table of Contents

1. [Tastytrade](#1-tastytrade-default) — CME Futures Options via Brokerage API
2. [Databento](#2-databento-recommended) — Direct CME Globex Feed ($125 Free Credits)
3. [Interactive Brokers](#3-interactive-brokers-ibkr) — Global & CME Futures Options
4. [Yahoo Finance](#4-yahoo-finance-free) — Free Futures Prices & Historical Candles
5. [Deribit](#5-deribit-free-crypto) — Free Crypto Options (BTC, ETH)
6. [Multi-Provider Usage Example](#multi-provider-usage-example)
7. [Writing Your Own Custom Adapter](#writing-your-own-custom-adapter)

---

## Provider Compatibility Matrix

| Asset | Tastytrade | Databento | IBKR | Yahoo Finance | Deribit |
|---|:---:|:---:|:---:|:---:|:---:|
| **Gold /GC Options** | ✅ Live + Greeks | ✅ Tick/Depth (Greeks calc) | ✅ Live + Greeks | ❌ | ❌ |
| **S&P 500 /ES Options** | ✅ Live + Greeks | ✅ Tick/Depth (Greeks calc) | ✅ Live + Greeks | ❌ | ❌ |
| **NASDAQ /NQ Options** | ✅ Live + Greeks | ✅ Tick/Depth (Greeks calc) | ✅ Live + Greeks | ❌ | ❌ |
| **Futures Prices (/GC, /ES, /NQ)** | ✅ Chain inferred | ✅ Trade/OHLCV | ✅ Live quotes | ✅ Free | ❌ |
| **Historical OHLCV Candles** | ✅ yfinance sync | ✅ Direct Globex | ✅ TWS Historical | ✅ Free | ✅ TradingView feed |
| **Crypto Options (BTC, ETH)** | ❌ | ❌ | ❌ | ❌ | ✅ Free 100% |

---

## 1. Tastytrade (Default)

**Asset Class:** CME Futures Options (/GC, /ES, /NQ)  
**Cost:** Free with brokerage account  
**Setup Difficulty:** ⭐ Easy  

### Setup Instructions
1. Create an account at [Tastytrade](https://tastytrade.com/welcome/?referralCode=YGHF9JJZCV).
2. Go to your **Account / Developer Portal** → Generate OAuth Client Secret & Refresh Token.
3. Configure your `.env`:
   ```env
   ACTIVE_PROVIDER=tastytrade
   TASTYTRADE_CLIENT_SECRET=your_client_secret_here
   TASTYTRADE_REFRESH_TOKEN=your_refresh_token_here
   ```
4. Verify connection:
   ```bash
   python -c "
   import asyncio
   from adapters import AdapterRegistry
   async def test():
       a = AdapterRegistry.from_env('tastytrade')
       await a.connect()
       print(f'Connected: {a.is_connected}')
       await a.disconnect()
   asyncio.run(test())
   "
   ```

---

## 2. Databento (Recommended)

**Asset Class:** CME Futures Options (/GC, /ES, /NQ) — Direct CME Globex Feed  
**Cost:** **$125 in Free API Credits** on signup, then pay-per-GB  
**Setup Difficulty:** ⭐ Easy  

### Why Databento?
- **Direct exchange data:** Straight from CME Globex MDP 3.0 (`GLBX.MDP3`).
- **Tick-level detail & 10-level order book depth.**
- No complicated broker setup or account minimums required.

### Setup Instructions
1. Register at [databento.com](https://databento.com) (you will instantly receive $125 free credit).
2. Navigate to **API Keys** → Generate a key (starts with `db-`).
3. Configure your `.env`:
   ```env
   ACTIVE_PROVIDER=databento
   DATABENTO_API_KEY=db-your-key-here
   ```
4. Verify connection:
   ```bash
   python -c "
   import asyncio
   from adapters import AdapterRegistry
   async def test():
       a = AdapterRegistry.from_env('databento')
       if await a.connect():
           price = await a.get_futures_price('GC')
           print(f'Databento GC Price: {price.price}')
           await a.disconnect()
   asyncio.run(test())
   "
   ```

---

## 3. Interactive Brokers (IBKR)

**Asset Class:** CME & Global Futures Options  
**Cost:** Free API (requires IBKR account + market data subscription)  
**Setup Difficulty:** ⭐⭐ Medium  

### Setup Instructions
1. Install and start **TWS** (Trader Workstation) or **IB Gateway**.
2. Enable Socket API in TWS Settings:
   - `Global Configuration` → `API` → `Settings`
   - Enable `Enable ActiveX and Socket Clients`
   - Port: `7497` (Paper trading) or `7496` (Live trading)
3. Configure your `.env`:
   ```env
   ACTIVE_PROVIDER=ibkr
   IBKR_HOST=127.0.0.1
   IBKR_PORT=7497
   IBKR_CLIENT_ID=1
   ```
4. Verify connection:
   ```bash
   python -c "
   import asyncio
   from adapters import AdapterRegistry
   async def test():
       a = AdapterRegistry.from_env('ibkr')
       if await a.connect():
           print('Connected to IBKR TWS!')
           await a.disconnect()
   asyncio.run(test())
   "
   ```

---

## 4. Yahoo Finance (Free)

**Asset Class:** Futures Prices & Historical Candlesticks  
**Cost:** 🟢 100% Free — No API key needed  
**Setup Difficulty:** ⭐ Easy  

> **Note:** Yahoo Finance provides spot/futures **prices** (e.g. `GC=F`, `ES=F`, `NQ=F`) and historical candles, but **does not provide CME futures options chains**. Use this as a lightweight free price source.

### Setup Instructions
1. Configure your `.env`:
   ```env
   ACTIVE_PROVIDER=yfinance
   ```
2. Verify:
   ```bash
   python -c "
   import asyncio
   from adapters import AdapterRegistry
   async def test():
       a = AdapterRegistry.get('yfinance')
       await a.connect()
       p = await a.get_futures_price('GC')
       print(f'Yahoo Finance Gold Price: {p.price}')
       await a.disconnect()
   asyncio.run(test())
   "
   ```

---

## 5. Deribit (Free Crypto)

**Asset Class:** Crypto Options (BTC, ETH)  
**Cost:** 🟢 100% Free Public Market Data — No API key needed  
**Setup Difficulty:** ⭐ Easy  

### Setup Instructions
1. Configure your `.env`:
   ```env
   ACTIVE_PROVIDER=deribit
   ```
2. Verify:
   ```bash
   python -c "
   import asyncio
   from adapters import AdapterRegistry
   async def test():
       a = AdapterRegistry.get('deribit')
       await a.connect()
       chain = await a.get_option_chain('BTC')
       print(f'Fetched {len(chain)} BTC option contracts from Deribit!')
       if chain:
           print(f'Sample: Strike={chain[0].strike}, Delta={chain[0].delta:.4f}, IV={chain[0].iv:.2f}')
       await a.disconnect()
   asyncio.run(test())
   "
   ```

---

## Multi-Provider Usage Example

You can mix and match data from different providers simultaneously in your scripts:

```python
import asyncio
from adapters import AdapterRegistry

async def multi_source_pipeline():
    # 1. CME Options Chain from Tastytrade or Databento
    cme_adapter = AdapterRegistry.from_env("tastytrade")
    await cme_adapter.connect()
    gc_chain = await cme_adapter.get_option_chain("GC")
    await cme_adapter.disconnect()

    # 2. Crypto Options Chain from Deribit (Free)
    crypto_adapter = AdapterRegistry.get("deribit")
    await crypto_adapter.connect()
    btc_chain = await crypto_adapter.get_option_chain("BTC")
    await crypto_adapter.disconnect()

    # 3. Free historical candle baseline from Yahoo Finance
    yf_adapter = AdapterRegistry.get("yfinance")
    await yf_adapter.connect()
    candles = await yf_adapter.get_historical_candles("ES", period="30d")
    await yf_adapter.disconnect()

    print(f"GC Options: {len(gc_chain)}, BTC Options: {len(btc_chain)}, ES Bars: {len(candles)}")

asyncio.run(multi_source_pipeline())
```

---

## Writing Your Own Custom Adapter

To plug in a new data provider:
1. Create `adapters/my_custom_adapter.py`
2. Subclass `BaseDataAdapter` and decorate with `@AdapterRegistry.register("name")`:

```python
from adapters.base import BaseDataAdapter, UnifiedOptionData, UnifiedFuturesData, AssetClass
from adapters.registry import AdapterRegistry

@AdapterRegistry.register("my_provider", env_keys=["MY_API_KEY"])
class MyCustomAdapter(BaseDataAdapter):
    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_option_chain(self, symbol, expiry=None):
        # Fetch data and return list[UnifiedOptionData]
        return []

    async def get_futures_price(self, symbol):
        return UnifiedFuturesData(symbol=symbol, price=0.0)

    async def get_historical_candles(self, symbol, period="30d", interval="1d"):
        import pandas as pd
        return pd.DataFrame()

    def get_supported_symbols(self):
        return ["GC", "ES", "NQ"]

    def get_provider_name(self):
        return "My Custom Provider"

    def get_asset_class(self):
        return AssetClass.FUTURES_OPTIONS
```
3. Import your adapter in `adapters/__init__.py`.
