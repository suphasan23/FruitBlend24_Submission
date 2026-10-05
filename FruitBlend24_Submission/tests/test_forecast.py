"""No future targets may affect forecasts made at a cutoff."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from analysis import predict


class ForecastTests(unittest.TestCase):
    def test_future_sales_do_not_leak_into_prediction(self):
        dates = pd.date_range('2026-01-01', periods=70)
        grid = pd.DataFrame({'date': dates, 'kitchen': 'A', 'sku': 'X', 'units_sold': 10.0, 'dow': dates.dayofweek})
        cutoff = dates[56]
        expected = predict(grid, cutoff, dates[56:], 'weekday', 28)
        grid.loc[grid.date >= cutoff, 'units_sold'] = 99999
        actual = predict(grid, cutoff, dates[56:], 'weekday', 28)
        pd.testing.assert_frame_equal(actual, expected)
        self.assertTrue(actual.predicted_units.eq(10).all())

    def test_insufficient_training_is_explicit_error(self):
        dates = pd.date_range('2026-01-01', periods=2)
        grid = pd.DataFrame({'date': dates, 'kitchen': 'A', 'sku': 'X', 'units_sold': 10.0, 'dow': dates.dayofweek})
        with self.assertRaises(ValueError):
            predict(grid, dates[0], dates, 'weekday', 28)


if __name__ == '__main__':
    unittest.main()
