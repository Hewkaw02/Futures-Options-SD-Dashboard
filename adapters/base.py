"""
Unified Data Contract & Base Adapter Interface.
ทุก provider adapter ต้อง implement BaseDataAdapter.
ข้อมูลทั้งหมดถูก normalize เป็น UnifiedOptionData / UnifiedFuturesData
ก่อนส่งให้ Analytics Engine.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional
import pandas as pd


class AssetClass(Enum):
    FUTURES_OPTIONS = "futures_options"    # CME: GC, ES, NQ
    CRYPTO_OPTIONS = "crypto_options"      # Deribit, Binance: BTC, ETH
    EQUITY_OPTIONS = "equity_options"      # Schwab, Polygon: SPY, QQQ
    FUTURES = "futures"                    # Price data only
    EQUITY = "equity"                      # Price data only


@dataclass
class UnifiedOptionData:
    """Normalized option contract — ทุก adapter map เข้า format นี้."""
    symbol: str                    # Root: "GC", "ES", "NQ", "BTC", "SPY"
    strike: float
    option_type: str               # "C" or "P"
    expiry: date
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    iv: float = 0.0                # Implied Volatility (decimal 0.15 = 15%)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    underlying_price: float = 0.0
    multiplier: float = 1.0        # Contract multiplier (GC=100, ES=50)
    timestamp: Optional[datetime] = None
    streamer_symbol: str = ""      # Backward compat with Tastytrade code
    provider: str = ""             # Which adapter provided this data
    raw: dict = field(default_factory=dict)  # Original provider response

    @property
    def mark(self) -> float:
        """Mid-price."""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def dte(self) -> int:
        """Days to expiration from today."""
        return max(0, (self.expiry - date.today()).days)

    @property
    def has_greeks(self) -> bool:
        return any([self.delta, self.gamma, self.theta, self.vega])


@dataclass
class UnifiedFuturesData:
    """Normalized futures/underlying price data."""
    symbol: str
    price: float
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0
    open_interest: int = 0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    timestamp: Optional[datetime] = None
    provider: str = ""
    raw: dict = field(default_factory=dict)


class BaseDataAdapter(ABC):
    """
    Abstract Base Class — ทุก provider adapter ต้อง implement.

    Usage:
        adapter = AdapterRegistry.get("databento", api_key="db-xxx")
        await adapter.connect()
        chain = await adapter.get_option_chain("GC")
        price = await adapter.get_futures_price("GC")
        candles = await adapter.get_historical_candles("GC", period="30d")
        await adapter.disconnect()
    """

    def __init__(self, **kwargs):
        self._connected = False
        self._config = kwargs

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Required Methods ──────────────────────────────────

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection / validate credentials."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanup resources."""
        ...

    @abstractmethod
    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
    ) -> list[UnifiedOptionData]:
        """
        Fetch full option chain for a symbol.
        If expiry is None, return nearest expiry.
        """
        ...

    @abstractmethod
    async def get_futures_price(
        self, symbol: str
    ) -> UnifiedFuturesData:
        """Fetch current price for the underlying."""
        ...

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Return OHLCV DataFrame with columns:
        ['Open', 'High', 'Low', 'Close', 'Volume']
        Index: DatetimeIndex
        """
        ...

    @abstractmethod
    def get_supported_symbols(self) -> list[str]:
        """List of symbols this adapter can provide data for."""
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Human-readable provider name (e.g. 'Databento')."""
        ...

    @abstractmethod
    def get_asset_class(self) -> AssetClass:
        """What type of instruments does this adapter serve."""
        ...

    # ── Optional Methods (override if supported) ──────────

    async def get_expirations(self, symbol: str) -> list[date]:
        """List available expiration dates."""
        chain = await self.get_option_chain(symbol)
        return sorted(set(o.expiry for o in chain))

    async def get_strikes(
        self, symbol: str, expiry: date
    ) -> list[float]:
        """List available strikes for a given expiry."""
        chain = await self.get_option_chain(symbol, expiry)
        return sorted(set(o.strike for o in chain))

    def get_capabilities(self) -> dict:
        """Describe adapter capabilities."""
        return {
            "provider": self.get_provider_name(),
            "asset_class": self.get_asset_class().value,
            "symbols": self.get_supported_symbols(),
            "options_chain": True,
            "greeks_included": False,
            "streaming": False,
            "historical": False,
        }

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<{self.get_provider_name()} [{status}]>"
