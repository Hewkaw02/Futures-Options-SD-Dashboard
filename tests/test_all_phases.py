import unittest
import pandas as pd
import numpy as np
from analytics.correlation import calc_asset_correlations
from analytics.scenarios import run_stress_scenarios
from analytics.pin_risk import calc_pin_risk
from analytics.monte_carlo import simulate_price_cones
from ml.features import extract_quant_feature_vector
from ml.regime_classifier import predict_market_regime
from alerts.dispatcher import format_discord_payload, format_telegram_payload, format_line_notify_payload

class TestAllPhases(unittest.TestCase):
    def test_correlation(self):
        dates = pd.date_range('2026-01-01', periods=30, freq='D')
        np.random.seed(42)
        p1 = 100 * np.exp(np.cumsum(np.random.normal(0, 0.01, 30)))
        p2 = 100 * np.exp(np.cumsum(np.random.normal(0, 0.01, 30)))
        candles = {
            'GC': pd.DataFrame({'Close': p1}, index=dates),
            'ES': pd.DataFrame({'Close': p2}, index=dates),
        }
        res = calc_asset_correlations(candles)
        self.assertIn('gc_es_corr', res)
        self.assertIn('macro_regime', res)

    def test_scenarios(self):
        rows = [
            {'Strike': 2400.0, 'Type': 'C', 'Open_Interest': 100, 'IV': 0.20},
            {'Strike': 2350.0, 'Type': 'P', 'Open_Interest': 150, 'IV': 0.22}
        ]
        res = run_stress_scenarios(rows, spot=2380.0, dte=5.0, multiplier=100.0)
        self.assertEqual(len(res['scenarios']), 7)
        self.assertIn('dealer_delta_hedge_demand', res['scenarios'][0])

    def test_pin_risk(self):
        rows = [
            {'Strike': 2400.0, 'Open_Interest': 500},
            {'Strike': 2450.0, 'Open_Interest': 50}
        ]
        res = calc_pin_risk(rows, spot=2400.0, dte=1.0, max_pain_strike=2400.0)
        self.assertGreater(res['pin_score'], 0)
        self.assertTrue(res['pin_magnet_active'])

    def test_monte_carlo(self):
        res = simulate_price_cones(spot=2400.0, iv=0.20, days_horizon=30, num_paths=1000, call_wall=2450.0, put_wall=2350.0)
        self.assertGreaterEqual(len(res['cones']), 5)
        self.assertIn('prob_touch_call_wall_pct', res['barrier_odds'])
        self.assertIn('prob_touch_put_wall_pct', res['barrier_odds'])

    def test_ml_regime_classifier(self):
        feats = extract_quant_feature_vector(
            bias={'price': 2400.0, 'wall_resistance': 2450.0, 'wall_support': 2350.0, 'pcr_vol': 0.6, 'gex': 'STABLE'},
            vrp={'vrp_pct': 4.0, 'iv_pct': 18.0},
            skew={'risk_reversal_25d': 1.5, 'butterfly_25d': 2.0},
            flow={'imbalance': {'imbalance': 0.4}},
            corr={},
            pin={'pin_score': 30.0}
        )
        pred = predict_market_regime(feats)
        self.assertIn('regime', pred)
        self.assertGreater(pred['confidence_pct'], 0)
        self.assertAlmostEqual(pred['prob_bull'] + pred['prob_bear'] + pred['prob_range'], 1.0, delta=0.01)

    def test_alert_dispatchers(self):
        alerts = [{'severity': 'CRITICAL', 'title': 'Test Breach', 'detail': 'Price breached wall', 'asset': 'GC', 'timestamp': '2026-09-01'}]
        d_pay = format_discord_payload(alerts)
        t_pay = format_telegram_payload(alerts)
        l_pay = format_line_notify_payload(alerts)
        self.assertIn('embeds', d_pay)
        self.assertIn('CRITICAL', t_pay)
        self.assertIn('Test Breach', l_pay)

if __name__ == '__main__':
    unittest.main()
