"""Unit tests for Databento Adapter."""
import unittest
from datetime import date
from adapters.databento_adapter import DatabentoAdapter, SYMBOL_MAP, CONTRACT_MULTIPLIERS
from adapters.base import AssetClass, UnifiedOptionData, UnifiedFuturesData
from adapters.registry import AdapterRegistry


class TestDatabentoAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = DatabentoAdapter(api_key="db-test-key-mock")

    def test_registration(self):
        self.assertIn("databento", AdapterRegistry.list_providers())
        inst = AdapterRegistry.get("databento", api_key="db-test")
        self.assertIsInstance(inst, DatabentoAdapter)

    def test_provider_metadata(self):
        self.assertEqual(self.adapter.get_provider_name(), "Databento")
        self.assertEqual(self.adapter.get_asset_class(), AssetClass.FUTURES_OPTIONS)
        self.assertIn("GC", self.adapter.get_supported_symbols())
        self.assertIn("ES", self.adapter.get_supported_symbols())
        self.assertIn("NQ", self.adapter.get_supported_symbols())

    def test_capabilities(self):
        caps = self.adapter.get_capabilities()
        self.assertTrue(caps["options_chain"])
        self.assertTrue(caps["historical"])
        self.assertTrue(caps["streaming"])
        self.assertFalse(caps["greeks_included"])  # By design (raw feed)

    def test_symbol_and_multiplier_mappings(self):
        self.assertEqual(SYMBOL_MAP["GC"]["opt"], "GC.OPT")
        self.assertEqual(SYMBOL_MAP["ES"]["opt"], "ES.OPT")
        self.assertEqual(SYMBOL_MAP["NQ"]["opt"], "NQ.OPT")
        self.assertEqual(CONTRACT_MULTIPLIERS["GC"], 100.0)
        self.assertEqual(CONTRACT_MULTIPLIERS["ES"], 50.0)
        self.assertEqual(CONTRACT_MULTIPLIERS["NQ"], 20.0)

    def test_period_parser(self):
        self.assertEqual(DatabentoAdapter._parse_period("30d"), 30)
        self.assertEqual(DatabentoAdapter._parse_period("2w"), 14)
        self.assertEqual(DatabentoAdapter._parse_period("1m"), 30)
        self.assertEqual(DatabentoAdapter._parse_period("1y"), 365)


if __name__ == "__main__":
    unittest.main()
