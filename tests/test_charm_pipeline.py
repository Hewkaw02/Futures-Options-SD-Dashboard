import unittest
from update_dashboard import parse_option_data_csv
import tempfile
import os

class TestCharmPipeline(unittest.TestCase):
    def test_charm_parsed_and_aggregated(self):
        csv_content = """Strike,Type,OI,Volume,GEX,Vanna,DEX,Charm,IV
2400.0,Call,100,50,150.0,25.0,-20000.0,12.5,0.20
2400.0,Put,80,40,-120.0,-20.0,18000.0,-8.0,0.20
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            res = parse_option_data_csv(temp_path)
            self.assertIn('charm', res)
            self.assertIn('charm_exp', res['charm'])
            self.assertIn('total_overnight_flow_usd', res['charm'])
            self.assertAlmostEqual(res['charm']['total_overnight_flow_usd'], 4.5, delta=0.1)
        finally:
            os.remove(temp_path)

if __name__ == '__main__':
    unittest.main()
