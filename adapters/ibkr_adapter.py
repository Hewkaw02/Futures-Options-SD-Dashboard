"""
Interactive Brokers (IBKR) Data Provider Adapter.

Connects to Interactive Brokers TWS (Trader Workstation) or IB Gateway via
the `ib_insync` library to stream and fetch CME / COMEX / NYMEX / CBOT
futures and futures options data, including real-time prices, option chains,
model Greeks, and historical OHLCV candlesticks.

Prerequisites & Architecture:
- Requires TWS or IB Gateway running locally or on an accessible host.
- TWS/Gateway must have API connections enabled:
    Global Configuration -> API -> Settings -> "Enable ActiveX and Socket Clients"
- Default Socket Ports:
    * TWS Paper Trading:      7497
    * TWS Live Trading:       7496
    * IB Gateway Paper:       4002
    * IB Gateway Live:        4001
- Environment Variables:
    * IBKR_HOST: Host IP (default: "127.0.0.1")
    * IBKR_PORT: Port number (default: 7497)
    * IBKR_CLIENT_ID: Client ID integer (default: 1)

Key Features & Limitations:
- Asset Class: AssetClass.FUTURES_OPTIONS
- Contract Multipliers: GC=100, ES=50, NQ=20, CL=1000, SI=5000, etc.
- Greeks: Fetched via genericTickList='100,101,104,106' (IV, Delta, Gamma, Theta, Vega, Rho).
- Rate Limits: 50 messages/second, 60 historical requests / 10 minutes.
- Open Interest: In TWS API, real-time OI for futures options may have limitations or delays
  depending on market data subscriptions.

API References:
- ib_insync: https://ib-insync.readthedocs.io/
- Interactive Brokers TWS API: https://interactivebrokers.github.io/tws-api/
"""

import asyncio
import math
import os
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from .base import AssetClass, BaseDataAdapter, UnifiedFuturesData, UnifiedOptionData
from .registry import AdapterRegistry

# Graceful import of ib_insync to avoid crashes if not installed
try:
    from ib_insync import IB, Contract, ContractDetails, Future, FuturesOption, OptionChain, util
    IB_INSYNC_AVAILABLE = True
except ImportError:
    IB = None
    Contract = None
    ContractDetails = None
    Future = None
    FuturesOption = None
    OptionChain = None
    util = None
    IB_INSYNC_AVAILABLE = False


