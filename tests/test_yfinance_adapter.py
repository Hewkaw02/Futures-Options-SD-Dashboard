"""
Unit and Integration tests for YFinanceAdapter.
"""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from adapters import (
    AdapterRegistry,
    AssetClass,
    BaseDataAdapter,
    UnifiedFuturesData,
    UnifiedOptionData,
    YFinanceAdapter,
    unified_chain_to_tastytrade_format,
    unified_futures_to_mark_price,
    unified_to_analytics_rows,
    unified_to_master_report_records,
)


class TestYFinanceAdapter(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_registration(self):
        """Verify YFinanceAdapter is properly registered in AdapterRegistry."""
        self.assertIn("yfinance", AdapterRegistry.list_providers())
        adapter = AdapterRegistry.get("yfinance")
        self.assertIsInstance(adapter, YFinanceAdapter)
        self.assertIsInstance(adapter, BaseDataAdapter)
        self.assertEqual(adapter.get_provider_name(), "Yahoo Finance")
        self.assertEqual(adapter.get_asset_class(), AssetClass.FUTURES)
        self.assertIn("yfinance", AdapterRegistry.list_by_asset_class(AssetClass.FUTURES))

    def test_connect_and_disconnect(self):
        """Test connection lifecycle."""
        adapter = YFinanceAdapter()
        self.assertFalse(adapter.is_connected)

        connected = self.loop.run_until_complete(adapter.connect())
        self.assertTrue(connected)
        self.assertTrue(adapter.is_connected)

        self.loop.run_until_complete(adapter.disconnect())
        self.assertFalse(adapter.is_connected)

    def test_supported_symbols_and_capabilities(self):
        """Test supported symbols and capabilities metadata."""
        adapter = YFinanceAdapter()
        symbols = adapter.get_supported_symbols()
        self.assertIn("GC", symbols)
        self.assertIn("ES", symbols)
        self.assertIn("NQ", symbols)
        self.assertIn("SPY", symbols)
        self.assertIn("QQQ", symbols)

        caps = adapter.get_capabilities()
        self.assertEqual(caps["provider"], "Yahoo Finance")
        self.assertEqual(caps["asset_class"], "futures")
        self.assertTrue(caps["options_chain"])
        self.assertFalse(caps["futures_options"])
        self.assertFalse(caps["greeks_included"])
        self.assertFalse(caps["streaming"])
        self.assertTrue(caps["historical"])
        self.assertFalse(caps["auth_required"])

    def test_get_futures_price_mapping(self):
        """Test futures symbol mapping and UnifiedFuturesData mapping."""
        adapter = YFinanceAdapter()

        # Mock yfinance Ticker
        mock_df = pd.DataFrame(
            [
                {
                    "Open": 2400.0,
                    "High": 2420.0,
                    "Low": 2390.0,
                    "Close": 2415.0,
                    "Volume": 150000,
                }
            ],
            index=pd.DatetimeIndex([datetime(2026, 9, 2, 10, 0, 0)], name="Date"),
        )
        mock_fast_info = SimpleNamespace(
            last_price=2415.0,
            regular_market_previous_close=2400.0,
            open=2400.0,
            day_high=2420.0,
            day_low=2390.0,
        )

        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = mock_df
            mock_ticker.fast_info = mock_fast_info
            mock_ticker_cls.return_value = mock_ticker

            fut_data = self.loop.run_until_complete(adapter.get_futures_price("GC"))
            mock_ticker_cls.assert_called_with("GC=F")

            self.assertEqual(fut_data.symbol, "GC")
            self.assertEqual(fut_data.price, 2415.0)
            self.assertEqual(fut_data.open, 2400.0)
            self.assertEqual(fut_data.high, 2420.0)
            self.assertEqual(fut_data.low, 2390.0)
            self.assertEqual(fut_data.volume, 150000)
            self.assertAlmostEqual(fut_data.change, 15.0)
            self.assertAlmostEqual(fut_data.change_pct, (15.0 / 2400.0) * 100.0)
            self.assertEqual(fut_data.provider, "yfinance")

    def test_get_option_chain_futures_empty(self):
        """Futures symbols should return an empty list because yfinance does not provide futures options."""
        adapter = YFinanceAdapter()
        chain = self.loop.run_until_complete(adapter.get_option_chain("GC"))
        self.assertEqual(chain, [])

        chain_es = self.loop.run_until_complete(adapter.get_option_chain("ES"))
        self.assertEqual(chain_es, [])

    def test_get_option_chain_equity(self):
        """Equity symbols like SPY should parse calls and puts into UnifiedOptionData with 0 Greeks."""
        adapter = YFinanceAdapter()

        calls_data = pd.DataFrame(
            [
                {
                    "contractSymbol": "SPY260918C00500000",
                    "lastTradeDate": pd.Timestamp("2026-09-01 15:30:00"),
                    "strike": 500.0,
                    "lastPrice": 12.50,
                    "bid": 12.40,
                    "ask": 12.60,
                    "volume": 3500,
                    "openInterest": 12000,
                    "impliedVolatility": 0.185,
                    "inTheMoney": True,
                }
            ]
        )
        puts_data = pd.DataFrame(
            [
                {
                    "contractSymbol": "SPY260918P00500000",
                    "lastTradeDate": pd.Timestamp("2026-09-01 15:30:00"),
                    "strike": 500.0,
                    "lastPrice": 8.50,
                    "bid": 8.40,
                    "ask": 8.60,
                    "volume": 2200,
                    "openInterest": 9500,
                    "impliedVolatility": 0.192,
                    "inTheMoney": False,
                }
            ]
        )

        mock_chain = SimpleNamespace(calls=calls_data, puts=puts_data)
        mock_fast_info = SimpleNamespace(last_price=505.0)

        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker = MagicMock()
            mock_ticker.options = ("2026-09-18", "2026-09-25")
            mock_ticker.option_chain.return_value = mock_chain
            mock_ticker.fast_info = mock_fast_info
            mock_ticker_cls.return_value = mock_ticker

            chain = self.loop.run_until_complete(adapter.get_option_chain("SPY"))
            self.assertEqual(len(chain), 2)

            call_opt = chain[0]
            self.assertEqual(call_opt.symbol, "SPY")
            self.assertEqual(call_opt.strike, 500.0)
            self.assertEqual(call_opt.option_type, "C")
            self.assertEqual(call_opt.expiry, date(2026, 9, 18))
            self.assertEqual(call_opt.bid, 12.40)
            self.assertEqual(call_opt.ask, 12.60)
            self.assertEqual(call_opt.last, 12.50)
            self.assertEqual(call_opt.mark, 12.50)
            self.assertEqual(call_opt.volume, 3500)
            self.assertEqual(call_opt.open_interest, 12000)
            self.assertEqual(call_opt.iv, 0.185)
            self.assertEqual(call_opt.delta, 0.0)
            self.assertEqual(call_opt.gamma, 0.0)
            self.assertEqual(call_opt.theta, 0.0)
            self.assertEqual(call_opt.vega, 0.0)
            self.assertEqual(call_opt.rho, 0.0)
            self.assertEqual(call_opt.multiplier, 100.0)
            self.assertEqual(call_opt.provider, "yfinance")

            put_opt = chain[1]
            self.assertEqual(put_opt.option_type, "P")
            self.assertEqual(put_opt.strike, 500.0)
            self.assertEqual(put_opt.bid, 8.40)
            self.assertEqual(put_opt.ask, 8.60)
            self.assertEqual(put_opt.iv, 0.192)

    def test_get_historical_candles(self):
        """Test historical candles fetching and DataFrame formatting."""
        adapter = YFinanceAdapter()

        dates = pd.date_range("2026-08-01", periods=5, freq="D")
        mock_df = pd.DataFrame(
            {
                "Open": [2400.0, 2410.0, 2405.0, 2420.0, 2415.0],
                "High": [2420.0, 2430.0, 2415.0, 2435.0, 2425.0],
                "Low": [2395.0, 2400.0, 2390.0, 2410.0, 2405.0],
                "Close": [2410.0, 2405.0, 2420.0, 2415.0, 2422.0],
                "Volume": [1000, 1200, 950, 1100, 1300],
                "Dividends": [0, 0, 0, 0, 0],
            },
            index=dates,
        )

        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = mock_df
            mock_ticker_cls.return_value = mock_ticker

            df = self.loop.run_until_complete(
                adapter.get_historical_candles("GC", period="30d", interval="1d")
            )
            mock_ticker_cls.assert_called_with("GC=F")

            self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
            self.assertEqual(len(df), 5)
            self.assertEqual(df.iloc[-1]["Close"], 2422.0)

    def test_bridge_compatibility(self):
        """Test that data produced by YFinanceAdapter works with bridge helper functions."""
        call_opt = UnifiedOptionData(
            symbol="SPY",
            strike=500.0,
            option_type="C",
            expiry=date(2026, 9, 18),
            bid=12.40,
            ask=12.60,
            last=12.50,
            volume=3500,
            open_interest=12000,
            iv=0.185,
            provider="yfinance",
        )
        fut_data = UnifiedFuturesData(
            symbol="SPY",
            price=505.0,
            bid=504.9,
            ask=505.1,
            provider="yfinance",
        )

        # 1. tastytrade format bridge
        tt_dict = unified_chain_to_tastytrade_format([call_opt])
        self.assertIn(date(2026, 9, 18), tt_dict)
        self.assertEqual(tt_dict[date(2026, 9, 18)][0].strike_price, "500.0")

        # 2. analytics rows bridge
        rows = unified_to_analytics_rows([call_opt])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Strike"], 500.0)
        self.assertEqual(rows[0]["OI"], 12000)

        # 3. master report records bridge
        records = unified_to_master_report_records([call_opt])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["Vol"], 3500)

        # 4. mark price bridge
        mark_price = unified_futures_to_mark_price(fut_data)
        self.assertAlmostEqual(mark_price, 505.0)


if __name__ == "__main__":
    unittest.main()
