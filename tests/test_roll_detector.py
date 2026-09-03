import unittest
from analytics.order_flow import detect_calendar_roll_activity

class TestRollDetector(unittest.TestCase):
    def test_calendar_roll_detection(self):
        # Front month losing 500 contracts, Back month gaining 480 contracts at 2400 strike
        front_changes = {2400.0: -500.0, 2450.0: -50.0}
        back_changes = {2400.0: +480.0, 2450.0: +20.0}

        rolls = detect_calendar_roll_activity(front_changes, back_changes, min_roll_contracts=100.0)
        self.assertEqual(len(rolls), 1)
        self.assertEqual(rolls[0]['strike'], 2400.0)
        self.assertEqual(rolls[0]['roll_status'], 'ACTIVE_CALENDAR_ROLL')
        self.assertAlmostEqual(rolls[0]['roll_ratio'], 0.96, delta=0.05)

if __name__ == '__main__':
    unittest.main()
