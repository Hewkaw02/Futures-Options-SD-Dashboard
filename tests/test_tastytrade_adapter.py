"""
Unit tests for TastytradeAdapter.
"""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from adapters import AdapterRegistry, AssetClass, TastytradeAdapter
from adapters.base import UnifiedFuturesData, UnifiedOptionData


class TestTastytradeAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = TastytradeAdapter(
            client_secret="test_secret",
            refresh_token="test_token",
            fetch_greeks=False,
        )

    def test_registry_registration(self):
        """Test that Tastytrade adapter is registered in AdapterRegistry."""
        self.assertIn("tastytrade", AdapterRegistry.list_providers())
        instance = AdapterRegistry.get("tastytrade", client_secret="s", refresh_token="t")
        self.assertIsInstance(instance, TastytradeAdapter)

        info = AdapterRegistry.get_provider_info("tastytrade")
        self.assertEqual(info["name"], "tastytrade")
        self.assertIn("TASTYTRADE_CLIENT_SECRET", info["env_keys"])
        self.assertIn("TASTYTRADE_REFRESH_TOKEN", info["env_keys"])

    def test_provider_metadata(self):
        """Test provider metadata, symbols, and asset class."""
        self.assertEqual(self.adapter.get_provider_name(), "Tastytrade")
        self.assertEqual(self.adapter.get_asset_class(), AssetClass.FUTURES_OPTIONS)
        supported = self.adapter.get_supported_symbols()
        self.assertIn("/GC", supported)
        self.assertIn("/ES", supported)
        self.assertIn("/NQ", supported)
        self.assertIn("GC", supported)

        caps = self.adapter.get_capabilities()
        self.assertTrue(caps["options_chain"])
        self.assertTrue(caps["greeks_included"])
        self.assertEqual(caps["asset_class"], "futures_options")

    def test_multipliers_and_symbol_helpers(self):
        """Test multiplier lookup and symbol formatting."""
        self.assertEqual(self.adapter._get_multiplier("GC"), 100.0)
        self.assertEqual(self.adapter._get_multiplier("/GC"), 100.0)
        self.assertEqual(self.adapter._get_multiplier("ES"), 50.0)
        self.assertEqual(self.adapter._get_multiplier("NQ"), 20.0)

        self.assertEqual(self.adapter._normalize_root("/GC"), "GC")
        self.assertEqual(self.adapter._normalize_root("gc"), "GC")
        self.assertEqual(self.adapter._to_tastytrade_symbol("GC"), "/GC")
        self.assertEqual(self.adapter._to_yfinance_symbol("GC"), "GC=F")
        self.assertEqual(self.adapter._to_yfinance_symbol("ES"), "ES=F")
        self.assertEqual(self.adapter._to_yfinance_symbol("NQ"), "NQ=F")

    def test_infer_mark_price_from_chain(self):
        """Test mark price inference from median strike."""
        exp = date(2026, 9, 2)
        mock_options = [
            SimpleNamespace(strike_price="2400.0", option_type=SimpleNamespace(value="C")),
            SimpleNamespace(strike_price="2450.0", option_type=SimpleNamespace(value="C")),
            SimpleNamespace(strike_price="2500.0", option_type=SimpleNamespace(value="C")),
        ]
        chain = {exp: mock_options}
        mark = TastytradeAdapter.infer_mark_price_from_chain(chain, exp)
        self.assertEqual(mark, 2450.0)

        # Non-existent expiry
        self.assertEqual(TastytradeAdapter.infer_mark_price_from_chain(chain, date(2026, 1, 1)), 0.0)

    def test_calc_sd_ranges(self):
        """Test 1-SD and 2-SD calculation."""
        res = TastytradeAdapter.calc_sd_ranges(price=2400.0, iv=0.20, dte=5.0)
        self.assertIn("1sd_upper", res)
        self.assertIn("1sd_lower", res)
        self.assertIn("2sd_upper", res)
        self.assertIn("2sd_lower", res)
        self.assertGreater(res["1sd_upper"], 2400.0)
        self.assertLess(res["1sd_lower"], 2400.0)
        self.assertGreater(res["2sd_upper"], res["1sd_upper"])

    def test_monkeypatch_error_validation(self):
        """Test patched validate_response with malformed string error."""
        import tastytrade.utils as tt_utils
        from tastytrade.utils import TastytradeError

        # Mock a response with string error
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "Invalid token"}
        mock_response.text = '{"error": "Invalid token"}'

        with self.assertRaises(TastytradeError) as ctx:
            tt_utils.validate_response(mock_response)
        self.assertIn("Invalid token", str(ctx.exception))

    def test_get_historical_candles_yfinance(self):
        """Test historical candles retrieval."""
        async def _run():
            # Mock yfinance ticker
            mock_df = pd.DataFrame(
                {
                    "Open": [2400.0, 2410.0],
                    "High": [2420.0, 2430.0],
                    "Low": [2390.0, 2400.0],
                    "Close": [2410.0, 2425.0],
                    "Volume": [1000, 1500],
                },
                index=pd.date_range("2026-09-01", periods=2, freq="D"),
            )
            with patch("yfinance.Ticker") as mock_ticker:
                mock_ticker.return_value.history.return_value = mock_df
                candles = await self.adapter.get_historical_candles("GC", period="5d")
                self.assertEqual(len(candles), 2)
                self.assertListEqual(list(candles.columns), ["Open", "High", "Low", "Close", "Volume"])
                self.assertEqual(candles["Close"].iloc[-1], 2425.0)

        asyncio.run(_run())

    def test_get_option_chain_mocked(self):
        """Test option chain mapping to UnifiedOptionData dataclasses."""
        async def _run():
            target_exp = date(2026, 9, 2)
            mock_options = [
                SimpleNamespace(
                    symbol="/GCJ26",
                    strike_price="2400.0",
                    option_type=SimpleNamespace(value="C"),
                    streamer_symbol="./GCZ6 C2400",
                    root_symbol="GC",
                    expiration_date=target_exp,
                ),
                SimpleNamespace(
                    symbol="/GCJ26",
                    strike_price="2400.0",
                    option_type=SimpleNamespace(value="P"),
                    streamer_symbol="./GCZ6 P2400",
                    root_symbol="GC",
                    expiration_date=target_exp,
                ),
            ]
            mock_chain = {target_exp: mock_options}

            with patch("adapters.tastytrade_adapter.get_future_option_chain", new=AsyncMock(return_value=mock_chain)), \
                 patch.object(self.adapter, "_ensure_connected", new=AsyncMock(return_value=True)):

                chain = await self.adapter.get_option_chain("GC", expiry=target_exp)
                self.assertEqual(len(chain), 2)

                call_opt = chain[0]
                self.assertEqual(call_opt.symbol, "GC")
                self.assertEqual(call_opt.strike, 2400.0)
                self.assertEqual(call_opt.option_type, "C")
                self.assertEqual(call_opt.expiry, target_exp)
                self.assertEqual(call_opt.multiplier, 100.0)
                self.assertEqual(call_opt.underlying_price, 2400.0)
                self.assertEqual(call_opt.provider, "tastytrade")

                put_opt = chain[1]
                self.assertEqual(put_opt.option_type, "P")

        asyncio.run(_run())

    def test_get_futures_price_mocked(self):
        """Test get_futures_price with chain median strike inference."""
        async def _run():
            target_exp = date.today()
            mock_options = [
                SimpleNamespace(strike_price="2400.0", option_type=SimpleNamespace(value="C")),
                SimpleNamespace(strike_price="2450.0", option_type=SimpleNamespace(value="C")),
                SimpleNamespace(strike_price="2500.0", option_type=SimpleNamespace(value="C")),
            ]
            mock_chain = {target_exp: mock_options}

            with patch("adapters.tastytrade_adapter.get_future_option_chain", new=AsyncMock(return_value=mock_chain)), \
                 patch.object(self.adapter, "_ensure_connected", new=AsyncMock(return_value=True)), \
                 patch.object(self.adapter, "get_front_month_symbol", new=AsyncMock(return_value="/GCV26")):

                fut_data = await self.adapter.get_futures_price("GC")
                self.assertIsInstance(fut_data, UnifiedFuturesData)
                self.assertEqual(fut_data.symbol, "GC")
                self.assertEqual(fut_data.price, 2450.0)
                self.assertEqual(fut_data.provider, "tastytrade")
                self.assertEqual(fut_data.raw.get("front_month"), "/GCV26")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
