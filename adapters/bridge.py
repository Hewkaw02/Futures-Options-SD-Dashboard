"""
Bridge — backward compatibility layer.
แปลง UnifiedOptionData ⇆ existing code format ที่ Trading_Core/Main.py
และ Analysis_Tools/master_report.py ใช้อยู่.
"""
from datetime import date
from types import SimpleNamespace
from typing import Optional
from .base import UnifiedOptionData, UnifiedFuturesData


def unified_chain_to_tastytrade_format(
    options: list[UnifiedOptionData],
) -> dict:
    """
    Convert unified options → dict[expiry_date, list[option_obj]]
    ที่ Trading_Core/Main.py ใช้ (keyed by expiry date).
    Returns mock objects that mimic tastytrade Option attributes.
    """
    chain: dict[date, list] = {}
    for opt in options:
        if opt.expiry not in chain:
            chain[opt.expiry] = []
        mock = SimpleNamespace(
            strike_price=str(opt.strike),
            option_type=SimpleNamespace(value=opt.option_type),
            streamer_symbol=(
                opt.streamer_symbol
                or f"{opt.symbol}_{opt.strike}_{opt.option_type}"
            ),
        )
        chain[opt.expiry].append(mock)
    return chain


def unified_to_analytics_rows(
    options: list[UnifiedOptionData],
) -> list[dict]:
    """
    Convert to row-dict format used by analytics modules:
    analytics/order_flow.py, analytics/pin_risk.py, etc.
    """
    return [
        {
            "Strike": opt.strike,
            "Type": opt.option_type,
            "Volume": opt.volume,
            "Open_Interest": opt.open_interest,
            "OI": opt.open_interest,
            "Vol": opt.volume,
            "vol": opt.volume,
            "oi": opt.open_interest,
            "strike": opt.strike,
            "type": opt.option_type,
            "IV": opt.iv,
            "Bid": opt.bid,
            "Ask": opt.ask,
        }
        for opt in options
    ]


def unified_to_master_report_records(
    options: list[UnifiedOptionData],
) -> list[dict]:
    """
    Convert to the record format used in master_report.py
    for building the pandas DataFrame.
    """
    return [
        {
            "Type": opt.option_type,
            "OI": opt.open_interest,
            "Vol": opt.volume,
            "Strike": opt.strike,
        }
        for opt in options
    ]


def unified_futures_to_mark_price(
    futures_data: UnifiedFuturesData,
) -> float:
    """Extract mark price from unified futures data."""
    if futures_data.bid > 0 and futures_data.ask > 0:
        return (futures_data.bid + futures_data.ask) / 2.0
    return futures_data.price