@AdapterRegistry.register("ibkr", env_keys=["IBKR_HOST", "IBKR_PORT", "IBKR_CLIENT_ID"])
class IBKRAdapter(BaseDataAdapter):
    """
    Interactive Brokers Data Adapter for CME Futures and Futures Options.
    Uses ib_insync socket communication with local TWS / IB Gateway.
    """

    # Contract multipliers for notional value & GEX calculations
    CONTRACT_MULTIPLIERS: dict[str, float] = {
        "GC": 100.0,    # Gold: 100 troy oz
        "ES": 50.0,     # E-mini S&P 500: $50 x index
        "NQ": 20.0,     # E-mini Nasdaq-100: $20 x index
        "CL": 1000.0,   # Crude Oil: 1,000 barrels
        "SI": 5000.0,   # Silver: 5,000 troy oz
        "ZB": 1000.0,   # 30-Year U.S. Treasury Bond
        "ZN": 1000.0,   # 10-Year U.S. Treasury Note
        "ZF": 1000.0,   # 5-Year U.S. Treasury Note
        "ZT": 2000.0,   # 2-Year U.S. Treasury Note
        "ZC": 5000.0,   # Corn: 5,000 bushels
        "ZS": 5000.0,   # Soybeans: 5,000 bushels
        "ZW": 5000.0,   # Wheat: 5,000 bushels
        "ZM": 100.0,    # Soybean Meal: 100 short tons
        "ZL": 60000.0,  # Soybean Oil: 60,000 lbs
        "YM": 5.0,      # E-mini Dow: $5 x index
        "RTY": 50.0,    # E-mini Russell 2000: $50 x index
        "HG": 25000.0,  # Copper: 25,000 lbs
        "NG": 10000.0,  # Natural Gas: 10,000 MMBtu
        "6E": 125000.0, # Euro FX: 125,000 EUR
        "6B": 62500.0,  # British Pound: 62,500 GBP
        "6J": 12500000.0, # Japanese Yen: 12,500,000 JPY
        "6A": 100000.0, # Australian Dollar: 100,000 AUD
        "6C": 100000.0, # Canadian Dollar: 100,000 CAD
    }

    # Exchange routing for CME Group commodities & indices
    SYMBOL_EXCHANGE_MAP: dict[str, str] = {
        "GC": "COMEX",
        "SI": "COMEX",
        "HG": "COMEX",
        "ES": "CME",
        "NQ": "CME",
        "RTY": "CME",
        "6E": "CME",
        "6B": "CME",
        "6J": "CME",
        "6A": "CME",
        "6C": "CME",
        "CL": "NYMEX",
        "NG": "NYMEX",
        "ZB": "CBOT",
        "ZN": "CBOT",
        "ZF": "CBOT",
        "ZT": "CBOT",
        "ZC": "CBOT",
        "ZS": "CBOT",
        "ZW": "CBOT",
        "ZM": "CBOT",
        "ZL": "CBOT",
        "YM": "CBOT",
    }

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int | str] = None,
        client_id: Optional[int | str] = None,
        timeout: float = 15.0,
        **kwargs,
    ):
        """
        Initialize the IBKR adapter with host, port, and client ID.

        Parameters:
            host: IP address of TWS / IB Gateway (default: IBKR_HOST or '127.0.0.1')
            port: Port for TWS / IB Gateway socket (default: IBKR_PORT or 7497)
            client_id: Unique client identifier (default: IBKR_CLIENT_ID or 1)
            timeout: Connection timeout in seconds (default: 15.0)
        """
        super().__init__(**kwargs)
        self.host = host or os.getenv("IBKR_HOST", "127.0.0.1")

        raw_port = port or os.getenv("IBKR_PORT", 7497)
        try:
            self.port = int(raw_port)
        except (ValueError, TypeError):
            self.port = 7497

        raw_client_id = client_id or os.getenv("IBKR_CLIENT_ID", 1)
        try:
            self.client_id = int(raw_client_id)
        except (ValueError, TypeError):
            self.client_id = 1

        self.timeout = float(timeout)
        self._ib: Optional[Any] = None

    # ── Required Methods Implementation ──────────────────

    async def connect(self) -> bool:
        """
        Establish socket connection to local TWS or IB Gateway.

        Validates ib_insync availability and handles connection errors with
        clear troubleshooting guidance.
        """
        if not IB_INSYNC_AVAILABLE:
            print(
                "[IBKR] Error: 'ib_insync' package is not installed.\n"
                "       Please install it using: pip install ib_insync"
            )
            self._connected = False
            return False

        if self._ib is not None and self._ib.isConnected():
            self._connected = True
            return True

        try:
            print(
                f"[IBKR] Connecting to TWS/Gateway at {self.host}:{self.port} "
                f"(clientId={self.client_id})..."
            )
            if self._ib is None:
                self._ib = IB()

            await self._ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=self.timeout,
            )

            if self._ib.isConnected():
                self._connected = True
                print(
                    f"[IBKR] Successfully connected to TWS/IB Gateway "
                    f"({self.host}:{self.port}, clientId={self.client_id})."
                )
                return True
            else:
                self._connected = False
                print(f"[IBKR] Failed to connect to TWS/IB Gateway at {self.host}:{self.port}.")
                return False

        except ConnectionRefusedError:
            self._connected = False
            print(
                f"[IBKR] Connection refused at {self.host}:{self.port}.\n"
                "       Troubleshooting steps:\n"
                "       1. Ensure TWS or IB Gateway is running.\n"
                "       2. Verify API settings in TWS/Gateway: Configuration -> API -> Settings:\n"
                "          - Check 'Enable ActiveX and Socket Clients'\n"
                f"          - Verify Socket Port matches {self.port} "
                "            (Paper: 7497 TWS / 4002 Gateway, Live: 7496 TWS / 4001 Gateway)\n"
                "          - Ensure 127.0.0.1 is in Trusted IP list."
            )
            return False
        except asyncio.TimeoutError:
            self._connected = False
            print(
                f"[IBKR] Connection timed out after {self.timeout}s attempting to reach "
                f"{self.host}:{self.port}."
            )
            return False
        except Exception as e:
            self._connected = False
            print(f"[IBKR] Connection error: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect socket connection to TWS / IB Gateway."""
        if self._ib is not None:
            try:
                if self._ib.isConnected():
                    self._ib.disconnect()
            except Exception as e:
                print(f"[IBKR] Error during disconnect: {e}")
        self._connected = False
        print("[IBKR] Disconnected from TWS/IB Gateway.")

    async def get_futures_price(self, symbol: str) -> UnifiedFuturesData:
        """
        Fetch current market price and quote data for the underlying futures contract.

        Parameters:
            symbol: Root symbol (e.g. 'GC', 'ES', 'NQ')

        Returns:
            UnifiedFuturesData dataclass with price, bid, ask, volume, and OHLC data.
        """
        if not await self._ensure_connected():
            return UnifiedFuturesData(
                symbol=symbol.upper(),
                price=0.0,
                provider="ibkr",
                raw={"error": "Not connected to IBKR / TWS"},
            )

        sym = symbol.upper()
        try:
            front_contract = await self._get_front_future(sym)
            if not front_contract:
                print(f"[IBKR] Could not resolve front-month futures contract for '{sym}'.")
                return UnifiedFuturesData(
                    symbol=sym,
                    price=0.0,
                    provider="ibkr",
                    raw={"error": f"Contract not found for {sym}"},
                )

            # Request market data ticker
            ticker = self._ib.reqMktData(
                front_contract,
                genericTickList="100,101",
                snapshot=False,
                regulatorySnapshot=False,
            )

            # Wait briefly for market data to populate
            for _ in range(20):
                await self._ib.sleep(0.1)
                if (
                    ticker.last is not None
                    and not math.isnan(ticker.last)
                    and ticker.last > 0
                ):
                    break
                if (
                    ticker.bid is not None
                    and ticker.ask is not None
                    and ticker.bid > 0
                    and ticker.ask > 0
                ):
                    break

            self._ib.cancelMktData(front_contract)

            bid = self._clean_float(ticker.bid)
            ask = self._clean_float(ticker.ask)
            last = self._clean_float(ticker.last)
            close = self._clean_float(ticker.close)
            high = self._clean_float(ticker.high)
            low = self._clean_float(ticker.low)
            open_price = self._clean_float(ticker.open)
            volume = self._clean_int(ticker.volume)
            oi = self._clean_int(
                getattr(ticker, "openInterest", 0)
                or getattr(ticker, "callOpenInterest", 0)
                or getattr(ticker, "putOpenInterest", 0)
            )

            # Determine best price estimate
            price = last
            if price <= 0.0:
                if bid > 0.0 and ask > 0.0:
                    price = (bid + ask) / 2.0
                elif close > 0.0:
                    price = close
                elif (
                    hasattr(ticker, "markPrice")
                    and ticker.markPrice is not None
                    and not math.isnan(ticker.markPrice)
                    and ticker.markPrice > 0
                ):
                    price = float(ticker.markPrice)

            change = 0.0
            change_pct = 0.0
            if close > 0.0 and price > 0.0:
                change = price - close
                change_pct = (change / close) * 100.0

            ts = (
                ticker.time
                if hasattr(ticker, "time") and ticker.time
                else datetime.now()
            )

            return UnifiedFuturesData(
                symbol=sym,
                price=price,
                bid=bid,
                ask=ask,
                volume=volume,
                open_interest=oi,
                high=high,
                low=low,
                open=open_price,
                change=change,
                change_pct=change_pct,
                timestamp=ts,
                provider="ibkr",
                raw={
                    "conId": front_contract.conId,
                    "localSymbol": front_contract.localSymbol,
                    "exchange": front_contract.exchange,
                    "expiry": front_contract.lastTradeDateOrContractMonth,
                    "close": close,
                },
            )

        except Exception as e:
            print(f"[IBKR] Error fetching futures price for '{sym}': {e}")
            return UnifiedFuturesData(
                symbol=sym,
                price=0.0,
                provider="ibkr",
                raw={"error": str(e)},
            )

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """
        Fetch full option chain for a symbol with Greeks and quotes.

        If expiry is None, returns options for the nearest active expiration date.
        Requests Greeks via genericTickList='100,101,104,106'.

        Parameters:
            symbol: Root symbol (e.g. 'GC', 'ES', 'NQ')
            expiry: Optional expiration date to filter. If None, uses nearest.

        Returns:
            List of UnifiedOptionData contracts.
        """
        if not await self._ensure_connected():
            return []

        sym = symbol.upper()
        multiplier = self._get_multiplier(sym)

        try:
            # 1. Resolve underlying front contract
            front_contract = await self._get_front_future(sym)
            if not front_contract or not front_contract.conId:
                print(f"[IBKR] Could not resolve underlying contract for '{sym}'.")
                return []

            # 2. Get underlying price
            underlying_data = await self.get_futures_price(sym)
            underlying_price = underlying_data.price

            # 3. Request Security Definition Option Parameters
            chains = await self._ib.reqSecDefOptParamsAsync(
                underlyingSymbol=sym,
                futFopExchange="",
                underlyingSecType="FUT",
                underlyingConId=front_contract.conId,
            )

            if not chains:
                print(f"[IBKR] No option chains returned for {sym} (conId: {front_contract.conId}).")
                return []

            # 4. Resolve expiration date
            today = date.today()
            available_expiries: dict[str, date] = {}

            for ch in chains:
                for exp_str in ch.expirations:
                    try:
                        exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
                        if exp_date >= today:
                            available_expiries[exp_str] = exp_date
                    except ValueError:
                        pass

            # Fallback if all dates are in the past or date formatting differs
            if not available_expiries:
                for ch in chains:
                    for exp_str in ch.expirations:
                        try:
                            available_expiries[exp_str] = datetime.strptime(exp_str, "%Y%m%d").date()
                        except ValueError:
                            pass

            if not available_expiries:
                print(f"[IBKR] No valid expiration dates found for {sym}.")
                return []

            target_exp_str: str = ""
            target_exp_date: date = today

            if expiry is not None:
                exp_str_req = expiry.strftime("%Y%m%d")
                if exp_str_req in available_expiries:
                    target_exp_str = exp_str_req
                    target_exp_date = expiry
                else:
                    sorted_expiries = sorted(
                        available_expiries.items(),
                        key=lambda x: abs((x[1] - expiry).days),
                    )
                    target_exp_str, target_exp_date = sorted_expiries[0]
                    print(
                        f"[IBKR] Requested expiry {expiry} not found. "
                        f"Using nearest available: {target_exp_date}"
                    )
            else:
                # Nearest expiration date
                sorted_expiries = sorted(available_expiries.items(), key=lambda x: x[1])
                target_exp_str, target_exp_date = sorted_expiries[0]

            # 5. Build list of FuturesOption contracts
            contracts_to_query: list[tuple[Any, str, float, str]] = []

            for ch in chains:
                if target_exp_str not in ch.expirations:
                    continue
                chain_mult = float(ch.multiplier) if ch.multiplier else multiplier
                for strike in sorted(ch.strikes):
                    for right in ["C", "P"]:
                        opt = FuturesOption(
                            symbol=sym,
                            strike=strike,
                            right=right,
                            exchange=ch.exchange,
                            expiry=target_exp_str,
                            multiplier=(
                                str(int(chain_mult))
                                if chain_mult.is_integer()
                                else str(chain_mult)
                            ),
                            currency="USD",
                        )
                        contracts_to_query.append((opt, ch.exchange, strike, right))

            if not contracts_to_query:
                print(f"[IBKR] No contracts generated for {sym} expiry {target_exp_str}.")
                return []

            print(
                f"[IBKR] Requesting market data & Greeks for {len(contracts_to_query)} "
                f"contracts ({sym} {target_exp_str})..."
            )

            # 6. Query market data in batches to respect 50 msg/sec rate limit
            # and manage simultaneous market data subscription limits
            results: list[UnifiedOptionData] = []
            batch_size = 40

            for i in range(0, len(contracts_to_query), batch_size):
                batch = contracts_to_query[i : i + batch_size]
                active_tickers: list[tuple[Any, Any, str, float, str]] = []

                for opt_contract, exchange, strike, right in batch:
                    ticker = self._ib.reqMktData(
                        opt_contract,
                        genericTickList="100,101,104,106",
                        snapshot=False,
                        regulatorySnapshot=False,
                    )
                    active_tickers.append((ticker, opt_contract, exchange, strike, right))

                # Allow TWS to return market data ticks and Greeks
                await self._ib.sleep(1.2)

                for ticker, opt_contract, exchange, strike, right in active_tickers:
                    self._ib.cancelMktData(opt_contract)

                    bid = self._clean_float(ticker.bid)
                    ask = self._clean_float(ticker.ask)
                    last = self._clean_float(ticker.last)
                    vol = self._clean_int(ticker.volume)
                    oi = self._clean_int(
                        getattr(ticker, "openInterest", 0)
                        or getattr(ticker, "callOpenInterest", 0)
                        or getattr(ticker, "putOpenInterest", 0)
                    )

                    # Extract Greeks from modelGreeks or fallback Greek computations
                    greeks = (
                        getattr(ticker, "modelGreeks", None)
                        or getattr(ticker, "lastGreeks", None)
                        or getattr(ticker, "bidGreeks", None)
                        or getattr(ticker, "askGreeks", None)
                    )

                    iv = 0.0
                    delta = 0.0
                    gamma = 0.0
                    theta = 0.0
                    vega = 0.0
                    rho = 0.0
                    und_price = underlying_price

                    if greeks is not None:
                        iv = self._clean_greek(getattr(greeks, "impliedVol", 0.0))
                        delta = self._clean_greek(getattr(greeks, "delta", 0.0))
                        gamma = self._clean_greek(getattr(greeks, "gamma", 0.0))
                        theta = self._clean_greek(getattr(greeks, "theta", 0.0))
                        vega = self._clean_greek(getattr(greeks, "vega", 0.0))
                        rho = self._clean_greek(getattr(greeks, "rho", 0.0))
                        greeks_und = getattr(greeks, "undPrice", None)
                        if (
                            greeks_und is not None
                            and not math.isnan(greeks_und)
                            and greeks_und > 0
                        ):
                            und_price = float(greeks_und)

                    if (
                        iv == 0.0
                        and hasattr(ticker, "impliedVolatility")
                        and ticker.impliedVolatility
                    ):
                        iv = self._clean_greek(ticker.impliedVolatility)

                    opt_data = UnifiedOptionData(
                        symbol=sym,
                        strike=strike,
                        option_type=right,
                        expiry=target_exp_date,
                        bid=bid,
                        ask=ask,
                        last=last,
                        volume=vol,
                        open_interest=oi,
                        iv=iv,
                        delta=delta,
                        gamma=gamma,
                        theta=theta,
                        vega=vega,
                        rho=rho,
                        underlying_price=und_price,
                        multiplier=multiplier,
                        timestamp=datetime.now(),
                        streamer_symbol=f"{sym}_{strike}_{right}_{target_exp_str}",
                        provider="ibkr",
                        raw={
                            "exchange": exchange,
                            "expiry": target_exp_str,
                            "conId": getattr(ticker.contract, "conId", 0),
                        },
                    )
                    results.append(opt_data)

                # Pacing delay between batches
                if i + batch_size < len(contracts_to_query):
                    await self._ib.sleep(0.3)

            print(
                f"[IBKR] Successfully fetched {len(results)} option contracts "
                f"for {sym} (expiry: {target_exp_str})."
            )
            return results

        except Exception as e:
            print(f"[IBKR] Error fetching option chain for '{sym}': {e}")
            return []

    async def get_historical_candles(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles for a futures symbol.

        Parameters:
            symbol: Root symbol (e.g. 'GC', 'ES', 'NQ')
            period: Duration string (e.g. '1d', '5d', '30d', '60d', '90d', '1y', '1m', '3m', '6m')
            interval: Bar size (e.g. '1m', '5m', '15m', '30m', '1h', '1d', '1w', '1M')

        Returns:
            pd.DataFrame with columns ['Open', 'High', 'Low', 'Close', 'Volume']
            and DatetimeIndex.
        """
        empty_df = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"],
            index=pd.DatetimeIndex([], name="Date"),
        )

        if not await self._ensure_connected():
            return empty_df

        sym = symbol.upper()
        try:
            front_contract = await self._get_front_future(sym)
            if not front_contract:
                print(f"[IBKR] Could not resolve futures contract for '{sym}'.")
                return empty_df

            duration_str = self._parse_period_to_ibkr(period)
            bar_size = self._parse_interval_to_ibkr(interval)

            print(
                f"[IBKR] Requesting historical data for {sym} "
                f"(duration: '{duration_str}', barSize: '{bar_size}')..."
            )

            bars = await self._ib.reqHistoricalDataAsync(
                contract=front_contract,
                endDateTime="",
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
            )

            if not bars:
                print(f"[IBKR] No historical bars returned for {sym}.")
                return empty_df

            records = []
            for b in bars:
                bar_date = getattr(b, "date", None)
                if isinstance(bar_date, str):
                    try:
                        bar_dt = pd.to_datetime(bar_date)
                    except Exception:
                        bar_dt = bar_date
                elif isinstance(bar_date, (date, datetime)):
                    bar_dt = pd.to_datetime(bar_date)
                else:
                    bar_dt = pd.to_datetime(str(bar_date))

                records.append(
                    {
                        "Date": bar_dt,
                        "Open": float(getattr(b, "open", 0.0)),
                        "High": float(getattr(b, "high", 0.0)),
                        "Low": float(getattr(b, "low", 0.0)),
                        "Close": float(getattr(b, "close", 0.0)),
                        "Volume": (
                            float(getattr(b, "volume", 0.0))
                            if getattr(b, "volume", None) is not None
                            else 0.0
                        ),
                    }
                )

            df = pd.DataFrame(records)
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)
            return df[["Open", "High", "Low", "Close", "Volume"]]

        except Exception as e:
            print(f"[IBKR] Error fetching historical candles for '{sym}': {e}")
            return empty_df

    def get_supported_symbols(self) -> list[str]:
        """
        List of supported futures symbols (CME, COMEX, NYMEX, CBOT).
        """
        return [
            "GC",   # Gold (COMEX)
            "SI",   # Silver (COMEX)
            "HG",   # Copper (COMEX)
            "ES",   # E-mini S&P 500 (CME)
            "NQ",   # E-mini Nasdaq-100 (CME)
            "RTY",  # E-mini Russell 2000 (CME)
            "CL",   # Crude Oil (NYMEX)
            "NG",   # Natural Gas (NYMEX)
            "ZB",   # 30-Year U.S. Treasury Bond (CBOT)
            "ZN",   # 10-Year U.S. Treasury Note (CBOT)
            "ZF",   # 5-Year U.S. Treasury Note (CBOT)
            "ZT",   # 2-Year U.S. Treasury Note (CBOT)
            "ZC",   # Corn (CBOT)
            "ZS",   # Soybeans (CBOT)
            "ZW",   # Wheat (CBOT)
            "YM",   # E-mini Dow (CBOT)
            "6E",   # Euro FX (CME)
            "6B",   # British Pound (CME)
            "6J",   # Japanese Yen (CME)
            "6A",   # Australian Dollar (CME)
            "6C",   # Canadian Dollar (CME)
        ]

    def get_provider_name(self) -> str:
        """Human-readable provider name."""
        return "Interactive Brokers"

    def get_asset_class(self) -> AssetClass:
        """Asset class served by this adapter."""
        return AssetClass.FUTURES_OPTIONS

    # ── Optional Methods Overrides ───────────────────────

    async def get_expirations(self, symbol: str) -> list[date]:
        """
        List available expiration dates for a futures symbol.
        Uses reqSecDefOptParamsAsync directly for fast resolution.
        """
        if not await self._ensure_connected():
            return []

        sym = symbol.upper()
        try:
            front_contract = await self._get_front_future(sym)
            if not front_contract or not front_contract.conId:
                return []

            chains = await self._ib.reqSecDefOptParamsAsync(
                underlyingSymbol=sym,
                futFopExchange="",
                underlyingSecType="FUT",
                underlyingConId=front_contract.conId,
            )

            today = date.today()
            expiries = set()
            for ch in chains:
                for exp_str in ch.expirations:
                    try:
                        exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
                        if exp_date >= today:
                            expiries.add(exp_date)
                    except ValueError:
                        pass

            return sorted(expiries)
        except Exception as e:
            print(f"[IBKR] Error fetching expirations for '{sym}': {e}")
            return []

    async def get_strikes(self, symbol: str, expiry: date) -> list[float]:
        """
        List available strike prices for a given expiry.
        """
        if not await self._ensure_connected():
            return []

        sym = symbol.upper()
        exp_str = expiry.strftime("%Y%m%d")
        try:
            front_contract = await self._get_front_future(sym)
            if not front_contract or not front_contract.conId:
                return []

            chains = await self._ib.reqSecDefOptParamsAsync(
                underlyingSymbol=sym,
                futFopExchange="",
                underlyingSecType="FUT",
                underlyingConId=front_contract.conId,
            )

            strikes = set()
            for ch in chains:
                if exp_str in ch.expirations:
                    strikes.update(ch.strikes)

            return sorted(strikes)
        except Exception as e:
            print(f"[IBKR] Error fetching strikes for '{sym}' ({expiry}): {e}")
            return []

    def get_capabilities(self) -> dict:
        """Describe IBKR adapter capabilities."""
        return {
            "provider": self.get_provider_name(),
            "asset_class": self.get_asset_class().value,
            "symbols": self.get_supported_symbols(),
            "options_chain": True,
            "greeks_included": True,
            "streaming": True,
            "historical": True,
            "open_interest_limited": True,
        }

    # ── Internal Helper Methods ──────────────────────────

    async def _ensure_connected(self) -> bool:
        """Check connection status and attempt connection if disconnected."""
        if not self._connected or self._ib is None or not self._ib.isConnected():
            return await self.connect()
        return True

    def _get_exchange(self, symbol: str) -> str:
        """Determine primary exchange for a given futures symbol."""
        return self.SYMBOL_EXCHANGE_MAP.get(symbol.upper(), "CME")

    def _get_multiplier(self, symbol: str) -> float:
        """Get contract multiplier for notional and Greeks scaling."""
        return self.CONTRACT_MULTIPLIERS.get(symbol.upper(), 1.0)

    async def _get_front_future(self, symbol: str) -> Optional[Any]:
        """
        Resolve front-month active futures contract for a given symbol.
        """
        if self._ib is None:
            return None

        sym = symbol.upper()
        exchange = self._get_exchange(sym)

        # 1. Query with specific exchange
        fut = Future(symbol=sym, exchange=exchange, currency="USD")
        details = await self._ib.reqContractDetailsAsync(fut)

        # 2. Fallback to SMART if exchange query returned nothing
        if not details:
            fut_smart = Future(symbol=sym, exchange="SMART", currency="USD")
            details = await self._ib.reqContractDetailsAsync(fut_smart)

        # 3. Fallback to CME
        if not details:
            fut_cme = Future(symbol=sym, exchange="CME", currency="USD")
            details = await self._ib.reqContractDetailsAsync(fut_cme)

        if not details:
            return None

        today_str = datetime.now().strftime("%Y%m%d")

        # Filter active non-expired contracts
        active = [
            d
            for d in details
            if (getattr(d.contract, "lastTradeDateOrContractMonth", "") or "") >= today_str
        ]

        if active:
            active.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
            return active[0].contract

        # Fallback to the first contract in details
        return details[0].contract

    @staticmethod
    def _clean_float(val: Any, default: float = 0.0) -> float:
        """Sanitize numerical float values from IBKR (guards against NaN and negative values)."""
        if val is None:
            return default
        try:
            f = float(val)
            return f if not math.isnan(f) and f >= 0.0 else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _clean_greek(val: Any, default: float = 0.0) -> float:
        """Sanitize Greek values from IBKR (allows negative values such as theta/delta)."""
        if val is None:
            return default
        try:
            f = float(val)
            return f if not math.isnan(f) else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _clean_int(val: Any, default: int = 0) -> int:
        """Sanitize integer values (volume, OI)."""
        if val is None:
            return default
        try:
            f = float(val)
            return int(f) if not math.isnan(f) and f >= 0.0 else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_period_to_ibkr(period: str) -> str:
        """Convert standard period strings (e.g. '30d', '1y') to IBKR durationStr."""
        p = period.strip().lower()
        mapping = {
            "1d": "1 D",
            "2d": "2 D",
            "5d": "5 D",
            "10d": "10 D",
            "14d": "14 D",
            "30d": "30 D",
            "60d": "60 D",
            "90d": "90 D",
            "180d": "180 D",
            "1m": "1 M",
            "2m": "2 M",
            "3m": "3 M",
            "6m": "6 M",
            "1y": "1 Y",
            "2y": "2 Y",
            "5y": "5 Y",
            "10y": "10 Y",
        }
        if p in mapping:
            return mapping[p]

        # If already in 'X D', 'X M', 'X Y' format
        if any(p.endswith(unit) for unit in [" d", " m", " y", " s", " w"]):
            return period.strip().upper()

        return "30 D"

    @staticmethod
    def _parse_interval_to_ibkr(interval: str) -> str:
        """Convert standard interval strings (e.g. '1d', '5m') to IBKR barSizeSetting."""
        inv = interval.strip().lower()
        mapping = {
            "1s": "1 sec",
            "5s": "5 secs",
            "10s": "10 secs",
            "15s": "15 secs",
            "30s": "30 secs",
            "1m": "1 min",
            "1min": "1 min",
            "2m": "2 mins",
            "2mins": "2 mins",
            "3m": "3 mins",
            "3mins": "3 mins",
            "5m": "5 mins",
            "5mins": "5 mins",
            "10m": "10 mins",
            "10mins": "10 mins",
            "15m": "15 mins",
            "15mins": "15 mins",
            "20m": "20 mins",
            "20mins": "20 mins",
            "30m": "30 mins",
            "30mins": "30 mins",
            "1h": "1 hour",
            "1hour": "1 hour",
            "2h": "2 hours",
            "3h": "3 hours",
            "4h": "4 hours",
            "8h": "8 hours",
            "1d": "1 day",
            "1day": "1 day",
            "day": "1 day",
            "1w": "1 week",
            "1week": "1 week",
            "week": "1 week",
            "1month": "1 month",
            "1mon": "1 month",
        }
        return mapping.get(inv, "1 day")

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<IBKRAdapter [{status}] host={self.host}:{self.port} clientId={self.client_id}>"

