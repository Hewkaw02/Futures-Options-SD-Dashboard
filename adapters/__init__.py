"""
Adapters package for multi-provider market data ingestion.
Curated to the essential providers that work reliably for Futures & Crypto Options:
1. Tastytrade (CME Futures Options)
2. Databento (Direct CME Globex Feed)
3. Interactive Brokers (CME Futures Options via TWS/Gateway)
4. Yahoo Finance (Futures Prices & Historical Candles)
5. Deribit (Crypto BTC/ETH Options - Free public API)
"""
from .base import (
    AssetClass,
    BaseDataAdapter,
    UnifiedFuturesData,
    UnifiedOptionData,
)
from .registry import AdapterRegistry
from .bridge import (
    unified_chain_to_tastytrade_format,
    unified_to_analytics_rows,
    unified_to_master_report_records,
    unified_futures_to_mark_price,
)

# Auto-import core adapters to register them in AdapterRegistry
try:
    from .tastytrade_adapter import TastytradeAdapter
except ImportError:
    TastytradeAdapter = None

try:
    from .databento_adapter import DatabentoAdapter
except ImportError:
    DatabentoAdapter = None

try:
    from .ibkr_adapter import IBKRAdapter
except ImportError:
    IBKRAdapter = None

try:
    from .yfinance_adapter import YFinanceAdapter
except ImportError:
    YFinanceAdapter = None

try:
    from .deribit_adapter import DeribitAdapter, parse_deribit_instrument_name
except ImportError:
    DeribitAdapter = None
    parse_deribit_instrument_name = None

__all__ = [
    "AssetClass",
    "BaseDataAdapter",
    "UnifiedOptionData",
    "UnifiedFuturesData",
    "AdapterRegistry",
    "unified_chain_to_tastytrade_format",
    "unified_to_analytics_rows",
    "unified_to_master_report_records",
    "unified_futures_to_mark_price",
    "TastytradeAdapter",
    "DatabentoAdapter",
    "IBKRAdapter",
    "YFinanceAdapter",
    "DeribitAdapter",
    "parse_deribit_instrument_name",
]
