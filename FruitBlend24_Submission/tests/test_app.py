"""Meaningful financial and boundary checks. python -m unittest discover -s tests -v"""
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import inventory_plan, read_data, scenario, numeric


class FinancialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read_data()

    def test_base_scenario_reconciles_to_export(self):
        result = scenario(self.data, {})['monthly']
        for got, expected in zip(result, self.data['forecast']):
            for key in ('revenue', 'gp', 'operating_profit', 'units_sold', 'waste_cost'):
                self.assertAlmostEqual(got[key], expected[key], places=4)

    def test_price_change_preserves_units_and_changes_net_revenue(self):
        result = scenario(self.data, {'price': ['10']})['monthly']
        for got, expected in zip(result, self.data['forecast']):
            self.assertAlmostEqual(got['units_sold'], expected['units_sold'], places=4)
            self.assertAlmostEqual(got['operating_profit'] - expected['operating_profit'], .1*(expected['revenue']-expected['commission']), places=4)

    def test_target_sku_does_not_change_other_volume(self):
        target = 'MixedBerryPremium'
        result = scenario(self.data, {'sku': [target], 'volume': ['-20']})['monthly']
        for got, base in zip(result, self.data['forecast']):
            target_volume = sum(r['units_sold'] for r in self.data['forecast_detail'] if r['sku'] == target and r['month'] == base['month'])
            self.assertAlmostEqual(got['units_sold'], base['units_sold'] - .2*target_volume, places=4)
            self.assertEqual(got['overhead'], base['overhead'])

    def test_waste_savings_not_double_counted(self):
        result = scenario(self.data, {'waste': ['25']})['monthly']
        for got, base in zip(result, self.data['forecast']):
            self.assertAlmostEqual(got['change_from_base'], base['waste_cost']*.25, places=4)

    def test_fruit_cost_inflation_includes_waste(self):
        result = scenario(self.data, {'fruit': ['10']})['monthly']
        for got, base in zip(result, self.data['forecast']):
            wasted_fruit = 0
            for r in self.data['forecast_detail']:
                if r['month'] == base['month']:
                    e = next(e for e in self.data['economics'] if (e['sku'],e['kitchen']) == (r['sku'],r['kitchen']))
                    wasted_fruit += r['units_wasted']*e['fruit_cost_per_cup_thb']
            self.assertAlmostEqual(got['change_from_base'], -.1*(base['fruit_cost']+wasted_fruit), places=4)

    def test_invalid_values_rejected(self):
        for value in ['nan', 'inf', '1000', '-1000', 'text']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                scenario(self.data, {'price': [value]})

    def test_unknown_sku_rejected(self):
        with self.assertRaises(ValueError):
            scenario(self.data, {'sku': ['unknown']})

    def test_targeted_plan_matches_independent_menu_scenarios(self):
        from app import TARGETED_PLAN
        base = sum(r['operating_profit'] for r in scenario(self.data, {'waste': ['25'], 'overhead': ['15']})['monthly'])
        expected = base
        for sku, assumptions in TARGETED_PLAN.items():
            changed = scenario(self.data, {'waste': ['25'], 'overhead': ['15'], 'sku': [sku], 'price': [str(assumptions['price_pct'])], 'volume': [str(assumptions['volume_pct'])]})
            expected += sum(r['operating_profit'] for r in changed['monthly']) - base
        actual = scenario(self.data, {'plan': ['targeted']})
        self.assertAlmostEqual(sum(r['operating_profit'] for r in actual['monthly']), expected, places=4)

    def test_inventory_never_orders_negative(self):
        got = inventory_plan(self.data, {'onhand': ['100000']})
        self.assertEqual(got['order_cup_equivalents'], 0)

    def test_inventory_existing_stock_deducted(self):
        base = inventory_plan(self.data, {})
        got = inventory_plan(self.data, {'onhand': ['3'], 'transit': ['2']})
        self.assertEqual(got['order_cup_equivalents'], max(0, base['order_cup_equivalents']-5))

    def test_short_shelf_life_flags_service_conflict(self):
        got = inventory_plan(self.data, {'lead': ['3'], 'review': ['1'], 'shelf': ['.25']})
        self.assertTrue(got['freshness_cap_binding'])
        self.assertTrue(got['horizon_exceeds_shelf_life'])

    def test_invalid_inventory_rejected(self):
        with self.assertRaises(ValueError):
            inventory_plan(self.data, {'service': ['100']})
        with self.assertRaises(ValueError):
            inventory_plan(self.data, {'kitchen': ['unknown']})

    def test_historical_bridge_and_checks(self):
        self.assertTrue(all(self.data['checks'].values()))
        a = self.data['audit']
        self.assertAlmostEqual(a['raw_revenue']-a['duplicate_revenue_removed']-a['out_of_scope_revenue_removed'], a['clean_revenue'], places=4)

    def test_forecast_dated_from_source_not_today(self):
        self.assertEqual(self.data['meta']['forecast_start'], '2026-09-01')
        self.assertEqual(self.data['meta']['forecast_end'], '2026-11-30')


if __name__ == '__main__':
    unittest.main()
