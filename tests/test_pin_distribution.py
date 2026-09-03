import unittest
from analytics.pin_risk import calc_pinning_probability_distribution

class TestPinDistribution(unittest.TestCase):
    def test_pin_distribution_probabilities(self):
        rows = [
            {'Strike': 2380.0, 'Type': 'C', 'Open_Interest': 100, 'IV': 0.18},
            {'Strike': 2400.0, 'Type': 'C', 'Open_Interest': 1500, 'IV': 0.18},
            {'Strike': 2400.0, 'Type': 'P', 'Open_Interest': 1200, 'IV': 0.18},
            {'Strike': 2420.0, 'Type': 'P', 'Open_Interest': 200, 'IV': 0.18},
        ]
        res = calc_pinning_probability_distribution(rows, spot=2395.0, dte=1.0)
        self.assertIn('pin_probabilities', res)
        self.assertIn('most_likely_pin_strike', res)
        self.assertEqual(res['most_likely_pin_strike'], 2400.0)

        # Sum of probabilities across strikes should equal ~100%
        total_p = sum(p['probability_pct'] for p in res['pin_probabilities'])
        self.assertAlmostEqual(total_p, 100.0, delta=1.0)

        # Top 3 strikes should be sorted descending by probability
        self.assertIn('top_3_pin_strikes', res)
        self.assertGreater(res['top_3_pin_strikes'][0]['probability_pct'], res['top_3_pin_strikes'][1]['probability_pct'])

if __name__ == '__main__':
    unittest.main()
