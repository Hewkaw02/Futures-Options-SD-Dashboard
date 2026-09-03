import unittest
from analytics.scenarios import run_stress_scenarios

class TestVannaRallyScenario(unittest.TestCase):
    def test_iv_shock_simulation(self):
        rows = [
            {'Strike': 2400.0, 'Type': 'C', 'Open_Interest': 500, 'IV': 0.20},
            {'Strike': 2350.0, 'Type': 'P', 'Open_Interest': 800, 'IV': 0.25}
        ]
        # Test with IV shock scenarios (-5% IV crush, e.g. post-FOMC)
        res = run_stress_scenarios(
            options_rows=rows, spot=2400.0, dte=5.0, multiplier=100.0,
            iv_shifts=[-0.05, 0.0, +0.05]
        )
        self.assertIn('vanna_rally_scenarios', res)
        iv_crush = [s for s in res['vanna_rally_scenarios'] if s['iv_shift_pct'] == -5.0]
        self.assertEqual(len(iv_crush), 1)
        self.assertIn('dealer_rebalance_usd', iv_crush[0])
        self.assertIn('vanna_rally_direction', iv_crush[0])

if __name__ == '__main__':
    unittest.main()
