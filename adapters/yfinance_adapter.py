"""
Yahoo Finance Data Provider Adapter.

Uses `yfinance` to fetch real-time market quotes and historical candlestick
data for CME/COMEX/NYMEX/CBOT futures contracts (e.g., GC=F, ES=F, NQ=F),
as well as option chains for US equity underlyings (e.g., SPY, QQQ, AAPL).

Key Characteristics & Architecture:
- Cost: 100% Free public market data source (no API keys required).
- Role: Supplementary price data feed and historical candle provider.
- Asset Class: AssetClass.FUTURES (primarily a futures/equity price provider).
- Futures Options Limitation:
    Yahoo Finance does NOT provide CME futures option chains (e.g. Gold/ES options).
    For futures symbols, `get_option_chain()` returns an empty list `[]`.
    For US equity underlyings (SPY, QQQ, AAPL), standard equity option chains are supported.
- Greeks:
    Greeks (Delta, Gamma, Theta, Vega, Rho) are NOT computed or provided by Yahoo Finance
    and are initialized to 0.0. Implied Volatility (IV) is parsed when provided by Yahoo.
- Async Execution:
    Wraps synchronous `yfinance` calls using `asyncio.to_thread` to maintain a non-blocking
    event loop across all async adapter consumers.

API References:
- yfinance SDK: https://github.com/ranaroussi/yfinance
- Yahoo Finance: https://finance.yahoo.com/
"""

import asyncio
from datetime import date, datetime
import math
from typing import Any, Optional

import pandas as pd

from .base import AssetClass, BaseDataAdapter, UnifiedFuturesData, UnifiedOptionData
from .registry import AdapterRegistry

# Graceful import of yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    YFINANCE_AVAILABLE = False


