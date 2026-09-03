"""Unit tests for the adapter base infrastructure."""
import unittest
from datetime import date, datetime
from adapters.base import UnifiedOptionData, UnifiedFuturesData, AssetClass
from adapters.registry import AdapterRegistry
from adapters.bridge import (
    unified_chain_to_tastytrade_format,
    unified_to_analytics_rows,
    unified_to_master_report_records,
    unified_futures_to_mark_price,
)


class TestUnifiedOptionData(unittest.TestCase):
    def test_creation_with_all_fields(self):
        opt = UnifiedOptionData(
            symbol="GC", strike=2500.0, option_type="C",
            expiry=date(2026, 12, 31), bid=12.0, ask=13.0,
            volume=100, open_interest=500, iv=0.15,
            delta=0.45, gamma=0.002, theta=-0.05, vega=10.0,
            underlying_price=2480.0, multiplier=100.0,
            provider="databento",
        )
        self.assertEqual(opt.symbol, "GC")
        self.assertEqual(opt.strike, 2500.0)
        self.assertEqual(opt.option_type, "C")
        self.assertEqual(opt.provider, "databento")
        self.assertEqual(opt.multiplier, 100.0)

    def test_mark_price_mid(self):
        opt = UnifiedOptionData(
            symbol="ES", strike=5000.0, option_type="C",
            expiry=date(2026, 12, 31), bid=20.0, ask=22.0,
        )
        self.assertAlmostEqual(opt.mark, 21.0)

    def test_mark_price_fallback_to_last(self):
        opt = UnifiedOptionData(
            symbol="ES", strike=5000.0, option_type="P",
            expiry=date(2026, 12, 31), last=25.0,
        )
        self.assertEqual(opt.mark, 25.0)

    def test_mark_price_zero_bid_ask(self):
        opt = UnifiedOptionData(
            symbol="NQ", strike=18000.0, option_type="C",
            expiry=date(2026, 12, 31), bid=0.0, ask=0.0, last=10.0,
        )
        self.assertEqual(opt.mark, 10.0)

    def test_has_greeks_false(self):
        opt = UnifiedOptionData(
            symbol="NQ", strike=18000.0, option_type="C",
            expiry=date(2026, 12, 31),
        )
        self.assertFalse(opt.has_greeks)

    def test_has_greeks_true(self):
        opt = UnifiedOptionData(
            symbol="NQ", strike=18000.0, option_type="C",
            expiry=date(2026, 12, 31), delta=0.45,
        )
        self.assertTrue(opt.has_greeks)

    def test_dte_calculation(self):
        future_date = date(2099, 12, 31)
        opt = UnifiedOptionData(
            symbol="GC", strike=2500.0, option_type="C",
            expiry=future_date,
        )
        self.assertGreater(opt.dte, 0)

    def test_dte_past_date(self):
        past_date = date(2020, 1, 1)
        opt = UnifiedOptionData(
            symbol="GC", strike=2500.0, option_type="C",
            expiry=past_date,
        )
        self.assertEqual(opt.dte, 0)

    def test_default_values(self):
        opt = UnifiedOptionData(
            symbol="BTC", strike=100000.0, option_type="C",
            expiry=date(2026, 12, 31),
        )
        self.assertEqual(opt.bid, 0.0)
        self.assertEqual(opt.volume, 0)
        self.assertEqual(opt.iv, 0.0)
        self.assertEqual(opt.multiplier, 1.0)
        self.assertEqual(opt.provider, "")
        self.assertEqual(opt.raw, {})


class TestUnifiedFuturesData(unittest.TestCase):
    def test_creation(self):
        fut = UnifiedFuturesData(
            symbol="GC", price=2480.0, bid=2479.8, ask=2480.2,
            volume=150000, high=2495.0, low=2470.0, open=2475.0,
            provider="tastytrade",
        )
        self.assertEqual(fut.price, 2480.0)
        self.assertEqual(fut.symbol, "GC")
        self.assertEqual(fut.provider, "tastytrade")

    def test_default_values(self):
        fut = UnifiedFuturesData(symbol="ES", price=5000.0)
        self.assertEqual(fut.bid, 0.0)
        self.assertEqual(fut.volume, 0)
        self.assertEqual(fut.change, 0.0)


