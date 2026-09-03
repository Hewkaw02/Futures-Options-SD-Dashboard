"""
Databento Data Provider Adapter.

Provides DIRECT CME Globex market data via the GLBX.MDP3 dataset —
institutional-grade tick-level data straight from the exchange.

API Details:
- Dataset: GLBX.MDP3 (CME Globex MDP 3.0)
- Auth: API Key (starts with 'db-'), env var DATABENTO_API_KEY
- SDK: `databento` (pip install databento, Python 3.10+)
- Rate Limits: 100 req/sec (timeseries), 100 concurrent connections
- Cost: $125 free credits on signup, then pay-per-GB
- Asset Class: AssetClass.FUTURES_OPTIONS

Parent Symbology (stype_in='parent'):
  GC.OPT → all Gold options (all strikes, expiries, puts/calls)
  ES.OPT → all E-mini S&P 500 options
  NQ.OPT → all NASDAQ E-mini options
  GC.FUT, ES.FUT, NQ.FUT → underlying futures prices

Schemas:
  'definition'  → instrument metadata (strike, expiry, instrument class, raw_symbol)
  'mbp-1'       → top-of-book quotes (bid/ask)
  'trades'      → tick-by-tick trade data
  'statistics'  → EOD OI, volume, settlement prices
  'ohlcv-1d'    → daily OHLCV candles
  'ohlcv-1h'    → hourly OHLCV candles

IMPORTANT: Databento does NOT provide pre-calculated Greeks.
The adapter populates bid/ask/OI/volume — consumers should use
analytics/exposure.py's black76_greeks() to calculate Greeks from raw data.

Reference: https://databento.com/docs
"""

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from .base import AssetClass, BaseDataAdapter, UnifiedFuturesData, UnifiedOptionData
from .registry import AdapterRegistry

# Conditionally import databento SDK
try:
    import databento as db
    HAS_DATABENTO = True
except ImportError:
    db = None
    HAS_DATABENTO = False

# Default dataset for CME Globex
DATASET = "GLBX.MDP3"

# Map root symbols to parent symbol suffixes
SYMBOL_MAP = {
    "GC": {"opt": "GC.OPT", "fut": "GC.FUT", "exchange": "COMEX"},
    "SI": {"opt": "SI.OPT", "fut": "SI.FUT", "exchange": "COMEX"},
    "ES": {"opt": "ES.OPT", "fut": "ES.FUT", "exchange": "CME"},
    "NQ": {"opt": "NQ.OPT", "fut": "NQ.FUT", "exchange": "CME"},
    "CL": {"opt": "LO.OPT", "fut": "CL.FUT", "exchange": "NYMEX"},
    "ZB": {"opt": "OZB.OPT", "fut": "ZB.FUT", "exchange": "CBOT"},
    "ZN": {"opt": "OZN.OPT", "fut": "ZN.FUT", "exchange": "CBOT"},
}

CONTRACT_MULTIPLIERS = {
    "GC": 100.0,   # 100 troy oz per contract
    "SI": 5000.0,  # 5000 troy oz
    "ES": 50.0,    # $50 per index point
    "NQ": 20.0,    # $20 per index point
    "CL": 1000.0,  # 1000 barrels
    "ZB": 1000.0,  # $1000 per point
    "ZN": 1000.0,  # $1000 per point
}


