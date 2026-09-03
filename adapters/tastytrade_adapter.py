"""
Tastytrade Data Provider Adapter.

Wraps the official Tastytrade SDK (`tastytrade`) and DXLink streamer for CME
Futures and Futures Options data (/GC, /ES, /NQ), providing unified access to
live option chains, real-time model Greeks, underlying price inference, and
historical candlestick data.

Architecture & API Details:
- SDK: `tastytrade` Python SDK (OAuth session + DXLink WebSocket streamer)
- Session Auth: OAuth via `Session(provider_secret=client_secret, refresh_token=refresh_token)`
- Future Instruments: `Future.get(session)` filtered by product code (GC, ES, NQ)
- Option Chains: `get_future_option_chain(session, symbol)` returning `dict[date, list[FutureOption]]`
- Greeks: DXLink streamer (`DXLinkStreamer`) subscribing to `Greeks` events
- Mark Price: Inferred from option chain median strike (call/put parity proxy) or yfinance fallback
- Historical Candles: Historical OHLCV via `yfinance` (GC=F, ES=F, NQ=F)
- Asset Class: `AssetClass.FUTURES_OPTIONS`
- CME Multipliers: GC=100, ES=50, NQ=20

API References:
- Tastytrade Developer Portal: https://developer.tastytrade.com/
- Tastytrade Python SDK: https://github.com/tastyware/tastytrade
- DXFeed Streaming Docs: https://kb.dxfeed.com/
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import math
import os
from typing import Any, Optional

import aiohttp
import pandas as pd
import yfinance as yf

from .base import AssetClass, BaseDataAdapter, UnifiedFuturesData, UnifiedOptionData
from .registry import AdapterRegistry

# ── Tastytrade SDK Import & Error Handling ──────────────────────
try:
    from tastytrade import DXLinkStreamer, Session
    from tastytrade.dxfeed import Greeks
    from tastytrade.instruments import Future, FutureOption, get_future_option_chain
    from tastytrade.utils import TastytradeError
    import tastytrade.utils as tt_utils

    TASTYTRADE_AVAILABLE = True

    # ── Monkeypatch validate_response for Malformed API Error Payloads ──
    _original_validate_response = getattr(
        tt_utils, "_original_validate_response", tt_utils.validate_response
    )

    def _patched_validate_response(response):
        """
        Patched version of tastytrade's validate_response that handles
        when the API returns 'error' as a raw string instead of a dict.
        Prevents AttributeError ('str' object has no attribute 'get').
        """
        if response.status_code // 100 != 2:
            try:
                json_data = response.json()
            except Exception as e:
                raise TastytradeError(f"Couldn't parse response: {response.text}") from e

            content = json_data.get("error")
            if not content:
                raise TastytradeError(f"Couldn't parse response: {json_data}")

            # Handle both dict (expected) and string (malformed) error payloads
            if isinstance(content, str):
                raise TastytradeError(f"API Error: {content}")

            errors = content.get("errors") or [content]
            message = ""
            for error in errors:
                if isinstance(error, dict):
                    if "code" in error and "message" in error:
                        message += f"{error['code']}: {error['message']}\n"
                    elif "domain" in error and "reason" in error:
                        message += f"{error['domain']}: {error['reason']}\n"
                    else:
                        tt_utils.logger.debug(f"Unknown error type: {error}")

            raise TastytradeError(message)

    tt_utils._original_validate_response = _original_validate_response
    tt_utils.validate_response = _patched_validate_response

except ImportError:
    Session = None  # type: ignore
    DXLinkStreamer = None  # type: ignore
    Greeks = None  # type: ignore
    Future = None  # type: ignore
    FutureOption = None  # type: ignore
    get_future_option_chain = None  # type: ignore
    TastytradeError = Exception  # type: ignore
    TASTYTRADE_AVAILABLE = False


@AdapterRegistry.register(
    "tastytrade",
    env_keys=["TASTYTRADE_CLIENT_SECRET", "TASTYTRADE_REFRESH_TOKEN"],
)
class TastytradeAdapter(BaseDataAdapter):
    """
    Tastytrade Data Adapter for CME Futures Options (/GC, /ES, /NQ).
    Wraps the tastytrade Python SDK and DXLink streaming API.
    """

    # CME contract multipliers for dollar-notional & GEX calculations
    CONTRACT_MULTIPLIERS: dict[str, float] = {
        "GC": 100.0,  # Gold: 100 troy oz per contract
        "ES": 50.0,   # S&P 500 E-mini: $50 per index point
        "NQ": 20.0,   # Nasdaq-100 E-mini: $20 per index point
    }

    # Mapping to Yahoo Finance tickers for candle fallback & price checks
    YFINANCE_MAP: dict[str, str] = {
        "GC": "GC=F",
        "ES": "ES=F",
        "NQ": "NQ=F",
    }

    # Supported root and prefixed symbols
    SUPPORTED_SYMBOLS: list[str] = [
        "/GC",
        "/ES",
        "/NQ",
        "GC",
        "ES",
        "NQ",
    ]

    def __init__(
        self,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        session: Optional[Any] = None,
        fetch_greeks: bool = True,
        greeks_timeout: float = 4.0,
        **kwargs,
    ):
        """
        Initialize the Tastytrade adapter.

        Parameters:
            client_secret: Tastytrade OAuth client secret (default: env TASTYTRADE_CLIENT_SECRET)
            refresh_token: Tastytrade OAuth refresh token (default: env TASTYTRADE_REFRESH_TOKEN)
            session: Optional pre-authenticated tastytrade Session instance
            fetch_greeks: Whether to query DXLink streamer for live Greeks during chain fetches
            greeks_timeout: Timeout in seconds when listening for DXLink Greeks events (default: 4.0s)
        """
        super().__init__(**kwargs)
        self.client_secret = (
            client_secret
            or kwargs.get("provider_secret")
            or os.getenv("TASTYTRADE_CLIENT_SECRET")
        )
        self.refresh_token = (
            refresh_token
            or os.getenv("TASTYTRADE_REFRESH_TOKEN")
        )
        self._session: Optional[Any] = session
        self.fetch_greeks = fetch_greeks
        self.greeks_timeout = float(greeks_timeout)
        self._cached_futures: Optional[list[Any]] = None
        self._cached_front_months: dict[str, str] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)

    # ── Required Methods Implementation ──────────────────

    async def connect(self) -> bool:
        """
        Establish connection / validate OAuth session with Tastytrade API.

        Returns:
            bool: True if connection/authentication succeeded, False otherwise.
        """
        if not TASTYTRADE_AVAILABLE:
            print(
                "[Tastytrade] Error: 'tastytrade' SDK is not installed.\n"
                "            Please install it using: pip install tastytrade"
            )
            self._connected = False
            return False

        # If a session is already provided, check its validity
        if self._session is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self._executor, self._session.validate)
                self._connected = True
                print("[Tastytrade] Existing session validated successfully.")
                return True
            except Exception as e:
                print(f"[Tastytrade] Existing session invalid ({e}), creating a new session...")

        if not self.client_secret or not self.refresh_token:
            print(
                "[Tastytrade] Error: Missing credentials. Please provide "
                "TASTYTRADE_CLIENT_SECRET and TASTYTRADE_REFRESH_TOKEN in .env or arguments."
            )
            self._connected = False
            return False

        try:
            print("[Tastytrade] Authenticating session via OAuth...")
            loop = asyncio.get_running_loop()

            def _create_session():
                s = Session(
                    provider_secret=self.client_secret,
                    refresh_token=self.refresh_token,
                )
                s.validate()
                return s

            self._session = await loop.run_in_executor(self._executor, _create_session)
            self._connected = True
            print("[Tastytrade] Successfully authenticated and connected.")
            return True

        except TastytradeError as e:
            self._connected = False
            self._session = None
            print(f"[Tastytrade] Authentication failed (TastytradeError): {e}")
            return False
        except Exception as e:
            self._connected = False
            self._session = None
            print(f"[Tastytrade] Connection error: {e}")
            return False

    async def disconnect(self) -> None:
        """
        Clean up resources and invalidate session.
        """
        self._session = None
        self._cached_futures = None
        self._cached_front_months.clear()
        self._connected = False
        print("[Tastytrade] Disconnected.")

    async def get_futures_price(self, symbol: str) -> UnifiedFuturesData:
        """
        Fetch current market price and quote data for the underlying futures contract.
        Infers price from the option chain median strike, with yfinance as fallback.

        Parameters:
            symbol: Root or prefixed symbol (e.g. 'GC', '/GC', 'ES', '/ES')

        Returns:
            UnifiedFuturesData dataclass with price, high, low, volume, and timestamp.
        """
        root_sym = self._normalize_root(symbol)
        tt_sym = self._to_tastytrade_symbol(symbol)
        ts = datetime.now()

        # 1. Attempt price inference from Tastytrade option chain if connected
        if await self._ensure_connected():
            try:
                chain = await get_future_option_chain(self._session, tt_sym)
                if chain:
                    today = date.today()
                    # Look for 0 DTE or nearest future expiration
                    if today in chain:
                        target_exp = today
                    else:
                        future_dates = sorted([d for d in chain.keys() if d > today])
                        target_exp = future_dates[0] if future_dates else sorted(chain.keys())[0]

                    mark = self.infer_mark_price_from_chain(chain, target_exp)
                    if mark > 0:
                        front_month = await self.get_front_month_symbol(root_sym)
                        return UnifiedFuturesData(
                            symbol=root_sym,
                            price=mark,
                            bid=mark,
                            ask=mark,
                            timestamp=ts,
                            provider="tastytrade",
                            raw={
                                "symbol": tt_sym,
                                "front_month": front_month,
                                "expiry_used": str(target_exp),
                                "source": "chain_median_strike",
                            },
                        )
            except Exception as e:
                print(f"[Tastytrade] Notice: Could not infer price from chain for '{tt_sym}': {e}")

        # 2. Fallback to yfinance for current futures quote
        print(f"[Tastytrade] Fetching market price for '{root_sym}' via Yahoo Finance fallback...")
        yf_data = await self._fetch_yfinance_quote(root_sym)
        if yf_data is not None:
            return yf_data

        # 3. Empty data fallback if all methods fail
        return UnifiedFuturesData(
            symbol=root_sym,
            price=0.0,
            timestamp=ts,
            provider="tastytrade",
            raw={"error": f"Failed to retrieve price for {symbol}"},
        )

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """
        Fetch full option chain for a symbol with Greeks and quotes.

        Parameters:
            symbol: Root or prefixed symbol (e.g. 'GC', '/GC', 'ES', '/ES')
            expiry: Optional expiration date to filter. If None, uses nearest expiration.

        Returns:
            List of UnifiedOptionData contracts normalized to standard contract format.
        """
        if not await self._ensure_connected():
            print(f"[Tastytrade] Cannot fetch option chain: adapter not connected.")
            return []

        root_sym = self._normalize_root(symbol)
        tt_sym = self._to_tastytrade_symbol(symbol)
        multiplier = self._get_multiplier(root_sym)

        try:
            print(f"[Tastytrade] Requesting option chain for {tt_sym}...")
            chain_dict = await get_future_option_chain(self._session, tt_sym)

            if not chain_dict:
                print(f"[Tastytrade] No option chains returned for {tt_sym}.")
                return []

            # Resolve target expiration date
            today = date.today()
            target_expiry: Optional[date] = None

            if expiry is not None:
                if expiry in chain_dict:
                    target_expiry = expiry
                else:
                    sorted_expiries = sorted(
                        chain_dict.keys(),
                        key=lambda d: abs((d - expiry).days),
                    )
                    target_expiry = sorted_expiries[0]
                    print(
                        f"[Tastytrade] Requested expiry {expiry} not found. "
                        f"Using nearest available: {target_expiry}"
                    )
            else:
                # Nearest expiration (0 DTE if available today, else nearest upcoming date)
                if today in chain_dict:
                    target_expiry = today
                else:
                    future_dates = sorted([d for d in chain_dict.keys() if d > today])
                    target_expiry = future_dates[0] if future_dates else sorted(chain_dict.keys())[0]
                    print(f"[Tastytrade] Using nearest expiry: {target_expiry}")

            options = chain_dict.get(target_expiry, [])
            if not options:
                print(f"[Tastytrade] No option contracts found for {tt_sym} on {target_expiry}.")
                return []

            # Infer underlying mark price from option chain
            underlying_price = self.infer_mark_price_from_chain(chain_dict, target_expiry)
            if underlying_price <= 0:
                yf_quote = await self._fetch_yfinance_quote(root_sym)
                if yf_quote and yf_quote.price > 0:
                    underlying_price = yf_quote.price

            # Fetch live Greeks via DXLink streamer if requested
            greeks_map: dict[str, Any] = {}
            if self.fetch_greeks and options:
                greeks_map = await self._fetch_greeks_for_options(options, underlying_price)

            results: list[UnifiedOptionData] = []
            now = datetime.now()

            for opt in options:
                try:
                    strike = float(opt.strike_price)
                    opt_type_raw = (
                        opt.option_type.value
                        if hasattr(opt.option_type, "value")
                        else str(opt.option_type)
                    )
                    opt_type = "C" if opt_type_raw.upper().startswith("C") else "P"
                    streamer_sym = getattr(opt, "streamer_symbol", "") or ""

                    # Greek fields
                    iv = 0.0
                    delta = 0.0
                    gamma = 0.0
                    theta = 0.0
                    vega = 0.0
                    rho = 0.0
                    last_price = 0.0

                    if streamer_sym in greeks_map:
                        g = greeks_map[streamer_sym]
                        iv = self._clean_float(getattr(g, "volatility", 0.0))
                        delta = self._clean_float(getattr(g, "delta", 0.0))
                        gamma = self._clean_float(getattr(g, "gamma", 0.0))
                        theta = self._clean_float(getattr(g, "theta", 0.0))
                        vega = self._clean_float(getattr(g, "vega", 0.0))
                        rho = self._clean_float(getattr(g, "rho", 0.0))
                        last_price = self._clean_float(getattr(g, "price", 0.0))

                    results.append(
                        UnifiedOptionData(
                            symbol=root_sym,
                            strike=strike,
                            option_type=opt_type,
                            expiry=target_expiry,
                            bid=0.0,
                            ask=0.0,
                            last=last_price,
                            volume=0,
                            open_interest=0,
                            iv=iv,
                            delta=delta,
                            gamma=gamma,
                            theta=theta,
                            vega=vega,
                            rho=rho,
                            underlying_price=underlying_price,
                            multiplier=multiplier,
                            timestamp=now,
                            streamer_symbol=streamer_sym,
                            provider="tastytrade",
                            raw={
                                "symbol": getattr(opt, "symbol", ""),
                                "streamer_symbol": streamer_sym,
                                "root_symbol": getattr(opt, "root_symbol", ""),
                                "expiration_date": str(opt.expiration_date),
                            },
                        )
                    )
                except Exception as ex:
                    print(f"[Tastytrade] Warning: Skipped invalid option record: {ex}")
                    continue

            print(
                f"[Tastytrade] Successfully fetched {len(results)} option contracts "
                f"for {root_sym} (expiry: {target_expiry})."
            )
            return results

        except Exception as e:
            print(f"[Tastytrade] Error fetching option chain for '{tt_sym}': {e}")
            return []

    async def get_historical_candles(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles for a futures contract via Yahoo Finance.

        Parameters:
            symbol: Root or prefixed symbol (e.g. 'GC', '/GC', 'ES', 'NQ')
            period: Historical lookback (e.g. '1d', '5d', '30d', '60d', '1y')
            interval: Bar timeframe (e.g. '1m', '5m', '15m', '1h', '1d')

        Returns:
            pd.DataFrame with columns ['Open', 'High', 'Low', 'Close', 'Volume']
            and DatetimeIndex.
        """
        root_sym = self._normalize_root(symbol)
        yf_ticker = self._to_yfinance_symbol(root_sym)
        empty_df = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex([], name="Date"),
        )

        try:
            print(
                f"[Tastytrade] Fetching historical candles for {root_sym} "
                f"via yfinance ('{yf_ticker}', period={period}, interval={interval})..."
            )
            loop = asyncio.get_running_loop()

            def _fetch():
                ticker = yf.Ticker(yf_ticker)
                return ticker.history(period=period, interval=interval)

            df = await loop.run_in_executor(self._executor, _fetch)

            if df is None or df.empty:
                print(f"[Tastytrade] No candle data returned for {yf_ticker}.")
                return empty_df

            # Normalize column names
            required_cols = ["Open", "High", "Low", "Close", "Volume"]
            for col in required_cols:
                if col not in df.columns:
                    df[col] = 0.0

            df = df[required_cols].copy()
            # Clean index tz if present
            if getattr(df.index, "tz", None) is not None:
                df.index = df.index.tz_localize(None)

            df.sort_index(inplace=True)
            return df

        except Exception as e:
            print(f"[Tastytrade] Error fetching historical candles for '{root_sym}': {e}")
            return empty_df

    def get_supported_symbols(self) -> list[str]:
        """List of supported symbols for Tastytrade CME futures."""
        return list(self.SUPPORTED_SYMBOLS)

    def get_provider_name(self) -> str:
        """Human-readable provider name."""
        return "Tastytrade"

    def get_asset_class(self) -> AssetClass:
        """Asset class served by this adapter."""
        return AssetClass.FUTURES_OPTIONS

    # ── Optional Methods Overrides ───────────────────────

    async def get_expirations(self, symbol: str) -> list[date]:
        """
        List available expiration dates for a futures symbol.
        """
        if not await self._ensure_connected():
            return []

        tt_sym = self._to_tastytrade_symbol(symbol)
        try:
            chain = await get_future_option_chain(self._session, tt_sym)
            if not chain:
                return []
            return sorted(chain.keys())
        except Exception as e:
            print(f"[Tastytrade] Error fetching expirations for '{tt_sym}': {e}")
            return []

    async def get_strikes(self, symbol: str, expiry: date) -> list[float]:
        """
        List available strike prices for a given expiration date.
        """
        chain = await self.get_option_chain(symbol, expiry=expiry)
        return sorted(set(o.strike for o in chain))

    def get_capabilities(self) -> dict:
        """Describe adapter capabilities."""
        return {
            "provider": self.get_provider_name(),
            "asset_class": self.get_asset_class().value,
            "symbols": self.get_supported_symbols(),
            "options_chain": True,
            "greeks_included": True,
            "streaming": True,
            "historical": True,
        }

    # ── Helpers and Domain Logic ─────────────────────────

    async def _ensure_connected(self) -> bool:
        """Ensure adapter is connected, attempting auto-connection if needed."""
        if self._connected and self._session is not None:
            return True
        return await self.connect()

    def _normalize_root(self, symbol: str) -> str:
        """Normalize symbol to uppercase root without leading slash, e.g. 'GC'."""
        return symbol.strip().lstrip("/").upper()

    def _to_tastytrade_symbol(self, symbol: str) -> str:
        """Format symbol for Tastytrade API, e.g. '/GC', '/ES', '/NQ'."""
        root = self._normalize_root(symbol)
        return f"/{root}"

    def _to_yfinance_symbol(self, symbol: str) -> str:
        """Map symbol to Yahoo Finance ticker, e.g. 'GC=F'."""
        root = self._normalize_root(symbol)
        return self.YFINANCE_MAP.get(root, f"{root}=F")

    def _get_multiplier(self, symbol: str) -> float:
        """Get contract multiplier for given symbol."""
        root = self._normalize_root(symbol)
        return self.CONTRACT_MULTIPLIERS.get(root, 1.0)

    async def get_front_month_symbol(self, symbol: str) -> str:
        """
        Get the front-month contract symbol for a root code (e.g. '/GCJ26').
        """
        root = self._normalize_root(symbol)
        if root in self._cached_front_months:
            return self._cached_front_months[root]

        if not await self._ensure_connected():
            return ""

        try:
            if self._cached_futures is None:
                self._cached_futures = await Future.get(self._session)

            matches = sorted(
                [f for f in self._cached_futures if getattr(f, "product_code", "") == root],
                key=lambda f: getattr(f, "expiration_date", date.max),
            )
            if matches:
                front_sym = getattr(matches[0], "symbol", "")
                self._cached_front_months[root] = front_sym
                return front_sym
        except Exception as e:
            print(f"[Tastytrade] Warning: Could not resolve front-month future for {root}: {e}")

        return ""

    @staticmethod
    def infer_mark_price_from_chain(
        chain: dict[date, list[Any]],
        expiry_date: date,
        debug: bool = False,
    ) -> float:
        """
        Infer the futures mark price by finding the median strike of the option chain.
        Uses call-put parity proxy to estimate ATM futures price without requiring
        real-time market data subscription permissions.
        """
        if expiry_date not in chain:
            if debug:
                print(f"[Tastytrade debug] Expiry {expiry_date} not in chain.")
            return 0.0

        options = chain[expiry_date]
        if not options:
            return 0.0

        strikes: list[float] = []
        for opt in options:
            try:
                strike = float(opt.strike_price)
                strikes.append(strike)
            except (ValueError, AttributeError, TypeError):
                continue

        if not strikes:
            return 0.0

        strikes.sort()
        median_strike = strikes[len(strikes) // 2]
        if debug:
            print(
                f"[Tastytrade debug] Extracted {len(strikes)} strikes. "
                f"Median strike: {median_strike:.2f}"
            )

        return float(median_strike)

    @staticmethod
    def calc_sd_ranges(
        price: float,
        iv: float,
        dte: float,
        min_sd_dte_days: float = 1.0,
    ) -> dict[str, float]:
        """
        Calculate 1-sigma and 2-sigma expected moves using 365 calendar days
        (standard for CME 23-hour futures markets).
        """
        effective_dte = max(float(dte), float(min_sd_dte_days))
        sd1 = price * iv * math.sqrt(effective_dte / 365.0)
        prec = 4
        swing_p1_percent = (sd1 / price * 100.0) if price > 0 else 0.0

        try:
            swing_p1_prob = math.erfc(1.0 / math.sqrt(2.0)) * 100.0
        except Exception:
            swing_p1_prob = 31.73

        return {
            "1sd_upper": round(price + sd1, prec),
            "1sd_lower": round(price - sd1, prec),
            "2sd_upper": round(price + 2 * sd1, prec),
            "2sd_lower": round(price - 2 * sd1, prec),
            "sd1_move": round(sd1, prec),
            "swing_p1_percent": round(swing_p1_percent, 4),
            "swing_p1_prob_percent": round(swing_p1_prob, 2),
            "sd_dte_used": round(effective_dte, 4),
        }

    async def _fetch_greeks_for_options(
        self,
        options: list[Any],
        mark_price: float,
    ) -> dict[str, Any]:
        """
        Subscribe to DXLinkStreamer for Greeks events across options in the chain.
        """
        if not DXLinkStreamer or not Greeks or not self._session:
            return {}

        # If mark price is known, prioritize strikes within +/- 20% range for fast streaming
        if mark_price > 0:
            min_strike = mark_price * 0.80
            max_strike = mark_price * 1.20
            filtered = [
                o for o in options
                if min_strike <= float(getattr(o, "strike_price", 0)) <= max_strike
            ]
            target_options = filtered if filtered else options
        else:
            target_options = options

        streamer_symbols = [
            getattr(o, "streamer_symbol", "")
            for o in target_options
            if getattr(o, "streamer_symbol", "")
        ]

        if not streamer_symbols:
            return {}

        greeks_by_symbol: dict[str, Any] = {}
        try:
            print(f"[Tastytrade] Subscribing to DXLink streamer for {len(streamer_symbols)} symbols...")
            async with DXLinkStreamer(self._session) as streamer:
                await streamer.subscribe(Greeks, streamer_symbols)
                end_time = asyncio.get_event_loop().time() + self.greeks_timeout

                while asyncio.get_event_loop().time() < end_time:
                    try:
                        greeks = await asyncio.wait_for(
                            streamer.get_event(Greeks),
                            timeout=0.4,
                        )
                        if greeks and hasattr(greeks, "event_symbol") and greeks.event_symbol:
                            greeks_by_symbol[greeks.event_symbol] = greeks
                            if len(greeks_by_symbol) >= len(streamer_symbols):
                                break
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        continue

            print(f"[Tastytrade] Received Greeks for {len(greeks_by_symbol)} contracts.")
        except Exception as e:
            print(f"[Tastytrade] Warning: DXLink streamer error ({e}). Returning available data.")

        return greeks_by_symbol

    async def _fetch_yfinance_quote(self, root_sym: str) -> Optional[UnifiedFuturesData]:
        """Fetch current quote from Yahoo Finance."""
        yf_ticker = self._to_yfinance_symbol(root_sym)
        try:
            loop = asyncio.get_running_loop()

            def _get_yf():
                t = yf.Ticker(yf_ticker)
                h = t.history(period="1d", interval="1m")
                if h is None or h.empty:
                    h = t.history(period="5d", interval="1d")
                return h

            hist = await loop.run_in_executor(self._executor, _get_yf)
            if hist is not None and not hist.empty:
                last_row = hist.iloc[-1]
                price = float(last_row.get("Close", 0.0))
                high = float(last_row.get("High", 0.0))
                low = float(last_row.get("Low", 0.0))
                open_val = float(last_row.get("Open", 0.0))
                vol = int(last_row.get("Volume", 0))

                return UnifiedFuturesData(
                    symbol=root_sym,
                    price=price,
                    bid=price,
                    ask=price,
                    volume=vol,
                    high=high,
                    low=low,
                    open=open_val,
                    timestamp=datetime.now(),
                    provider="tastytrade",
                    raw={"source": "yfinance", "ticker": yf_ticker},
                )
        except Exception as e:
            print(f"[Tastytrade] Yahoo Finance quote fetch error for '{yf_ticker}': {e}")

        return None

    @staticmethod
    def _clean_float(val: Any) -> float:
        """Safely convert numeric value to float."""
        if val is None:
            return 0.0
        try:
            f = float(val)
            return 0.0 if math.isnan(f) else f
        except (ValueError, TypeError):
            return 0.0
