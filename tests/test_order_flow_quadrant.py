import unittest
from analytics.order_flow import classify_oi_volume_quadrant, decompose_strike_flow

class TestOrderFlowQuadrant(unittest.TestCase):
    def test_quadrant_classification(self):
        # High vol + Positive Delta OI = Accumulation
        res1 = classify_oi_volume_quadrant(volume=500, delta_oi=300, min_vol=50)
        self.assertEqual(res1['quadrant'], 'ACCUMULATION')
        self.assertEqual(res1['badge'], '🟢 ACCUMULATING')

        # High vol + Negative Delta OI = Liquidation
        res2 = classify_oi_volume_quadrant(volume=500, delta_oi=-300, min_vol=50)
        self.assertEqual(res2['quadrant'], 'LIQUIDATION')
        self.assertEqual(res2['badge'], '🔴 DE-RISKING')

        # High vol + Flat Delta OI = Day Trading
        res3 = classify_oi_volume_quadrant(volume=500, delta_oi=5, min_vol=50)
        self.assertEqual(res3['quadrant'], 'DAY_TRADING')
        self.assertEqual(res3['badge'], '⚪ CHURN/SCALP')

    def test_decompose_strike_flow(self):
        records = [
            {'strike': 2400.0, 'call_vol': 800, 'call_doi': 600, 'put_vol': 100, 'put_doi': -50},
            {'strike': 2350.0, 'call_vol': 50, 'call_doi': 0, 'put_vol': 900, 'put_doi': 700},
        ]
        res = decompose_strike_flow(records)
        self.assertIn('dominant_regime', res)
        self.assertIn('accumulation_strikes', res)
        self.assertEqual(len(res['accumulation_strikes']), 2)

if __name__ == '__main__':
    unittest.main()
