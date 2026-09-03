"""
Deribit Data Provider Adapter.

Deribit is a leading cryptocurrency derivatives exchange offering options and futures
for BTC, ETH, and other digital assets. This adapter connects to the 100% free public
Deribit API v2 (no authentication required) to provide normalized options chains,
Greeks, underlying futures prices, and historical candles.

API Reference:
    - Base URL: https://www.deribit.com/api/v2
    - Testnet URL: https://test.deribit.com/api/v2
    - Rate Limits: Credit-based (~10,000 credits/sec, ~10-200 req/sec)
    - Response Wrapper: {"jsonrpc": "2.0", "result": ...}

Key Endpoints Used:
    - GET /public/test: Healthcheck & latency check
    - GET /public/get_instruments: List active instruments & metadata
    - GET /public/get_book_summary_by_currency: Full option chain & market summaries
    - GET /public/ticker: Real-time instrument ticker & Greeks
    - GET /public/get_tradingview_chart_data: OHLCV candle history
    - GET /public/get_historical_volatility: Historical volatility index
    - GET /public/get_volatility_index_data: DVOL volatility index candles
    - GET /public/get_index_price: Spot index pricing
"""
import asyncio
from datetime import date, datetime, timezone
import math
from typing import Optional, Any
import aiohttp
import pandas as pd

from .base import BaseDataAdapter, UnifiedOptionData, UnifiedFuturesData, AssetClass
from .registry import AdapterRegistry


def parse_deribit_instrument_name(
    instrument_name: str,
) -> Optional[tuple[str, date, float, str]]:
    """
    Parse a standard Deribit option instrument name into components.

    Format: <CURRENCY>-<DDMMMYY>-<STRIKE>-<TYPE>
    Examples:
        - "BTC-27SEP26-100000-C" -> ("BTC", date(2026, 9, 27), 100000.0, "C")
        - "ETH-30OCT26-3200-P"   -> ("ETH", date(2026, 10, 30), 3200.0, "P")
        - "BTC-2SEP26-69000-C"   -> ("BTC", date(2026, 9, 2), 69000.0, "C")

    Returns:
        tuple of (symbol, expiry_date, strike, option_type) or None if invalid.
    """
    if not instrument_name or not isinstance(instrument_name, str):
        return None

    parts = instrument_name.strip().split("-")
    if len(parts) != 4:
        return None

    symbol = parts[0].upper()
    expiry_str = parts[1].upper()
    strike_str = parts[2]
    type_str = parts[3].upper()

    # Parse strike
    try:
        strike = float(strike_str)
    except (ValueError, TypeError):
        return None

    # Parse option type
    if type_str.startswith("C"):
        option_type = "C"
    elif type_str.startswith("P"):
        option_type = "P"
    else:
        return None

    # Parse expiry date (e.g., "27SEP26" or "2SEP26")
    try:
        expiry_date = datetime.strptime(expiry_str, "%d%b%y").date()
    except ValueError:
        try:
            expiry_date = datetime.strptime(expiry_str, "%d%b%Y").date()
        except ValueError:
            return None

    return symbol, expiry_date, strike, option_type


def _calc_black76_greeks(
    spot: float,
    strike: float,
    dte_days: float,
    iv: float,
    option_type: str,
    r: float = 0.0,
) -> dict[str, float]:
    """
    Fallback Black-76 Greeks calculation when provider does not supply them in book summary.

    Parameters:
        spot: Underlying futures price
        strike: Strike price
        dte_days: Days to expiration
        iv: Implied volatility in decimal (e.g. 0.40 for 40%)
        option_type: "C" or "P"
        r: Risk-free interest rate (default 0.0 for crypto futures options)

    Returns:
        dict with delta, gamma, vega, theta, rho
    """
    if spot <= 0 or strike <= 0 or dte_days <= 0 or iv <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}

    t = dte_days / 365.0
    discount = math.exp(-r * t)
    std_dev = iv * math.sqrt(t)
    if std_dev <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}

    d1 = (math.log(spot / strike) + 0.5 * (iv ** 2) * t) / std_dev
    d2 = d1 - std_dev

    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    cdf_d1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    cdf_minus_d1 = 0.5 * (1.0 + math.erf(-d1 / math.sqrt(2.0)))

    is_call = option_type.upper().startswith("C")
    delta = discount * cdf_d1 if is_call else -discount * cdf_minus_d1
    gamma = discount * pdf_d1 / (spot * std_dev)
    # Vega per 1% move in IV
    vega = discount * spot * math.sqrt(t) * pdf_d1 * 0.01
    # Theta per 1 day decay
    theta = -(spot * pdf_d1 * iv / (2.0 * math.sqrt(t))) / 365.0

    return {
        "delta": round(delta, 5),
        "gamma": round(gamma, 7),
        "vega": round(vega, 5),
        "theta": round(theta, 5),
        "rho": 0.0,
    }