class TestAssetClass(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(AssetClass.FUTURES_OPTIONS.value, "futures_options")
        self.assertEqual(AssetClass.CRYPTO_OPTIONS.value, "crypto_options")
        self.assertEqual(AssetClass.EQUITY_OPTIONS.value, "equity_options")
        self.assertEqual(AssetClass.FUTURES.value, "futures")
        self.assertEqual(AssetClass.EQUITY.value, "equity")


class TestAdapterRegistry(unittest.TestCase):
    def test_list_providers_returns_list(self):
        providers = AdapterRegistry.list_providers()
        self.assertIsInstance(providers, list)

    def test_unknown_provider_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            AdapterRegistry.get("nonexistent_provider_xyz_999")
        self.assertIn("nonexistent_provider_xyz_999", str(ctx.exception))
        self.assertIn("Available", str(ctx.exception))

    def test_list_all_info_returns_dicts(self):
        info = AdapterRegistry.list_all_info()
        self.assertIsInstance(info, list)
        if info:
            self.assertIn("name", info[0])
            self.assertIn("env_keys", info[0])


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.options = [
            UnifiedOptionData(
                symbol="GC", strike=2500.0, option_type="C",
                expiry=date(2026, 9, 5), volume=100, open_interest=500,
                iv=0.15, bid=12.0, ask=13.0,
            ),
            UnifiedOptionData(
                symbol="GC", strike=2500.0, option_type="P",
                expiry=date(2026, 9, 5), volume=80, open_interest=300,
                iv=0.16, bid=8.0, ask=9.0,
            ),
            UnifiedOptionData(
                symbol="GC", strike=2550.0, option_type="C",
                expiry=date(2026, 9, 12), volume=50, open_interest=200,
                iv=0.14, bid=5.0, ask=6.0,
            ),
        ]

    def test_to_tastytrade_format_groups_by_expiry(self):
        chain = unified_chain_to_tastytrade_format(self.options)
        self.assertIn(date(2026, 9, 5), chain)
        self.assertIn(date(2026, 9, 12), chain)
        self.assertEqual(len(chain[date(2026, 9, 5)]), 2)
        self.assertEqual(len(chain[date(2026, 9, 12)]), 1)

    def test_to_tastytrade_format_mock_attributes(self):
        chain = unified_chain_to_tastytrade_format(self.options)
        mock_opt = chain[date(2026, 9, 5)][0]
        self.assertEqual(mock_opt.strike_price, "2500.0")
        self.assertEqual(mock_opt.option_type.value, "C")
        self.assertTrue(hasattr(mock_opt, "streamer_symbol"))

    def test_to_analytics_rows(self):
        rows = unified_to_analytics_rows(self.options)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Strike"], 2500.0)
        self.assertEqual(rows[0]["Type"], "C")
        self.assertEqual(rows[0]["Open_Interest"], 500)
        self.assertEqual(rows[0]["Volume"], 100)
        # Also check lowercase keys (used by some analytics modules)
        self.assertEqual(rows[0]["oi"], 500)
        self.assertEqual(rows[0]["vol"], 100)

    def test_to_master_report_records(self):
        records = unified_to_master_report_records(self.options)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["Type"], "C")
        self.assertEqual(records[0]["OI"], 500)
        self.assertEqual(records[0]["Vol"], 100)
        self.assertEqual(records[0]["Strike"], 2500.0)

    def test_futures_to_mark_price_mid(self):
        fut = UnifiedFuturesData(
            symbol="GC", price=2480.0, bid=2479.0, ask=2481.0,
        )
        self.assertAlmostEqual(unified_futures_to_mark_price(fut), 2480.0)

    def test_futures_to_mark_price_fallback(self):
        fut = UnifiedFuturesData(symbol="ES", price=5000.0)
        self.assertEqual(unified_futures_to_mark_price(fut), 5000.0)


if __name__ == "__main__":
    unittest.main()
