import unittest
import pandas as pd
import numpy as np
from analytics.vrp import calc_yang_zhang_rv, calc_parkinson_rv, calc_vrp, calc_iv_percentile_rank
from analytics.term_structure import calc_term_structure_slope, calc_25delta_skew
from analytics.order_flow import calc_volume_imbalance, detect_unusual_flow_spikes, calc_vpin_score
from alerts.engine import evaluate_market_alerts

class TestQuantModules(unittest.TestCase):
    def setUp(self):
        # Sample OHLC data
        dates = pd.date_range('2026-01-01', periods=30, freq='D')
        np.random.seed(42)
        prices = 100.0 * np.exp(np.cumsum(np.random.normal(0, 0.01, 30)))
        self.ohlc_df = pd.DataFrame({
            'Open': prices * (1 + np.random.normal(0, 0.002, 30)),
            'High': prices * (1 + abs(np.random.normal(0, 0.005, 30))),
            'Low': prices * (1 - abs(np.random.normal(0, 0.005, 30))),
            'Close': prices
        }, index=dates)

    def test_yang_zhang_rv(self):
        rv = calc_yang_zhang_rv(self.ohlc_df, window=20)
        self.assertGreater(rv, 0.0)
        self.assertLess(rv, 1.0)

    def test_vrp_calculation(self):
        res = calc_vrp(iv=0.20, rv=0.15)
        self.assertEqual(res['vrp_pct'], 5.0)
        self.assertEqual(res['regime'], 'EXPENSIVE')
        self.assertEqual(res['signal'], 'SELL_PREMIUM')

        res_cheap = calc_vrp(iv=0.10, rv=0.16)
        self.assertEqual(res_cheap['regime'], 'CHEAP')
        self.assertEqual(res_cheap['signal'], 'BUY_PREMIUM')

    def test_iv_percentile(self):
        hist = [0.12, 0.15, 0.18, 0.22, 0.25]
        res = calc_iv_percentile_rank(0.18, hist)
        self.assertAlmostEqual(res['iv_percentile'], 40.0, delta=1.0)
        self.assertAlmostEqual(res['iv_rank'], 46.2, delta=1.0)

    def test_term_structure(self):
        expiries = [
            {'dte': 7, 'iv': 0.15, 'expiry': '2026-06-10'},
            {'dte': 37, 'iv': 0.18, 'expiry': '2026-07-10'}
        ]
        res = calc_term_structure_slope(expiries)
        self.assertEqual(res['regime'], 'CONTANGO')
        self.assertGreater(res['slope_30d'], 0)

    def test_order_flow(self):
        imb = calc_volume_imbalance(call_vol=1500, put_vol=500)
        self.assertEqual(imb['imbalance'], 0.5)
        self.assertEqual(imb['bias'], 'AGGRESSIVE_CALL_FLOW')

    def test_unusual_flow(self):
        rows = [
            {'Strike': 2400, 'Type': 'C', 'Volume': 500, 'Open_Interest': 50},
            {'Strike': 2450, 'Type': 'P', 'Volume': 10, 'Open_Interest': 100}
        ]
        anomalies = detect_unusual_flow_spikes(rows, volume_to_oi_threshold=2.0)
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]['strike'], 2400)

    def test_alerts_engine(self):
        alerts = evaluate_market_alerts(
            asset_symbol='GC',
            price=2455.0,
            bias_label='Strong BULL',
            call_wall=2450.0,
            put_wall=2380.0,
            gex_regime='VOLATILE',
            vrp_data={'vrp_pct': 5.2},
            flow_anomalies=[{'type': 'C', 'strike': 2450, 'vol_oi_ratio': 3.5, 'volume': 200}],
            prev_bias_label='Mild BEAR'
        )
        self.assertGreaterEqual(len(alerts), 3)
        categories = [a['category'] for a in alerts]
        self.assertIn('WALL_BREACH', categories)
        self.assertIn('REGIME_FLIP', categories)
        self.assertIn('BIAS_REVERSAL', categories)

if __name__ == '__main__':
    unittest.main()