@AdapterRegistry.register("deribit", env_keys=[])
class DeribitAdapter(BaseDataAdapter):
    """
    Deribit Crypto Options & Futures Data Adapter.

    Provides direct, asynchronous access to Deribit's public API v2.
    Supports BTC, ETH, and SOL options chains, Greeks, perpetual/futures market data,
    and historical OHLCV candles.

    No API key or authentication is required for public market data endpoints.
    """

    DEFAULT_BASE_URL = "https://www.deribit.com/api/v2"
    TESTNET_BASE_URL = "https://test.deribit.com/api/v2"
    SUPPORTED_SYMBOLS = ["BTC", "ETH", "SOL"]

    def __init__(
        self,
        testnet: bool = False,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
        session: Optional[aiohttp.ClientSession] = None,
        **kwargs,
    ):
        """
        Initialize the Deribit adapter.

        Args:
            testnet: If True, uses the Deribit testnet API URL.
            base_url: Custom API base URL (overrides default/testnet if provided).
            timeout: Request timeout in seconds (default: 15.0).
            session: Optional pre-existing aiohttp.ClientSession.
            **kwargs: Extra config stored in self._config.
        """
        super().__init__(testnet=testnet, base_url=base_url, timeout=timeout, **kwargs)
        self.testnet = bool(testnet or self._config.get("testnet", False))
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif self.testnet:
            self.base_url = self.TESTNET_BASE_URL
        else:
            self.base_url = self._config.get("base_url") or self.DEFAULT_BASE_URL
            self.base_url = self.base_url.rstrip("/")

        self._timeout_sec = float(timeout or self._config.get("timeout", 15.0))
        self._session: Optional[aiohttp.ClientSession] = session
        self._own_session: bool = session is None

    # ── Internal HTTP Helpers ─────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the active aiohttp ClientSession."""
        if self._session is None or self._session.closed:
            timeout_obj = aiohttp.ClientTimeout(total=self._timeout_sec)
            self._session = aiohttp.ClientSession(timeout=timeout_obj)
            self._own_session = True
        return self._session

    async def _request(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        Execute an async GET request to Deribit API v2 and unpack JSON-RPC response.

        Args:
            endpoint: API endpoint path (e.g., "/public/get_book_summary_by_currency")
            params: Query parameters dict

        Returns:
            The 'result' object from Deribit's JSON-RPC response, or None on error.
        """
        endpoint_clean = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.base_url}{endpoint_clean}"
        headers = {
            "User-Agent": "FuturesOptionsDashboard/1.0",
            "Accept": "application/json",
        }

        # Filter out None values in params
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        try:
            session = await self._get_session()
            async with session.get(url, params=clean_params, headers=headers) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    print(
                        f"[DeribitAdapter] HTTP {resp.status} error from {endpoint}: {err_body}"
                    )
                    return None

                data = await resp.json()
                if not isinstance(data, dict):
                    print(f"[DeribitAdapter] Unexpected response type from {endpoint}: {type(data)}")
                    return None

                if "error" in data and data["error"]:
                    err = data["error"]
                    print(
                        f"[DeribitAdapter] JSON-RPC error from {endpoint}: "
                        f"code={err.get('code')}, msg={err.get('message')}"
                    )
                    return None

                return data.get("result")

        except asyncio.TimeoutError:
            print(f"[DeribitAdapter] Timeout ({self._timeout_sec}s) querying {endpoint}")
            return None
        except aiohttp.ClientError as e:
            print(f"[DeribitAdapter] Network error querying {endpoint}: {e}")
            return None
        except Exception as e:
            print(f"[DeribitAdapter] Unexpected error querying {endpoint}: {e}")
            return None

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol string to Deribit currency format (e.g., 'BTC', 'ETH').
        """
        sym = symbol.strip().upper()
        if sym.startswith("/"):
            sym = sym[1:]
        if sym.startswith("BTC") or sym.startswith("XBT"):
            return "BTC"
        if sym.startswith("ETH"):
            return "ETH"
        if sym.startswith("SOL"):
            return "SOL"
        if sym.startswith("USDC"):
            return "USDC"
        if sym.startswith("XRP"):
            return "XRP"
        return sym

    # ── Required BaseDataAdapter Methods ──────────────────

    async def connect(self) -> bool:
        """
        Establish connection and validate public API connectivity.

        Endpoint: GET /public/test

        Returns:
            bool: True if connection is healthy, False otherwise.
        """
        try:
            session = await self._get_session()
            res = await self._request("/public/test")
            if res is not None:
                self._connected = True
                print(
                    f"[DeribitAdapter] Connected successfully to Deribit API "
                    f"({self.base_url}, version: {res.get('version', 'unknown')})"
                )
                return True
            else:
                self._connected = False
                print("[DeribitAdapter] Connection test failed: empty response.")
                return False
        except Exception as e:
            self._connected = False
            print(f"[DeribitAdapter] Connect error: {e}")
            return False

    async def disconnect(self) -> None:
        """Cleanup HTTP session resources and mark as disconnected."""
        if self._session and not self._session.closed and self._own_session:
            await self._session.close()
            self._session = None
        self._connected = False
        print("[DeribitAdapter] Disconnected from Deribit API.")

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """
        Fetch full option chain with Greeks and volatility metrics for a cryptocurrency.

        Endpoint: GET /public/get_book_summary_by_currency?currency={curr}&kind=option

        Mapping to UnifiedOptionData:
            - symbol: Root currency ('BTC' or 'ETH')
            - strike: Strike price parsed from contract name
            - option_type: 'C' (Call) or 'P' (Put)
            - expiry: Contract expiration date
            - iv: Mark IV normalized to decimal (mark_iv / 100.0)
            - delta, gamma, theta, vega: Extracted from 'greeks' dict or Black-76 model
            - bid, ask, last: Normalized bid/ask/last prices
            - volume: 24h contract volume
            - open_interest: Total open interest
            - underlying_price: Spot index / underlying futures price
            - multiplier: 1.0 (crypto contracts represent 1 coin unit)

        Args:
            symbol: Root asset symbol ('BTC', 'ETH', etc.)
            expiry: Optional specific expiration date to filter by.

        Returns:
            list[UnifiedOptionData]: List of normalized option contracts.
        """
        curr = self._normalize_symbol(symbol)
        params = {"currency": curr, "kind": "option"}

        raw_items = await self._request("/public/get_book_summary_by_currency", params=params)
        if not raw_items or not isinstance(raw_items, list):
            print(f"[DeribitAdapter] No option contracts returned for currency {curr}")
            return []

        options: list[UnifiedOptionData] = []
        today = date.today()

        for item in raw_items:
            instrument_name = item.get("instrument_name", "")
            parsed = parse_deribit_instrument_name(instrument_name)
            if not parsed:
                continue

            item_sym, item_expiry, strike, opt_type = parsed

            # Filter by expiration date if specified
            if expiry is not None and item_expiry != expiry:
                continue

            # Core pricing fields
            bid = float(item.get("bid_price") or 0.0)
            ask = float(item.get("ask_price") or 0.0)
            last = float(item.get("last") or 0.0)
            volume = int(float(item.get("volume") or 0.0))
            open_interest = int(float(item.get("open_interest") or 0.0))

            # Implied Volatility: Deribit returns mark_iv as percentage (e.g. 41.2 -> 0.412)
            mark_iv = float(item.get("mark_iv") or 0.0)
            iv = mark_iv / 100.0 if mark_iv > 0 else 0.0

            underlying_price = float(item.get("underlying_price") or 0.0)

            # Greeks extraction
            greeks = item.get("greeks") or {}
            delta = float(greeks.get("delta") or 0.0)
            gamma = float(greeks.get("gamma") or 0.0)
            theta = float(greeks.get("theta") or 0.0)
            vega = float(greeks.get("vega") or 0.0)
            rho = float(greeks.get("rho") or 0.0)

            # Calculate Black-76 Greeks fallback if summary did not contain non-zero Greeks
            if delta == 0.0 and gamma == 0.0 and iv > 0 and underlying_price > 0:
                dte_days = max(1.0, float((item_expiry - today).days))
                calc_greeks = _calc_black76_greeks(
                    spot=underlying_price,
                    strike=strike,
                    dte_days=dte_days,
                    iv=iv,
                    option_type=opt_type,
                    r=0.0,
                )
                delta = calc_greeks["delta"]
                gamma = calc_greeks["gamma"]
                vega = calc_greeks["vega"]
                theta = calc_greeks["theta"]
                rho = calc_greeks["rho"]

            # Creation timestamp
            ts_ms = item.get("creation_timestamp")
            dt_stamp = (
                datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                if ts_ms
                else None
            )

            option_obj = UnifiedOptionData(
                symbol=item_sym,
                strike=strike,
                option_type=opt_type,
                expiry=item_expiry,
                bid=bid,
                ask=ask,
                last=last,
                volume=volume,
                open_interest=open_interest,
                iv=iv,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
                rho=rho,
                underlying_price=underlying_price,
                multiplier=1.0,
                timestamp=dt_stamp,
                streamer_symbol=instrument_name,
                provider="deribit",
                raw=item,
            )
            options.append(option_obj)

        # Sort cleanly by expiration, strike, and call/put
        options.sort(key=lambda o: (o.expiry, o.strike, o.option_type))
        return options

    async def get_futures_price(self, symbol: str) -> UnifiedFuturesData:
        """
        Fetch current market price, quotes, and 24h stats for underlying futures/perpetual.

        Endpoint: GET /public/ticker?instrument_name={CURR}-PERPETUAL

        Args:
            symbol: Symbol name (e.g., 'BTC', 'ETH', or 'BTC-PERPETUAL').

        Returns:
            UnifiedFuturesData: Normalized underlying price and volume metrics.
        """
        curr = self._normalize_symbol(symbol)
        instrument_name = symbol if "-" in symbol else f"{curr}-PERPETUAL"

        ticker_data = await self._request(
            "/public/ticker", params={"instrument_name": instrument_name}
        )

        if not ticker_data or not isinstance(ticker_data, dict):
            # Fallback to index price endpoint if perpetual ticker is unavailable
            print(
                f"[DeribitAdapter] Perpetual ticker failed for {instrument_name}, "
                f"trying index price fallback."
            )
            index_data = await self._request(
                "/public/get_index_price", params={"index_name": f"{curr.lower()}_usd"}
            )
            idx_price = float(
                (index_data or {}).get("index_price") or 0.0
            ) if isinstance(index_data, dict) else 0.0

            return UnifiedFuturesData(
                symbol=curr,
                price=idx_price,
                bid=idx_price,
                ask=idx_price,
                provider="deribit",
                raw=index_data if isinstance(index_data, dict) else {},
            )

        # Parse ticker fields
        last_price = float(
            ticker_data.get("last_price")
            or ticker_data.get("mark_price")
            or ticker_data.get("index_price")
            or 0.0
        )
        bid = float(ticker_data.get("best_bid_price") or 0.0)
        ask = float(ticker_data.get("best_ask_price") or 0.0)
        open_interest = int(float(ticker_data.get("open_interest") or 0.0))

        stats = ticker_data.get("stats") or {}
        high = float(stats.get("high") or 0.0)
        low = float(stats.get("low") or 0.0)
        change_pct = float(stats.get("price_change") or 0.0)
        volume = int(float(stats.get("volume_usd") or stats.get("volume") or 0.0))

        # Calculate implied open price from 24h change percentage
        open_price = (
            last_price / (1.0 + (change_pct / 100.0))
            if change_pct != -100.0 and last_price > 0
            else 0.0
        )
        change = (last_price - open_price) if open_price > 0 else 0.0

        ts_ms = ticker_data.get("timestamp")
        dt_stamp = (
            datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            if ts_ms
            else None
        )

        return UnifiedFuturesData(
            symbol=curr,
            price=last_price,
            bid=bid,
            ask=ask,
            volume=volume,
            open_interest=open_interest,
            high=high,
            low=low,
            open=round(open_price, 2),
            change=round(change, 2),
            change_pct=change_pct,
            timestamp=dt_stamp,
            provider="deribit",
            raw=ticker_data,
        )

    async def get_historical_candles(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candle history for the underlying instrument.

        Endpoint: GET /public/get_tradingview_chart_data

        Args:
            symbol: Asset symbol ('BTC', 'ETH', etc.) or exact instrument name.
            period: Lookback window ('1d', '7d', '30d', '90d', '1y', etc.).
            interval: Resolution ('1m', '5m', '15m', '30m', '1h', '2h', '1d', '1D').

        Returns:
            pd.DataFrame: OHLCV DataFrame with DatetimeIndex and columns:
                          ['Open', 'High', 'Low', 'Close', 'Volume'].
        """
        curr = self._normalize_symbol(symbol)
        instrument_name = symbol if "-" in symbol else f"{curr}-PERPETUAL"

        # Calculate time range in milliseconds
        now_utc = datetime.now(timezone.utc)
        end_ts = int(now_utc.timestamp() * 1000)

        period_lower = period.lower().strip()
        if period_lower.endswith("d"):
            days = float(period_lower[:-1])
            duration_ms = int(days * 86400 * 1000)
        elif period_lower.endswith("w"):
            weeks = float(period_lower[:-1])
            duration_ms = int(weeks * 7 * 86400 * 1000)
        elif period_lower.endswith("y"):
            years = float(period_lower[:-1])
            duration_ms = int(years * 365 * 86400 * 1000)
        elif period_lower.endswith("h"):
            hours = float(period_lower[:-1])
            duration_ms = int(hours * 3600 * 1000)
        else:
            duration_ms = int(30 * 86400 * 1000)

        start_ts = max(0, end_ts - duration_ms)

        # Resolution mapping for Deribit TradingView endpoint
        # Supported Deribit values: '1', '3', '5', '10', '15', '30', '60', '120', '180', '360', '720', '1D'
        interval_norm = interval.lower().strip()
        resolution_map = {
            "1m": "1",
            "1": "1",
            "3m": "3",
            "3": "3",
            "5m": "5",
            "5": "5",
            "10m": "10",
            "10": "10",
            "15m": "15",
            "15": "15",
            "30m": "30",
            "30": "30",
            "1h": "60",
            "60m": "60",
            "60": "60",
            "2h": "120",
            "120m": "120",
            "3h": "180",
            "6h": "360",
            "12h": "720",
            "1d": "1D",
            "d": "1D",
            "1D": "1D",
            "D": "1D",
        }
        resolution = resolution_map.get(interval_norm, "1D")

        params = {
            "instrument_name": instrument_name,
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "resolution": resolution,
        }

        data = await self._request("/public/get_tradingview_chart_data", params=params)
        cols = ["Open", "High", "Low", "Close", "Volume"]

        if not data or not isinstance(data, dict):
            print(f"[DeribitAdapter] No candle data found for {instrument_name}")
            return pd.DataFrame(columns=cols)

        ticks = data.get("ticks") or []
        opens = data.get("open") or []
        highs = data.get("high") or []
        lows = data.get("low") or []
        closes = data.get("close") or []
        volumes = data.get("volume") or []

        if not ticks or len(ticks) == 0:
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(
            {
                "Open": opens,
                "High": highs,
                "Low": lows,
                "Close": closes,
                "Volume": volumes,
            },
            index=pd.to_datetime(ticks, unit="ms", utc=True),
        )
        df.index.name = "Date"
        df.sort_index(inplace=True)
        return df

    def get_supported_symbols(self) -> list[str]:
        """List of supported asset symbols."""
        return list(self.SUPPORTED_SYMBOLS)

    def get_provider_name(self) -> str:
        """Human-readable provider name."""
        return "Deribit"

    def get_asset_class(self) -> AssetClass:
        """Instrument category served by this adapter."""
        return AssetClass.CRYPTO_OPTIONS

    # ── Additional Deribit-Specific Public Methods ─────────

    async def get_instruments(
        self,
        symbol: str = "BTC",
        kind: str = "option",
        expired: bool = False,
    ) -> list[dict]:
        """
        Fetch full active instrument specifications from Deribit.

        Endpoint: GET /public/get_instruments?currency={curr}&kind={kind}&expired={expired}

        Args:
            symbol: Asset symbol ('BTC', 'ETH', 'SOL').
            kind: 'option', 'future', or 'spot'.
            expired: Whether to include expired instruments.

        Returns:
            list[dict]: List of contract specification dictionaries.
        """
        curr = self._normalize_symbol(symbol)
        params = {
            "currency": curr,
            "kind": kind,
            "expired": "true" if expired else "false",
        }
        res = await self._request("/public/get_instruments", params=params)
        return res if isinstance(res, list) else []

    async def get_ticker(self, instrument_name: str) -> dict:
        """
        Fetch full real-time ticker data with order book depths and Greeks for a single contract.

        Endpoint: GET /public/ticker?instrument_name={name}

        Args:
            instrument_name: Contract name (e.g. 'BTC-27SEP26-100000-C')

        Returns:
            dict: Raw ticker dictionary.
        """
        res = await self._request(
            "/public/ticker", params={"instrument_name": instrument_name}
        )
        return res if isinstance(res, dict) else {}

    async def get_historical_volatility(self, symbol: str = "BTC") -> list[dict]:
        """
        Fetch Deribit historical volatility index time series.

        Endpoint: GET /public/get_historical_volatility?currency={curr}

        Args:
            symbol: Asset symbol ('BTC' or 'ETH').

        Returns:
            list[dict]: List of timestamp and volatility points.
        """
        curr = self._normalize_symbol(symbol)
        res = await self._request(
            "/public/get_historical_volatility", params={"currency": curr}
        )
        if not res or not isinstance(res, list):
            return []
        return [
            {
                "timestamp": datetime.fromtimestamp(item[0] / 1000.0, tz=timezone.utc),
                "volatility": item[1],
            }
            for item in res
            if isinstance(item, (list, tuple)) and len(item) >= 2
        ]

    async def get_dvol_index(
        self,
        symbol: str = "BTC",
        period: str = "30d",
        resolution: str = "1D",
    ) -> pd.DataFrame:
        """
        Fetch Deribit DVOL (Crypto VIX) volatility index OHLC candles.

        Endpoint: GET /public/get_volatility_index_data

        Args:
            symbol: Asset symbol ('BTC' or 'ETH').
            period: Lookback window ('30d', '90d', '1y').
            resolution: '1D' or intraday resolution.

        Returns:
            pd.DataFrame: DVOL OHLC DataFrame with DatetimeIndex.
        """
        curr = self._normalize_symbol(symbol)
        now_utc = datetime.now(timezone.utc)
        end_ts = int(now_utc.timestamp() * 1000)
        days = 30
        if period.lower().endswith("d"):
            try:
                days = int(period[:-1])
            except ValueError:
                days = 30
        start_ts = end_ts - int(days * 86400 * 1000)

        params = {
            "currency": curr,
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "resolution": resolution,
        }
        res = await self._request("/public/get_volatility_index_data", params=params)
        cols = ["Open", "High", "Low", "Close"]
        if not res or not isinstance(res, dict):
            return pd.DataFrame(columns=cols)

        data_rows = res.get("data") or []
        if not data_rows:
            return pd.DataFrame(columns=cols)

        timestamps = [r[0] for r in data_rows]
        opens = [r[1] for r in data_rows]
        highs = [r[2] for r in data_rows]
        lows = [r[3] for r in data_rows]
        closes = [r[4] for r in data_rows]

        df = pd.DataFrame(
            {"Open": opens, "High": highs, "Low": lows, "Close": closes},
            index=pd.to_datetime(timestamps, unit="ms", utc=True),
        )
        df.index.name = "Date"
        df.sort_index(inplace=True)
        return df

    def get_capabilities(self) -> dict:
        """Describe Deribit adapter capabilities."""
        return {
            "provider": self.get_provider_name(),
            "asset_class": self.get_asset_class().value,
            "symbols": self.get_supported_symbols(),
            "options_chain": True,
            "greeks_included": True,
            "streaming": False,
            "historical": True,
            "free_tier": True,
            "auth_required": False,
        }
