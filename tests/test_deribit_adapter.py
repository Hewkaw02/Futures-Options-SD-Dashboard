"""
Unit and Integration tests for DeribitAdapter.
"""
import unittest
import asyncio
from datetime import date
import pandas as pd

from adapters import (
    AdapterRegistry,
    BaseDataAdapter,
    UnifiedOptionData,
    UnifiedFuturesData,
    AssetClass,
    DeribitAdapter,
    parse_deribit_instrument_name,
    unified_to_analytics_rows,
    unified_chain_to_tastytrade_format,
)


class TestDeribitAdapter(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_registration(self):
        """Verify DeribitAdapter is properly registered in AdapterRegistry."""
        self.assertIn("deribit", AdapterRegistry.list_providers())
        adapter = AdapterRegistry.get("deribit")
        self.assertIsInstance(adapter, DeribitAdapter)
        self.assertIsInstance(adapter, BaseDataAdapter)
        self.assertEqual(adapter.get_provider_name(), "Deribit")
        self.assertEqual(adapter.get_asset_class(), AssetClass.CRYPTO_OPTIONS)
        self.assertIn("deribit", AdapterRegistry.list_by_asset_class(AssetClass.CRYPTO_OPTIONS))

    def test_instrument_parsing(self):
        """Test Deribit option instrument name parser."""
        # Standard format
        parsed1 = parse_deribit_instrument_name("BTC-27SEP26-100000-C")
        self.assertIsNotNone(parsed1)
        sym1, exp1, strike1, opt_type1 = parsed1
        self.assertEqual(sym1, "BTC")
        self.assertEqual(exp1, date(2026, 9, 27))
        self.assertEqual(strike1, 100000.0)
        self.assertEqual(opt_type1, "C")

        # Single digit day format
        parsed2 = parse_deribit_instrument_name("ETH-2SEP26-2500-P")
        self.assertIsNotNone(parsed2)
        sym2, exp2, strike2, opt_type2 = parsed2
        self.assertEqual(sym2, "ETH")
        self.assertEqual(exp2, date(2026, 9, 2))
        self.assertEqual(strike2, 2500.0)
        self.assertEqual(opt_type2, "P")

        # Invalid formats
        self.assertIsNone(parse_deribit_instrument_name("BTC-PERPETUAL"))
        self.assertIsNone(parse_deribit_instrument_name("INVALID-NAME"))
        self.assertIsNone(parse_deribit_instrument_name(""))

    def test_capabilities(self):
        """Check capabilities dictionary."""
        adapter = DeribitAdapter()
        caps = adapter.get_capabilities()
        self.assertEqual(caps["provider"], "Deribit")
        self.assertEqual(caps["asset_class"], "crypto_options")
        self.assertTrue(caps["options_chain"])
        self.assertTrue(caps["greeks_included"])
        self.assertTrue(caps["free_tier"])
        self.assertFalse(caps["auth_required"])

    def test_live_connection_and_chain(self):
        """Live test against Deribit public API."""
        async def run_async():
            adapter = DeribitAdapter()
            try:
                # 1. Test connect
                connected = await adapter.connect()
                self.assertTrue(connected)
                self.assertTrue(adapter.is_connected)

                # 2. Test futures price
                btc_fut = await adapter.get_futures_price("BTC")
                self.assertIsInstance(btc_fut, UnifiedFuturesData)
                self.assertEqual(btc_fut.symbol, "BTC")
                self.assertGreater(btc_fut.price, 0)
                self.assertEqual(btc_fut.provider, "deribit")

                # 3. Test option chain
                chain = await adapter.get_option_chain("BTC")
                self.assertIsInstance(chain, list)
                self.assertGreater(len(chain), 0)
                first_opt = chain[0]
                self.assertIsInstance(first_opt, UnifiedOptionData)
                self.assertEqual(first_opt.symbol, "BTC")
                self.assertIn(first_opt.option_type, ["C", "P"])
                self.assertGreater(first_opt.strike, 0)
                self.assertEqual(first_opt.multiplier, 1.0)
                self.assertEqual(first_opt.provider, "deribit")

                # 4. Test filtering by expiration
                expirations = await adapter.get_expirations("BTC")
                self.assertGreater(len(expirations), 0)
                target_exp = expirations[0]
                filtered_chain = await adapter.get_option_chain("BTC", expiry=target_exp)
                self.assertGreater(len(filtered_chain), 0)
                for opt in filtered_chain:
                    self.assertEqual(opt.expiry, target_exp)

                # 5. Test historical candles
                candles = await adapter.get_historical_candles("BTC", period="7d", interval="1d")
                self.assertIsInstance(candles, pd.DataFrame)
                self.assertListEqual(list(candles.columns), ["Open", "High", "Low", "Close", "Volume"])
                self.assertGreater(len(candles), 0)

                # 6. Test bridge compatibility
                analytics_rows = unified_to_analytics_rows(filtered_chain)
                self.assertGreater(len(analytics_rows), 0)
                self.assertIn("Strike", analytics_rows[0])
                self.assertIn("IV", analytics_rows[0])

                tasty_chain = unified_chain_to_tastytrade_format(filtered_chain)
                self.assertIn(target_exp, tasty_chain)

                # 7. Test Deribit specific methods
                vol = await adapter.get_historical_volatility("BTC")
                self.assertIsInstance(vol, list)
                self.assertGreater(len(vol), 0)

            finally:
                await adapter.disconnect()
                self.assertFalse(adapter.is_connected)

        self.loop.run_until_complete(run_async())


if __name__ == "__main__":
    unittest.main()
