import unittest
from analytics.exposure import calculate_dealer_exposures

class TestAsymmetricDealerExposure(unittest.TestCase):
    def test_asymmetric_dealer_positioning(self):
        # OTM Call (Strike 2500 vs Spot 2400): Customers sell covered calls -> Dealer is LONG call (+1)
        # Therefore dealer gamma should be POSITIVE
        exp_otm_call = calculate_dealer_exposures(
            oi=100.0, delta=0.30, gamma=0.002, vega=10.0, vanna=0.05, charm=-0.01,
            spot=2400.0, multiplier=100.0, option_type="C",
            strike=2500.0, dealer_model="asymmetric"
        )
        self.assertGreater(exp_otm_call['gex'], 0, "Dealer should be Long Gamma on OTM Calls")

        # ATM/ITM Call (Strike 2300 vs Spot 2400): Customers buy calls -> Dealer is SHORT call (-1)
        exp_itm_call = calculate_dealer_exposures(
            oi=100.0, delta=0.70, gamma=0.002, vega=10.0, vanna=0.05, charm=-0.01,
            spot=2400.0, multiplier=100.0, option_type="C",
            strike=2300.0, dealer_model="asymmetric"
        )
        self.assertLess(exp_itm_call['gex'], 0, "Dealer should be Short Gamma on ITM Calls")

        # Put Option (Strike 2300 vs Spot 2400): Customers buy put hedges -> Dealer is SHORT put (-1)
        exp_put = calculate_dealer_exposures(
            oi=100.0, delta=-0.30, gamma=0.002, vega=10.0, vanna=0.05, charm=0.01,
            spot=2400.0, multiplier=100.0, option_type="P",
            strike=2300.0, dealer_model="asymmetric"
        )
        self.assertLess(exp_put['gex'], 0, "Dealer should be Short Gamma on Puts")

if __name__ == '__main__':
    unittest.main()