@AdapterRegistry.register("yfinance")
class YFinanceAdapter(BaseDataAdapter):
    """
    Yahoo Finance Data Adapter for Futures Prices, Historical Candles,
    and US Equity Option Chains.
    """

    # Mapping of standard root symbols to Yahoo Finance ticker symbols
    YF_FUTURES_MAP: dict[str, str] = {
        "GC": "GC=F",   # Gold (COMEX)
        "SI": "SI=F",   # Silver (COMEX)
        "HG": "HG=F",   # Copper (COMEX)
        "PL": "PL=F",   # Platinum (NYMEX)
        "PA": "PA=F",   # Palladium (NYMEX)
        "ES": "ES=F",   # E-mini S&P 500 (CME)
        "NQ": "NQ=F",   # E-mini Nasdaq-100 (CME)
        "YM": "YM=F",   # E-mini Dow (CBOT)
        "RTY": "RTY=F", # E-mini Russell 2000 (CME)
        "CL": "CL=F",   # Crude Oil (NYMEX)
        "NG": "NG=F",   # Natural Gas (NYMEX)
        "RB": "RB=F",   # RBOB Gasoline (NYMEX)
        "HO": "HO=F",   # Heating Oil (NYMEX)
        "ZB": "ZB=F",   # 30-Year U.S. Treasury Bond (CBOT)
        "ZN": "ZN=F",   # 10-Year U.S. Treasury Note (CBOT)
        "ZF": "ZF=F",   # 5-Year U.S. Treasury Note (CBOT)
        "ZT": "ZT=F",   # 2-Year U.S. Treasury Note (CBOT)
        "ZC": "ZC=F",   # Corn (CBOT)
        "ZS": "ZS=F",   # Soybeans (CBOT)
        "ZW": "ZW=F",   # Wheat (CBOT)
        "ZM": "ZM=F",   # Soybean Meal (CBOT)
        "ZL": "ZL=F",   # Soybean Oil (CBOT)
        "6E": "6E=F",   # Euro FX (CME)
        "6B": "6B=F",   # British Pound (CME)
        "6J": "6J=F",   # Japanese Yen (CME)
        "6A": "6A=F",   # Australian Dollar (CME)
        "6C": "6C=F",   # Canadian Dollar (CME)
        "BTC": "BTC=F", # Bitcoin Futures (CME)
        "ETH": "ETH=F", # Ethereum Futures (CME)
    }

    # Contract multipliers for notional calculations
    CONTRACT_MULTIPLIERS: dict[str, float] = {
        "GC": 100.0,    # Gold: 100 troy oz
        "SI": 5000.0,   # Silver: 5,000 troy oz
        "HG": 25000.0,  # Copper: 25,000 lbs
        "ES": 50.0,     # E-mini S&P 500: $50 x index
        "NQ": 20.0,     # E-mini Nasdaq-100: $20 x index
        "YM": 5.0,      # E-mini Dow: $5 x index
        "RTY": 50.0,    # E-mini Russell 2000: $50 x index
        "CL": 1000.0,   # Crude Oil: 1,000 barrels
        "NG": 10000.0,  # Natural Gas: 10,000 MMBtu
        "ZB": 1000.0,   # 30-Year U.S. Treasury Bond
        "ZN": 1000.0,   # 10-Year U.S. Treasury Note
        "ZF": 1000.0,   # 5-Year U.S. Treasury Note
        "ZT": 2000.0,   # 2-Year U.S. Treasury Note
        "ZC": 5000.0,   # Corn: 5,000 bushels
        "ZS": 5000.0,   # Soybeans: 5,000 bushels
        "ZW": 5000.0,   # Wheat: 5,000 bushels
        "SPY": 100.0,   # SPY Equity Option: 100 shares
        "QQQ": 100.0,   # QQQ Equity Option: 100 shares
        "IWM": 100.0,   # IWM Equity Option: 100 shares
        "DIA": 100.0,   # DIA Equity Option: 100 shares
        "AAPL": 100.0,  # Apple Equity Option: 100 shares
    }

    def __init__(self, **kwargs):
        """Initialize Yahoo Finance adapter."""
        super().__init__(**kwargs)

    # ── Required BaseDataAdapter Methods ─────────────────

    async def connect(self) -> bool:
        """
        Establish connection / validate yfinance library availability.
        Yahoo Finance is a public unauthenticated API, so connection validates
        the SDK and sets the connected state.
        """
        if not YFINANCE_AVAILABLE:
            print(
                "[YFinance] Error: 'yfinance' package is not installed.\n"
                "          Please install it using: pip install yfinance"
            )
            self._connected = False
            return False

        self._connected = True
        print("[YFinance] Connected (Yahoo Finance public data source ready).")
        return True

    async def disconnect(self) -> None:
        """Cleanup resources and set connected status to False."""
        self._connected = False
        print("[YFinance] Disconnected.")

    async def get_futures_price(self, symbol: str) -> UnifiedFuturesData:
        """
        Fetch current market price and quote data for a futures contract or equity symbol.

        Parameters:
            symbol: Root symbol (e.g. 'GC', 'ES', 'NQ', 'CL', 'SI', 'SPY', 'QQQ')

        Returns:
            UnifiedFuturesData dataclass with price, OHLC, volume, and percent change.
        """
        if not YFINANCE_AVAILABLE:
            return UnifiedFuturesData(
                symbol=symbol.upper(),
                price=0.0,
                provider="yfinance",
                raw={"error": "yfinance package is not installed"},
            )

        sym = symbol.strip().upper()
        ticker_symbol = self._map_to_ticker_symbol(sym)

        try:
            return await asyncio.to_thread(self._fetch_price_sync, sym, ticker_symbol)
        except Exception as e:
            print(f"[YFinance] Error fetching price for '{sym}' ({ticker_symbol}): {e}")
            return UnifiedFuturesData(
                symbol=sym,
                price=0.0,
                provider="yfinance",
                raw={"error": str(e), "ticker_symbol": ticker_symbol},
            )

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """
        Fetch option chain for a symbol.

        IMPORTANT NOTES:
        1. Yahoo Finance does NOT provide CME/COMEX futures option chains.
           If a futures symbol (e.g. 'GC', 'ES', 'NQ', 'CL', 'SI') is requested,
           this method logs an informational message and returns an empty list `[]`.
        2. For US equity underlyings (e.g., 'SPY', 'QQQ', 'AAPL'), this method
           fetches calls and puts for the specified or nearest expiration date.
        3. Greeks are not provided by Yahoo Finance and are set to 0.0.

        Parameters:
            symbol: Root symbol (e.g. 'SPY', 'QQQ', 'GC')
            expiry: Optional target expiration date. If None, uses nearest expiration.

        Returns:
            List of UnifiedOptionData contracts.
        """
        if not YFINANCE_AVAILABLE:
            return []

        sym = symbol.strip().upper()

        # Check if symbol is a futures instrument (no option chains in yfinance)
        if self._is_futures_symbol(sym):
            print(
                f"[YFinance] Note: Futures option chains are not supported by Yahoo Finance for '{sym}'. "
                f"Returning empty chain. (Use an equity symbol like SPY/QQQ or a CME provider for futures options)."
            )
            return []

        try:
            return await asyncio.to_thread(self._fetch_option_chain_sync, sym, expiry)
        except Exception as e:
            print(f"[YFinance] Error fetching option chain for '{sym}': {e}")
            return []

    async def get_historical_candles(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candlestick data for a futures or equity symbol.

        Parameters:
            symbol: Root symbol (e.g. 'GC', 'ES', 'NQ', 'CL', 'SI', 'SPY')
            period: Duration string ('1d', '5d', '30d', '60d', '90d', '1mo', '3mo', '6mo', '1y', 'ytd', 'max')
            interval: Bar size ('1m', '2m', '5m', '15m', '30m', '60m', '1h', '1d', '1wk', '1mo')

        Returns:
            pd.DataFrame with columns ['Open', 'High', 'Low', 'Close', 'Volume']
            and a DatetimeIndex.
        """
        empty_df = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex([], name="Date"),
        )

        if not YFINANCE_AVAILABLE:
            return empty_df

        sym = symbol.strip().upper()
        ticker_symbol = self._map_to_ticker_symbol(sym)
        norm_period = self._normalize_period(period)
        norm_interval = self._normalize_interval(interval)

        try:
            return await asyncio.to_thread(
                self._fetch_candles_sync,
                sym,
                ticker_symbol,
                norm_period,
                norm_interval,
            )
        except Exception as e:
            print(f"[YFinance] Error fetching candles for '{sym}' ({ticker_symbol}): {e}")
            return empty_df

    def get_supported_symbols(self) -> list[str]:
        """
        List of supported symbols (CME/COMEX futures price symbols + popular equity underlyings).
        """
        return [
            # Futures prices
            "GC", "ES", "NQ", "CL", "SI", "HG", "YM", "RTY", "NG",
            "ZB", "ZN", "ZF", "ZT", "ZC", "ZS", "ZW", "6E", "6B", "6J", "BTC", "ETH",
            # Equity options & prices
            "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"
        ]

    def get_provider_name(self) -> str:
        """Human-readable provider name."""
        return "Yahoo Finance"

    def get_asset_class(self) -> AssetClass:
        """
        Asset class category for this adapter.
        Yahoo Finance is primarily used as a supplementary FUTURES/EQUITY price feed.
        """
        return AssetClass.FUTURES

    # ── Optional Methods Implementation ──────────────────

    async def get_expirations(self, symbol: str) -> list[date]:
        """
        List available expiration dates for a symbol.
        Returns empty list for futures symbols.
        """
        if not YFINANCE_AVAILABLE:
            return []

        sym = symbol.strip().upper()
        if self._is_futures_symbol(sym):
            return []

        try:
            return await asyncio.to_thread(self._fetch_expirations_sync, sym)
        except Exception as e:
            print(f"[YFinance] Error fetching expirations for '{sym}': {e}")
            return []

    async def get_strikes(self, symbol: str, expiry: date) -> list[float]:
        """List available strike prices for a given expiry date."""
        chain = await self.get_option_chain(symbol, expiry)
        return sorted(set(o.strike for o in chain))

    def get_capabilities(self) -> dict:
        """Describe adapter capabilities and supported features."""
        return {
            "provider": self.get_provider_name(),
            "asset_class": self.get_asset_class().value,
            "symbols": self.get_supported_symbols(),
            "options_chain": True,   # Supported for US Equities (SPY, QQQ, etc.)
            "futures_options": False, # CME futures options not available on Yahoo Finance
            "greeks_included": False,
            "streaming": False,
            "historical": True,
            "auth_required": False,
        }

    # ── Synchronous Worker Methods (Executed in Threads) ─

    def _fetch_price_sync(self, sym: str, ticker_symbol: str) -> UnifiedFuturesData:
        """Synchronously query yfinance for price quote data."""
        ticker = yf.Ticker(ticker_symbol)

        # Attempt to get latest 1-day or 5-day history (handles weekend / holiday closes)
        hist = ticker.history(period="1d")
        if hist.empty:
            hist = ticker.history(period="5d")

        last_price = 0.0
        open_price = 0.0
        high_price = 0.0
        low_price = 0.0
        volume = 0
        ts = datetime.now()

        if not hist.empty:
            last_row = hist.iloc[-1]
            last_price = self._clean_float(last_row.get("Close", 0.0))
            open_price = self._clean_float(last_row.get("Open", 0.0))
            high_price = self._clean_float(last_row.get("High", 0.0))
            low_price = self._clean_float(last_row.get("Low", 0.0))
            volume = self._clean_int(last_row.get("Volume", 0))
            if hasattr(last_row.name, "to_pydatetime"):
                ts = last_row.name.to_pydatetime()

        # Check fast_info as potential supplement / override
        fast_info = getattr(ticker, "fast_info", None)
        prev_close = 0.0

        if fast_info is not None:
            fi_last = self._clean_float(getattr(fast_info, "last_price", 0.0))
            if fi_last > 0:
                last_price = fi_last

            fi_open = self._clean_float(getattr(fast_info, "open", 0.0))
            if fi_open > 0:
                open_price = fi_open

            fi_high = self._clean_float(getattr(fast_info, "day_high", 0.0))
            if fi_high > 0:
                high_price = fi_high

            fi_low = self._clean_float(getattr(fast_info, "day_low", 0.0))
            if fi_low > 0:
                low_price = fi_low

            fi_prev = self._clean_float(
                getattr(fast_info, "regular_market_previous_close", 0.0)
                or getattr(fast_info, "previous_close", 0.0)
            )
            if fi_prev > 0:
                prev_close = fi_prev

        # Calculate change and percent change
        change = 0.0
        change_pct = 0.0
        if prev_close > 0.0 and last_price > 0.0:
            change = last_price - prev_close
            change_pct = (change / prev_close) * 100.0
        elif len(hist) > 1 and last_price > 0.0:
            prev_row_close = self._clean_float(hist.iloc[-2].get("Close", 0.0))
            if prev_row_close > 0.0:
                change = last_price - prev_row_close
                change_pct = (change / prev_row_close) * 100.0
        elif open_price > 0.0 and last_price > 0.0:
            change = last_price - open_price
            change_pct = (change / open_price) * 100.0

        return UnifiedFuturesData(
            symbol=sym,
            price=last_price,
            bid=0.0,
            ask=0.0,
            volume=volume,
            open_interest=0,
            high=high_price,
            low=low_price,
            open=open_price,
            change=change,
            change_pct=change_pct,
            timestamp=ts,
            provider="yfinance",
            raw={
                "ticker_symbol": ticker_symbol,
                "previous_close": prev_close,
                "history_rows": len(hist),
            },
        )

    def _fetch_option_chain_sync(
        self,
        sym: str,
        expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """Synchronously query yfinance for equity option chains."""
        ticker = yf.Ticker(sym)
        options_dates = ticker.options

        if not options_dates:
            print(f"[YFinance] No option chains available for '{sym}'.")
            return []

        # Parse available expiration dates (formatted as 'YYYY-MM-DD')
        today = date.today()
        exp_date_map: dict[str, date] = {}
        for d_str in options_dates:
            try:
                d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                if d_obj >= today:
                    exp_date_map[d_str] = d_obj
            except ValueError:
                pass

        # Fallback if all dates are past or formatted differently
        if not exp_date_map:
            for d_str in options_dates:
                try:
                    exp_date_map[d_str] = datetime.strptime(d_str, "%Y-%m-%d").date()
                except ValueError:
                    pass

        if not exp_date_map:
            print(f"[YFinance] Could not parse expiration dates for '{sym}'.")
            return []

        # Resolve target expiration date
        target_exp_str: str = ""
        target_exp_date: date = today

        if expiry is not None:
            exp_str_req = expiry.strftime("%Y-%m-%d")
            if exp_str_req in exp_date_map:
                target_exp_str = exp_str_req
                target_exp_date = expiry
            else:
                sorted_expiries = sorted(
                    exp_date_map.items(),
                    key=lambda item: abs((item[1] - expiry).days),
                )
                target_exp_str, target_exp_date = sorted_expiries[0]
                print(
                    f"[YFinance] Requested expiry {expiry} not found for '{sym}'. "
                    f"Using nearest available: {target_exp_date}"
                )
        else:
            sorted_expiries = sorted(exp_date_map.items(), key=lambda item: item[1])
            target_exp_str, target_exp_date = sorted_expiries[0]

        # Retrieve option chain data for target expiration date
        chain_obj = ticker.option_chain(target_exp_str)
        calls_df = getattr(chain_obj, "calls", pd.DataFrame())
        puts_df = getattr(chain_obj, "puts", pd.DataFrame())

        # Retrieve underlying price
        underlying_price = 0.0
        fast_info = getattr(ticker, "fast_info", None)
        if fast_info is not None:
            underlying_price = self._clean_float(getattr(fast_info, "last_price", 0.0))
        if underlying_price <= 0.0:
            hist = ticker.history(period="1d")
            if not hist.empty:
                underlying_price = self._clean_float(hist.iloc[-1].get("Close", 0.0))

        multiplier = self._get_multiplier(sym)
        results: list[UnifiedOptionData] = []

        # Process Calls ('C')
        if isinstance(calls_df, pd.DataFrame) and not calls_df.empty:
            for _, row in calls_df.iterrows():
                results.append(
                    self._row_to_unified_option(
                        sym=sym,
                        row=row,
                        option_type="C",
                        exp_date=target_exp_date,
                        exp_str=target_exp_str,
                        underlying_price=underlying_price,
                        multiplier=multiplier,
                    )
                )

        # Process Puts ('P')
        if isinstance(puts_df, pd.DataFrame) and not puts_df.empty:
            for _, row in puts_df.iterrows():
                results.append(
                    self._row_to_unified_option(
                        sym=sym,
                        row=row,
                        option_type="P",
                        exp_date=target_exp_date,
                        exp_str=target_exp_str,
                        underlying_price=underlying_price,
                        multiplier=multiplier,
                    )
                )

        return results

    def _fetch_candles_sync(
        self,
        sym: str,
        ticker_symbol: str,
        period: str,
        interval: str,
    ) -> pd.DataFrame:
        """Synchronously query yfinance for historical candlestick DataFrame."""
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            return pd.DataFrame(
                columns=["Open", "High", "Low", "Close", "Volume"],
                index=pd.DatetimeIndex([], name="Date"),
            )

        # Retain standard OHLCV columns
        cols_present = [col for col in ["Open", "High", "Low", "Close", "Volume"] if col in df.columns]
        cleaned_df = df[cols_present].copy()

        # Ensure numeric float/int conversion
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in cleaned_df.columns:
                cleaned_df[col] = pd.to_numeric(cleaned_df[col], errors="coerce").fillna(0.0)
            else:
                cleaned_df[col] = 0.0

        cleaned_df.index.name = "Date"
        cleaned_df.sort_index(inplace=True)
        return cleaned_df[["Open", "High", "Low", "Close", "Volume"]]

    def _fetch_expirations_sync(self, sym: str) -> list[date]:
        """Synchronously query available expiration dates for equity symbols."""
        ticker = yf.Ticker(sym)
        options_dates = ticker.options
        if not options_dates:
            return []

        today = date.today()
        expiries: set[date] = set()
        for d_str in options_dates:
            try:
                d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                if d_obj >= today:
                    expiries.add(d_obj)
            except ValueError:
                pass

        return sorted(expiries)

    # ── Internal Helper Methods ──────────────────────────

    def _map_to_ticker_symbol(self, sym: str) -> str:
        """Map standard root symbol to Yahoo Finance ticker symbol."""
        if sym in self.YF_FUTURES_MAP:
            return self.YF_FUTURES_MAP[sym]
        return sym

    def _is_futures_symbol(self, sym: str) -> bool:
        """Check if symbol represents a futures contract."""
        return sym in self.YF_FUTURES_MAP or sym.endswith("=F")

    def _get_multiplier(self, sym: str) -> float:
        """Return contract multiplier for a symbol."""
        return self.CONTRACT_MULTIPLIERS.get(sym, 100.0)

    def _row_to_unified_option(
        self,
        sym: str,
        row: Any,
        option_type: str,
        exp_date: date,
        exp_str: str,
        underlying_price: float,
        multiplier: float,
    ) -> UnifiedOptionData:
        """Convert a yfinance option row to a UnifiedOptionData instance."""
        strike = self._clean_float(row.get("strike", 0.0))
        bid = self._clean_float(row.get("bid", 0.0))
        ask = self._clean_float(row.get("ask", 0.0))
        last = self._clean_float(row.get("lastPrice", 0.0))
        volume = self._clean_int(row.get("volume", 0))
        open_interest = self._clean_int(row.get("openInterest", 0))
        iv = self._clean_float(row.get("impliedVolatility", 0.0))

        # Parse timestamp
        raw_trade_date = row.get("lastTradeDate", None)
        ts: Optional[datetime] = None
        if isinstance(raw_trade_date, datetime):
            ts = raw_trade_date
        elif hasattr(raw_trade_date, "to_pydatetime"):
            ts = raw_trade_date.to_pydatetime()
        else:
            ts = datetime.now()

        contract_symbol = str(
            row.get("contractSymbol", f"{sym}_{strike}_{option_type}_{exp_str}")
        )

        return UnifiedOptionData(
            symbol=sym,
            strike=strike,
            option_type=option_type,
            expiry=exp_date,
            bid=bid,
            ask=ask,
            last=last,
            volume=volume,
            open_interest=open_interest,
            iv=iv,
            delta=0.0,   # Greeks not provided by Yahoo Finance
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0,
            underlying_price=underlying_price,
            multiplier=multiplier,
            timestamp=ts,
            streamer_symbol=contract_symbol,
            provider="yfinance",
            raw={
                "contractSymbol": contract_symbol,
                "inTheMoney": row.get("inTheMoney", None),
                "change": row.get("change", 0.0),
                "percentChange": row.get("percentChange", 0.0),
                "currency": row.get("currency", "USD"),
            },
        )

    @staticmethod
    def _normalize_period(period: str) -> str:
        """Normalize period string for yfinance API."""
        p = period.strip().lower()
        mapping = {
            "1m": "1mo",
            "3m": "3mo",
            "6m": "6mo",
            "1y": "1y",
            "2y": "2y",
            "5y": "5y",
            "10y": "10y",
            "ytd": "ytd",
            "max": "max",
            "1d": "1d",
            "5d": "5d",
            "30d": "30d",
            "60d": "60d",
            "90d": "90d",
        }
        return mapping.get(p, p)

    @staticmethod
    def _normalize_interval(interval: str) -> str:
        """Normalize interval string for yfinance API."""
        inv = interval.strip()
        mapping = {
            "1m": "1m",
            "2m": "2m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "60m": "60m",
            "90m": "90m",
            "1h": "1h",
            "1d": "1d",
            "5d": "5d",
            "1w": "1wk",
            "1wk": "1wk",
            "1M": "1mo",
            "1mo": "1mo",
            "3mo": "3mo",
        }
        return mapping.get(inv, inv.lower())

    @staticmethod
    def _clean_float(val: Any) -> float:
        """Safely sanitize float values, handling None and NaN."""
        if val is None:
            return 0.0
        try:
            f = float(val)
            return 0.0 if (math.isnan(f) or math.isinf(f)) else f
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _clean_int(val: Any) -> int:
        """Safely sanitize integer values, handling None and NaN."""
        if val is None:
            return 0
        try:
            f = float(val)
            return 0 if (math.isnan(f) or math.isinf(f)) else int(f)
        except (ValueError, TypeError):
            return 0