@AdapterRegistry.register("databento", env_keys=["DATABENTO_API_KEY"])
class DatabentoAdapter(BaseDataAdapter):
    """
    Databento CME Globex adapter — direct exchange data via GLBX.MDP3.

    Provides option chains (definitions + quotes + OI), futures prices,
    and historical OHLCV candles for CME/COMEX/NYMEX/CBOT products.

    Usage:
        adapter = AdapterRegistry.get("databento", api_key="db-xxx")
        await adapter.connect()
        chain = await adapter.get_option_chain("GC")
        price = await adapter.get_futures_price("ES")
        candles = await adapter.get_historical_candles("NQ", period="30d")
        await adapter.disconnect()
    """

    def __init__(self, api_key: str = "", **kwargs):
        super().__init__(**kwargs)
        self._api_key = api_key or os.getenv("DATABENTO_API_KEY", "")
        self._hist_client = None
        self._live_client = None

    async def connect(self) -> bool:
        """
        Initialize Databento Historical client and validate API key.
        """
        if not HAS_DATABENTO:
            print(
                "[Databento] ERROR: databento SDK not installed.\n"
                "  Install with: pip install databento\n"
                "  Requires Python 3.10+"
            )
            return False

        if not self._api_key:
            print(
                "[Databento] ERROR: No API key provided.\n"
                "  Set DATABENTO_API_KEY in .env or pass api_key='db-...'"
            )
            return False

        try:
            self._hist_client = db.Historical(key=self._api_key)
            # Validate by fetching dataset metadata
            metadata = self._hist_client.metadata.list_datasets()
            if DATASET in [d for d in metadata]:
                print(f"[Databento] Connected — dataset {DATASET} available")
            else:
                print(f"[Databento] Connected — {len(metadata)} datasets available")
            self._connected = True
            return True
        except Exception as e:
            print(f"[Databento] Connection failed: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Clean up resources."""
        self._hist_client = None
        if self._live_client is not None:
            try:
                self._live_client.stop()
            except Exception:
                pass
            self._live_client = None
        self._connected = False
        print("[Databento] Disconnected")

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """
        Fetch CME futures option chain from Databento GLBX.MDP3.

        Steps:
        1. Fetch instrument definitions (strikes, expiries, types)
        2. Fetch statistics (OI, volume, settlement)
        3. Fetch top-of-book quotes (bid/ask)
        4. Merge and map to UnifiedOptionData

        Note: Greeks are NOT included — use analytics/exposure.py's
        black76_greeks() to calculate from bid/ask/IV data.
        """
        if not self._connected or not self._hist_client:
            print("[Databento] Not connected. Call connect() first.")
            return []

        root = symbol.upper().replace("/", "")
        if root not in SYMBOL_MAP:
            print(
                f"[Databento] Unsupported symbol: {root}. "
                f"Supported: {list(SYMBOL_MAP.keys())}"
            )
            return []

        opt_symbol = SYMBOL_MAP[root]["opt"]
        multiplier = CONTRACT_MULTIPLIERS.get(root, 1.0)

        # Use yesterday as start for latest data
        start_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )

        try:
            # Step 1: Fetch instrument definitions
            print(f"[Databento] Fetching definitions for {opt_symbol}...")
            defs_data = await asyncio.to_thread(
                self._fetch_definitions, opt_symbol, start_date
            )

            # Step 2: Fetch statistics (OI, volume, settlement)
            print(f"[Databento] Fetching statistics for {opt_symbol}...")
            stats_data = await asyncio.to_thread(
                self._fetch_statistics, opt_symbol, start_date
            )

            # Step 3: Fetch top-of-book quotes
            print(f"[Databento] Fetching quotes for {opt_symbol}...")
            quotes_data = await asyncio.to_thread(
                self._fetch_quotes, opt_symbol, start_date
            )

            # Step 4: Merge data and create UnifiedOptionData list
            options = self._merge_option_data(
                root, defs_data, stats_data, quotes_data, multiplier, expiry
            )

            print(
                f"[Databento] Got {len(options)} {root} options"
                + (f" (filtered to expiry {expiry})" if expiry else "")
            )
            return options

        except Exception as e:
            print(f"[Databento] Error fetching option chain for {root}: {e}")
            return []

    def _fetch_definitions(self, opt_symbol: str, start_date: str) -> pd.DataFrame:
        """Fetch instrument definitions — runs in thread."""
        data = self._hist_client.timeseries.get_range(
            dataset=DATASET,
            schema="definition",
            stype_in="parent",
            symbols=opt_symbol,
            start=start_date,
        )
        return data.to_df()

    def _fetch_statistics(self, opt_symbol: str, start_date: str) -> pd.DataFrame:
        """Fetch statistics (OI, volume, settlement) — runs in thread."""
        try:
            data = self._hist_client.timeseries.get_range(
                dataset=DATASET,
                schema="statistics",
                stype_in="parent",
                symbols=opt_symbol,
                start=start_date,
            )
            return data.to_df()
        except Exception as e:
            print(f"[Databento] Warning: Could not fetch statistics: {e}")
            return pd.DataFrame()

    def _fetch_quotes(self, opt_symbol: str, start_date: str) -> pd.DataFrame:
        """Fetch top-of-book quotes — runs in thread."""
        try:
            data = self._hist_client.timeseries.get_range(
                dataset=DATASET,
                schema="mbp-1",
                stype_in="parent",
                symbols=opt_symbol,
                start=start_date,
            )
            return data.to_df()
        except Exception as e:
            print(f"[Databento] Warning: Could not fetch quotes: {e}")
            return pd.DataFrame()

    def _merge_option_data(
        self,
        root: str,
        defs_df: pd.DataFrame,
        stats_df: pd.DataFrame,
        quotes_df: pd.DataFrame,
        multiplier: float,
        target_expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """
        Merge definition, statistics, and quotes data into UnifiedOptionData.
        """
        options = []

        if defs_df.empty:
            return options

        # Build lookup dicts keyed by instrument_id or raw_symbol
        stats_by_id = {}
        if not stats_df.empty and "instrument_id" in stats_df.columns:
            # Group by instrument and take latest
            for inst_id, group in stats_df.groupby("instrument_id"):
                latest = group.iloc[-1]
                stats_by_id[inst_id] = latest

        quotes_by_id = {}
        if not quotes_df.empty and "instrument_id" in quotes_df.columns:
            for inst_id, group in quotes_df.groupby("instrument_id"):
                latest = group.iloc[-1]
                quotes_by_id[inst_id] = latest

        # Process definitions
        for _, defn in defs_df.iterrows():
            try:
                # Extract fields from definition record
                inst_id = defn.get("instrument_id", None)
                raw_sym = str(defn.get("raw_symbol", ""))

                # Parse instrument class — filter for options only
                inst_class = str(defn.get("instrument_class", ""))
                if inst_class not in ("C", "P", "call", "put"):
                    # Also try parsing from raw symbol
                    option_type = self._parse_option_type(raw_sym, defn)
                    if option_type is None:
                        continue
                else:
                    option_type = "C" if inst_class in ("C", "call") else "P"

                # Strike price
                strike = self._safe_float(defn.get("strike_price", 0))
                if strike <= 0:
                    continue

                # Expiration date
                expiry_val = defn.get("expiration", None)
                if expiry_val is None:
                    continue
                if isinstance(expiry_val, pd.Timestamp):
                    expiry_date = expiry_val.date()
                elif isinstance(expiry_val, datetime):
                    expiry_date = expiry_val.date()
                elif isinstance(expiry_val, date):
                    expiry_date = expiry_val
                else:
                    try:
                        expiry_date = pd.Timestamp(expiry_val).date()
                    except Exception:
                        continue

                # Filter by target expiry if specified
                if target_expiry and expiry_date != target_expiry:
                    continue

                # Skip expired options
                if expiry_date < date.today():
                    continue

                # Get quotes data
                bid = 0.0
                ask = 0.0
                last = 0.0
                if inst_id in quotes_by_id:
                    q = quotes_by_id[inst_id]
                    bid = self._safe_float(q.get("bid_px_00", 0))
                    ask = self._safe_float(q.get("ask_px_00", 0))
                    last = self._safe_float(q.get("price", 0))

                # Get statistics data
                volume = 0
                open_interest = 0
                if inst_id in stats_by_id:
                    s = stats_by_id[inst_id]
                    volume = int(self._safe_float(s.get("quantity", 0)))
                    open_interest = int(self._safe_float(s.get("quantity", 0)))
                    # Check stat_type for distinguishing OI vs volume
                    stat_type = s.get("stat_type", "")
                    if hasattr(stat_type, "value"):
                        stat_type = stat_type.value

                opt = UnifiedOptionData(
                    symbol=root,
                    strike=strike,
                    option_type=option_type,
                    expiry=expiry_date,
                    bid=bid,
                    ask=ask,
                    last=last,
                    volume=volume,
                    open_interest=open_interest,
                    iv=0.0,  # Not provided by Databento
                    delta=0.0,
                    gamma=0.0,
                    theta=0.0,
                    vega=0.0,
                    underlying_price=0.0,
                    multiplier=multiplier,
                    timestamp=datetime.now(timezone.utc),
                    streamer_symbol=raw_sym,
                    provider="databento",
                    raw={"instrument_id": inst_id, "raw_symbol": raw_sym},
                )
                options.append(opt)

            except Exception as e:
                # Skip malformed records
                continue

        # If no target expiry, filter to nearest expiry
        if not target_expiry and options:
            expiries = sorted(set(o.expiry for o in options))
            if expiries:
                nearest = expiries[0]
                options = [o for o in options if o.expiry == nearest]

        return options

    def _parse_option_type(self, raw_symbol: str, defn: Any) -> Optional[str]:
        """Try to determine option type from various fields."""
        # Check strike_price_currency or other fields
        for field in ["security_sub_type", "security_type", "instrument_class"]:
            val = str(defn.get(field, "")).upper()
            if "CALL" in val or val == "C":
                return "C"
            if "PUT" in val or val == "P":
                return "P"

        # Try parsing from raw symbol
        raw_upper = raw_symbol.upper()
        if " C " in raw_upper or raw_upper.endswith("C"):
            return "C"
        if " P " in raw_upper or raw_upper.endswith("P"):
            return "P"

        return None

    @staticmethod
    def _safe_float(val: Any) -> float:
        """Safely convert a value to float."""
        if val is None:
            return 0.0
        try:
            f = float(val)
            if pd.isna(f):
                return 0.0
            return f
        except (ValueError, TypeError):
            return 0.0

    async def get_futures_price(self, symbol: str) -> UnifiedFuturesData:
        """
        Fetch current futures price from Databento.
        Uses latest trade or top-of-book for the front-month contract.
        """
        if not self._connected or not self._hist_client:
            print("[Databento] Not connected.")
            return UnifiedFuturesData(symbol=symbol, price=0.0, provider="databento")

        root = symbol.upper().replace("/", "")
        if root not in SYMBOL_MAP:
            print(f"[Databento] Unsupported symbol: {root}")
            return UnifiedFuturesData(symbol=root, price=0.0, provider="databento")

        fut_symbol = SYMBOL_MAP[root]["fut"]
        start_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime(
            "%Y-%m-%d"
        )

        try:
            # Fetch recent trades for the futures contract
            data = await asyncio.to_thread(
                lambda: self._hist_client.timeseries.get_range(
                    dataset=DATASET,
                    schema="trades",
                    stype_in="parent",
                    symbols=fut_symbol,
                    start=start_date,
                    limit=100,
                )
            )
            df = data.to_df()

            if df.empty:
                # Fallback to OHLCV
                ohlcv = await asyncio.to_thread(
                    lambda: self._hist_client.timeseries.get_range(
                        dataset=DATASET,
                        schema="ohlcv-1d",
                        stype_in="parent",
                        symbols=fut_symbol,
                        start=start_date,
                    )
                )
                df_ohlcv = ohlcv.to_df()
                if not df_ohlcv.empty:
                    latest = df_ohlcv.iloc[-1]
                    return UnifiedFuturesData(
                        symbol=root,
                        price=float(latest.get("close", 0)),
                        high=float(latest.get("high", 0)),
                        low=float(latest.get("low", 0)),
                        open=float(latest.get("open", 0)),
                        volume=int(latest.get("volume", 0)),
                        provider="databento",
                        timestamp=datetime.now(timezone.utc),
                    )

            # Use latest trade
            latest = df.iloc[-1]
            price = float(latest.get("price", 0))

            # Try to get bid/ask from mbp-1
            bid = 0.0
            ask = 0.0
            try:
                mbp = await asyncio.to_thread(
                    lambda: self._hist_client.timeseries.get_range(
                        dataset=DATASET,
                        schema="mbp-1",
                        stype_in="parent",
                        symbols=fut_symbol,
                        start=start_date,
                        limit=10,
                    )
                )
                mbp_df = mbp.to_df()
                if not mbp_df.empty:
                    last_q = mbp_df.iloc[-1]
                    bid = float(last_q.get("bid_px_00", 0))
                    ask = float(last_q.get("ask_px_00", 0))
            except Exception:
                pass

            return UnifiedFuturesData(
                symbol=root,
                price=price,
                bid=bid,
                ask=ask,
                volume=int(latest.get("size", 0)),
                provider="databento",
                timestamp=datetime.now(timezone.utc),
            )

        except Exception as e:
            print(f"[Databento] Error fetching futures price for {root}: {e}")
            return UnifiedFuturesData(
                symbol=root, price=0.0, provider="databento"
            )

    async def get_historical_candles(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles from Databento.

        Args:
            symbol: Root symbol (GC, ES, NQ)
            period: Lookback period (e.g., '30d', '60d', '1y')
            interval: Bar interval ('1d', '1h')

        Returns:
            DataFrame with columns ['Open', 'High', 'Low', 'Close', 'Volume']
            and DatetimeIndex.
        """
        if not self._connected or not self._hist_client:
            print("[Databento] Not connected.")
            return pd.DataFrame()

        root = symbol.upper().replace("/", "")
        if root not in SYMBOL_MAP:
            print(f"[Databento] Unsupported symbol: {root}")
            return pd.DataFrame()

        fut_symbol = SYMBOL_MAP[root]["fut"]

        # Parse period to days
        days = self._parse_period(period)
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d"
        )

        # Map interval to schema
        schema_map = {
            "1d": "ohlcv-1d",
            "1h": "ohlcv-1h",
            "1m": "ohlcv-1m",
            "1s": "ohlcv-1s",
        }
        schema = schema_map.get(interval, "ohlcv-1d")

        try:
            data = await asyncio.to_thread(
                lambda: self._hist_client.timeseries.get_range(
                    dataset=DATASET,
                    schema=schema,
                    stype_in="parent",
                    symbols=fut_symbol,
                    start=start_date,
                )
            )
            df = data.to_df()

            if df.empty:
                return pd.DataFrame()

            # Normalize column names to standard format
            result = pd.DataFrame(
                {
                    "Open": df["open"].astype(float),
                    "High": df["high"].astype(float),
                    "Low": df["low"].astype(float),
                    "Close": df["close"].astype(float),
                    "Volume": df["volume"].astype(int),
                }
            )

            # Set DatetimeIndex
            if "ts_event" in df.columns:
                result.index = pd.to_datetime(df["ts_event"], utc=True)
            elif df.index.dtype == "datetime64[ns, UTC]":
                result.index = df.index
            else:
                result.index = pd.to_datetime(df.index, utc=True)

            result.index.name = "Date"

            # Remove duplicate timestamps, keep last
            result = result[~result.index.duplicated(keep="last")]
            result.sort_index(inplace=True)

            print(
                f"[Databento] Got {len(result)} {interval} candles for {root}"
            )
            return result

        except Exception as e:
            print(f"[Databento] Error fetching candles for {root}: {e}")
            return pd.DataFrame()

    @staticmethod
    def _parse_period(period: str) -> int:
        """Convert period string to number of days."""
        period = period.lower().strip()
        if period.endswith("d"):
            return int(period[:-1])
        elif period.endswith("w"):
            return int(period[:-1]) * 7
        elif period.endswith("m") or period.endswith("mo"):
            num = int(period.rstrip("mo"))
            return num * 30
        elif period.endswith("y"):
            return int(period[:-1]) * 365
        else:
            try:
                return int(period)
            except ValueError:
                return 30

    def get_supported_symbols(self) -> list[str]:
        """List of symbols this adapter can provide data for."""
        return list(SYMBOL_MAP.keys())

    def get_provider_name(self) -> str:
        return "Databento"

    def get_asset_class(self) -> AssetClass:
        return AssetClass.FUTURES_OPTIONS

    def get_capabilities(self) -> dict:
        """Describe adapter capabilities."""
        return {
            "provider": self.get_provider_name(),
            "asset_class": self.get_asset_class().value,
            "symbols": self.get_supported_symbols(),
            "options_chain": True,
            "greeks_included": False,  # Must use black76_greeks() separately
            "streaming": True,  # db.Live() available
            "historical": True,  # Tick-level historical
            "order_book_depth": True,  # mbp-10 available
            "dataset": DATASET,
            "note": (
                "Greeks not included in raw data. Use "
                "analytics/exposure.py black76_greeks() to calculate."
            ),
        }

    async def get_expirations(self, symbol: str) -> list[date]:
        """
        Fast expiration list using definition schema.
        """
        if not self._connected or not self._hist_client:
            return []

        root = symbol.upper().replace("/", "")
        if root not in SYMBOL_MAP:
            return []

        opt_symbol = SYMBOL_MAP[root]["opt"]
        start_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )

        try:
            df = await asyncio.to_thread(
                self._fetch_definitions, opt_symbol, start_date
            )
            if df.empty:
                return []

            expiries = set()
            for _, row in df.iterrows():
                exp_val = row.get("expiration", None)
                if exp_val is not None:
                    if isinstance(exp_val, (pd.Timestamp, datetime)):
                        d = exp_val.date() if hasattr(exp_val, "date") else exp_val
                    elif isinstance(exp_val, date):
                        d = exp_val
                    else:
                        try:
                            d = pd.Timestamp(exp_val).date()
                        except Exception:
                            continue
                    if d >= date.today():
                        expiries.add(d)

            return sorted(expiries)

        except Exception as e:
            print(f"[Databento] Error fetching expirations for {root}: {e}")
            return []

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        key_preview = (
            f"{self._api_key[:5]}...{self._api_key[-4:]}"
            if len(self._api_key) > 9
            else "not set"
        )
        return f"<Databento [{status}] key={key_preview}>"
