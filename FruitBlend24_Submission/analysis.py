"""Reproducible FruitBlend24 case analysis. No network calls or source modifications."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'data' / 'FruitBlend24_Intern_Case_Data.xlsx'
RESULTS = ROOT / 'results'
ALIASES = {
    'Watermelon': ['Watermelon Ice', 'watermelon ice', 'Watermelon Smoothie', 'Watermelon smoothy', 'แตงโมปั่น', 'แตงโมปั่นสด', 'แตงโมปั่น (ไซส์ M)'],
    'Pineapple': ['Pineapple Ice', 'Pineapple Smoothie', 'Pineapple smoothie ', 'pineapple ice', 'สับปะรดปั่น', 'สัปปะรดปั่น'],
    'Guava': ['Guava Ice', 'guava ice', 'Guava Smoothie', 'ฝรั่งปั่น', 'ฝรั่งปั่น (ใส่เกลือ)'],
    'PassionFruit': ['Passion Fruit Ice', 'Passion Fruit Smoothie', 'passionfruit ice', 'เสาวรสปั่น', 'เสาวรสปั่นเข้มข้น'],
    'MixedBerryPremium': ['Mixed Berry Premium', 'Mixed Berry (Premium)', 'berry premium smoothie', 'เบอร์รี่ปั่นพรีเมียม', 'เบอร์รี่รวมพรีเมียม'],
}
OUT_OF_SCOPE = {'แก้วเปล่า', 'น้ำส้มปั่น (เมนูทดลอง)', 'Combo Set A (2 แก้ว)'}
SUM_COLS = ['units_sold', 'revenue', 'fruit_cost', 'packaging_cost', 'labor_cost', 'commission', 'contribution', 'units_wasted', 'waste_cost', 'gp']


def require(condition, message):
    if not bool(condition):
        raise ValueError(message)


def records(frame):
    return json.loads(frame.to_json(orient='records', date_format='iso', double_precision=8))


def normalize(value):
    return ' '.join(str(value).strip().casefold().split())


def load_and_clean(source):
    sheets = pd.read_excel(source, sheet_name=None, engine='openpyxl')
    raw = sheets['orders_hourly'].copy()
    raw['source_row'] = np.arange(2, len(raw) + 2)
    original_cols = [c for c in raw if c != 'source_row']
    duplicate = raw.duplicated(original_cols)
    excluded = raw.loc[duplicate].assign(exclusion_reason='exact_duplicate')
    orders = raw.loc[~duplicate].copy()
    mapping = {normalize(alias): sku for sku, aliases in ALIASES.items() for alias in aliases}
    orders['sku'] = orders.item_name_raw.map(lambda v: mapping.get(normalize(v)))
    unknown = orders.sku.isna()
    unexpected = set(orders.loc[unknown, 'item_name_raw']) - OUT_OF_SCOPE
    require(not unexpected, f'Unmapped new product names: {unexpected}. Review ALIASES before analysis.')
    excluded = pd.concat([excluded, orders.loc[unknown].assign(exclusion_reason='outside_five_menu_scope')], ignore_index=True)
    orders = orders.loc[~unknown].copy()
    orders['date'] = pd.to_datetime(orders.date, errors='raise').dt.normalize()
    require(not orders[original_cols + ['sku']].isna().any().any(), 'Missing required order values')
    require(orders.hour.between(0, 23).all(), 'Invalid hour')
    require((orders.day_of_week == orders.date.dt.dayofweek).all(), 'Weekday/date mismatch')
    require((orders.price_thb > 0).all() and (orders.units_sold > 0).all(), 'Non-positive sales in core menu')
    require((orders.units_sold % 1 == 0).all(), 'Non-integer cups')
    require(np.allclose(orders.price_thb * orders.units_sold, orders.gross_revenue_thb, atol=.011, rtol=0), 'Revenue does not equal price x units')
    parts = orders.rate_code.str.extract(r'^(LM|GB)-(RC\d{3})(?:-([A-Z]{2}))?$')
    parts.columns = ['platform_code', 'base_code', 'sku_code']
    orders = pd.concat([orders, parts], axis=1)
    require(orders.platform_code.notna().all(), 'Invalid rate-code syntax')
    skucodes = sheets['sku_code_dim'].set_index('sku_code').sku.to_dict()
    coded = orders.sku_code.notna()
    require((orders.loc[coded, 'sku_code'].map(skucodes) == orders.loc[coded, 'sku']).all(), 'Promo SKU mismatch')
    require(((orders.base_code == 'RC101') == coded).all(), 'SKU suffix is required for RC101 only')
    for name, key in [('platform_commission_rate', 'platform_code'), ('rate_code_dim', 'base_code')]:
        orders = orders.merge(sheets[name], on=key, how='left', validate='many_to_one')
    require(orders[['commission_rate', 'discount_pct']].notna().all().all(), 'Unknown promo/platform')
    costs = sheets['weekly_fruit_cost'].copy()
    costs['week_start'] = pd.to_datetime(costs.week_start)
    require((costs.week_start.dt.dayofweek == 0).all(), 'Fruit week must begin Monday')
    require(costs.fruit_cost_per_cup_thb.gt(0).all(), 'Invalid fruit cost')
    orders['week_start'] = orders.date - pd.to_timedelta(orders.date.dt.dayofweek, unit='D')
    orders = orders.merge(costs, on=['week_start', 'sku'], how='left', validate='many_to_one')
    orders['fruit_cost_imputed'] = orders.fruit_cost_per_cup_thb.isna()
    missing_cost = orders.fruit_cost_imputed
    # The launch was Sunday 1 Mar; the first supplied berry cost starts Monday 2 Mar.
    # Apply one explicit historical estimate, never a blanket fill for other missing weeks.
    if missing_cost.any():
        require((orders.loc[missing_cost, 'sku'].eq('MixedBerryPremium') & orders.loc[missing_cost, 'date'].eq(pd.Timestamp('2026-03-01'))).all(), 'Unexpected missing fruit cost outside the documented launch day')
        launch_cost = costs[(costs.sku == 'MixedBerryPremium') & (costs.week_start == pd.Timestamp('2026-03-02'))]
        require(len(launch_cost) == 1, 'Missing launch cost reference')
        orders.loc[missing_cost, 'fruit_cost_per_cup_thb'] = float(launch_cost.iloc[0].fruit_cost_per_cup_thb)
    assumptions = sheets['cost_assumptions'].iloc[:5].copy()
    orders = orders.merge(assumptions, on='sku', how='left', validate='many_to_one')
    costcols = ['fruit_cost_per_cup_thb', 'packaging_cost_per_cup_thb', 'labor_cost_per_cup_thb', 'base_price_thb']
    require(orders[costcols].notna().all().all(), 'Unmatched costs. Do not replace with zero.')
    for c in costcols:
        orders[c] = pd.to_numeric(orders[c], errors='raise')
    orders['expected_price'] = orders.base_price_thb * (1 - orders.discount_pct)
    price_exceptions = orders.loc[(orders.price_thb - orders.expected_price).abs() > .011].copy()
    orders['revenue'] = orders.gross_revenue_thb
    for name, col in [('fruit_cost', 'fruit_cost_per_cup_thb'), ('packaging_cost', 'packaging_cost_per_cup_thb'), ('labor_cost', 'labor_cost_per_cup_thb')]:
        orders[name] = orders.units_sold * orders[col]
    orders['commission'] = orders.revenue * orders.commission_rate
    orders['contribution'] = orders.revenue - orders[['fruit_cost', 'packaging_cost', 'labor_cost', 'commission']].sum(axis=1)
    orders['month'] = orders.date.dt.strftime('%Y-%m')
    waste = sheets['waste_daily'].rename(columns={'est_waste_cost_thb': 'waste_cost'}).copy()
    waste['date'] = pd.to_datetime(waste.date)
    waste['waste_cost_imputed'] = waste.waste_cost.isna()
    missing_waste = waste.waste_cost_imputed
    if missing_waste.any():
        require((waste.loc[missing_waste, 'sku'].eq('MixedBerryPremium') & waste.loc[missing_waste, 'date'].eq(pd.Timestamp('2026-03-01'))).all(), 'Unexpected missing waste cost outside launch day')
        launch_fruit = float(costs.loc[(costs.sku == 'MixedBerryPremium') & (costs.week_start == pd.Timestamp('2026-03-02')), 'fruit_cost_per_cup_thb'].iloc[0])
        berry_pack = float(assumptions.loc[assumptions.sku == 'MixedBerryPremium', 'packaging_cost_per_cup_thb'].iloc[0])
        waste.loc[missing_waste, 'waste_cost'] = waste.loc[missing_waste, 'units_wasted'] * (launch_fruit + berry_pack)
    require(not waste.duplicated(['date', 'kitchen', 'sku']).any(), 'Duplicate waste keys')
    require(waste[['units_wasted', 'waste_cost']].ge(0).all().all(), 'Negative waste')
    require(waste.date.between(orders.date.min(), orders.date.max()).all(), 'Waste period outside orders')
    require(set(waste.sku).issubset(set(orders.sku)) and set(waste.kitchen).issubset(set(orders.kitchen)), 'Unknown waste kitchen/SKU')
    overhead_rows = sheets['cost_assumptions'].iloc[8:12, :2].copy()
    overhead_rows.columns = ['kitchen', 'overhead']
    overhead_rows['overhead'] = pd.to_numeric(overhead_rows.overhead)
    require(set(overhead_rows.kitchen) == set(orders.kitchen), 'Overhead coverage mismatch')
    require(not overhead_rows.kitchen.duplicated().any(), 'Duplicate overhead keys')
    audit = {
        'raw_rows': len(raw), 'duplicate_rows_removed': int(duplicate.sum()),
        'out_of_scope_rows_removed': int(unknown.sum()), 'clean_rows': len(orders),
        'raw_revenue': float(raw.gross_revenue_thb.sum()),
        'duplicate_revenue_removed': float(excluded.loc[excluded.exclusion_reason == 'exact_duplicate', 'gross_revenue_thb'].sum()),
        'out_of_scope_revenue_removed': float(excluded.loc[excluded.exclusion_reason == 'outside_five_menu_scope', 'gross_revenue_thb'].sum()),
        'clean_revenue': float(orders.revenue.sum()), 'price_exceptions': len(price_exceptions),
        'raw_product_labels': int(raw.item_name_raw.nunique()), 'canonical_skus': int(orders.sku.nunique()),
        'retained_zero_prices': int(orders.price_thb.eq(0).sum()),
        'imputed_launch_cost_rows': int(orders.fruit_cost_imputed.sum()),
        'imputed_launch_cost_units': int(orders.loc[orders.fruit_cost_imputed, 'units_sold'].sum()),
        'imputed_launch_cost_total_thb': float(orders.loc[orders.fruit_cost_imputed, 'fruit_cost'].sum()),
        'imputed_waste_cost_rows': int(waste.waste_cost_imputed.sum()),
        'imputed_waste_cost_total_thb': float(waste.loc[waste.waste_cost_imputed, 'waste_cost'].sum()),
        'source_sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
    }
    require(abs(audit['raw_revenue'] - audit['duplicate_revenue_removed'] - audit['out_of_scope_revenue_removed'] - audit['clean_revenue']) < .01, 'Revenue cleaning bridge fails')
    # Adding columns must never silently merge independent platform observations.
    key = ['date', 'hour', 'kitchen', 'sku', 'platform_code', 'base_code']
    audit['remaining_business_key_duplicates'] = int(orders.duplicated(key).sum())
    require(audit['remaining_business_key_duplicates'] == 0, 'Multiple rows share a business key after mapping; review rather than double-count')
    audit['mixed_promo_day_groups'] = int(orders.groupby(['date', 'kitchen', 'sku', 'platform_code']).base_code.nunique().gt(1).sum())
    require(audit['mixed_promo_day_groups'] == 0, 'Partial-day promotions need hour-matched comparisons')
    return sheets, orders, waste, overhead_rows, costs, assumptions, excluded, price_exceptions, audit


def make_daily(orders, waste):
    keys = ['date', 'kitchen', 'sku']
    daily = orders.groupby(keys, as_index=False)[SUM_COLS[:7]].sum()
    daily = daily.merge(waste, on=keys, how='outer', validate='one_to_one')
    daily[SUM_COLS[:9]] = daily[SUM_COLS[:9]].fillna(0)
    daily['gp'] = daily.contribution - daily.waste_cost
    daily['month'] = daily.date.dt.strftime('%Y-%m')
    daily['dow'] = daily.date.dt.dayofweek
    return daily


def daily_grid(daily):
    """Complete active dates only. Missing exports assumed zero sales, explicitly disclosed."""
    pieces = []
    for (kitchen, sku), group in daily.groupby(['kitchen', 'sku']):
        idx = pd.date_range(group.date.min(), daily.date.max(), freq='D')
        g = group.set_index('date').reindex(idx)
        g['date'] = idx
        g['kitchen'], g['sku'] = kitchen, sku
        g['units_sold'] = g.units_sold.fillna(0)
        g['dow'] = idx.dayofweek
        pieces.append(g[['date', 'kitchen', 'sku', 'units_sold', 'dow']])
    return pd.concat(pieces, ignore_index=True)


def predict(grid, cutoff, dates, method, window):
    train = grid[(grid.date < cutoff) & (grid.date >= cutoff - pd.Timedelta(days=window))]
    keys = ['kitchen', 'sku']
    idx = pd.MultiIndex.from_product([dates, sorted(grid.kitchen.unique()), sorted(grid.sku.unique())], names=['date', *keys])
    pred = idx.to_frame(index=False)
    pred['dow'] = pred.date.dt.dayofweek
    group_keys = keys + (['dow'] if method == 'weekday' else [])
    averages = train.groupby(group_keys, as_index=False).units_sold.mean().rename(columns={'units_sold': 'predicted_units'})
    pred = pred.merge(averages, on=group_keys, how='left', validate='many_to_one')
    require(pred.predicted_units.notna().all(), 'Insufficient history for forecast groups')
    return pred


def forecast(grid, daily, orders, costs, assumptions, overhead):
    end = daily.date.max()
    candidates = [('mean', 28), ('weekday', 28), ('weekday', 56), ('weekday', 84)]
    first_holdout = end.to_period('M').start_time
    folds = [first_holdout - pd.DateOffset(months=2), first_holdout - pd.DateOffset(months=1), first_holdout]
    scores = []
    for method, window in candidates:
        for cut in folds:
            dates = pd.date_range(cut, min(cut + pd.offsets.MonthEnd(0), end))
            pred = predict(grid, cut, dates, method, window).merge(grid[['date', 'kitchen', 'sku', 'units_sold']], on=['date', 'kitchen', 'sku'], validate='one_to_one')
            error = pred.predicted_units - pred.units_sold
            scores.append({'model': f'{method}_{window}', 'method': method, 'window': window, 'month': cut.strftime('%Y-%m'), 'role': 'holdout' if cut == first_holdout else 'validation', 'absolute_error': float(error.abs().sum()), 'actual_units': float(pred.units_sold.sum()), 'predicted_units': float(pred.predicted_units.sum()), 'wape': float(error.abs().sum() / pred.units_sold.sum()), 'bias': float(error.sum() / pred.units_sold.sum()), 'mae_daily_group': float(error.abs().mean())})
    score = pd.DataFrame(scores)
    selection = score[score.role == 'validation'].groupby('model')[['absolute_error', 'actual_units']].sum()
    selected = (selection.absolute_error / selection.actual_units).idxmin()
    row = score[score.model == selected].iloc[0]
    dates = pd.date_range(end + pd.Timedelta(days=1), end + pd.offsets.MonthEnd(3))
    future = predict(grid, end + pd.Timedelta(days=1), dates, row.method, int(row.window))
    # Unit economics use recent 56 days; fruit forecast uses last 4 observed weeks.
    recent = orders[orders.date > end - pd.Timedelta(days=56)]
    econ = recent.groupby(['kitchen', 'sku'], as_index=False)[['units_sold', 'revenue', 'commission']].sum()
    econ['price_per_cup'] = econ.revenue / econ.units_sold
    econ['commission_per_cup'] = econ.commission / econ.units_sold
    econ['effective_commission_rate'] = econ.commission / econ.revenue
    econ = econ.drop(columns=['units_sold', 'revenue', 'commission'])
    last_costs = costs[costs.week_start > costs.week_start.max() - pd.Timedelta(weeks=4)].groupby('sku', as_index=False).fruit_cost_per_cup_thb.mean()
    eco = econ.merge(last_costs, on='sku', validate='many_to_one').merge(assumptions, on='sku', validate='many_to_one')
    for c in ['packaging_cost_per_cup_thb', 'labor_cost_per_cup_thb', 'base_price_thb']:
        eco[c] = pd.to_numeric(eco[c])
    waste_recent = daily[daily.date > end - pd.Timedelta(days=56)].groupby(['kitchen', 'sku'], as_index=False)[['units_sold', 'units_wasted']].sum()
    waste_recent['waste_per_sold'] = waste_recent.units_wasted / waste_recent.units_sold
    eco = eco.merge(waste_recent[['kitchen', 'sku', 'waste_per_sold']], on=['kitchen', 'sku'], validate='one_to_one')
    future = future.merge(eco, on=['kitchen', 'sku'], validate='many_to_one')
    future['month'] = future.date.dt.strftime('%Y-%m')
    future['units_sold'] = future.predicted_units
    future['revenue'] = future.units_sold * future.price_per_cup
    future['commission'] = future.units_sold * future.commission_per_cup
    for name, col in [('fruit_cost', 'fruit_cost_per_cup_thb'), ('packaging_cost', 'packaging_cost_per_cup_thb'), ('labor_cost', 'labor_cost_per_cup_thb')]:
        future[name] = future.units_sold * future[col]
    future['units_wasted'] = future.units_sold * future.waste_per_sold
    future['waste_cost'] = future.units_wasted * (future.fruit_cost_per_cup_thb + future.packaging_cost_per_cup_thb)
    future['contribution'] = future.revenue - future[['commission', 'fruit_cost', 'packaging_cost', 'labor_cost']].sum(axis=1)
    future['gp'] = future.contribution - future.waste_cost
    monthly = future.groupby(['month', 'kitchen', 'sku'], as_index=False)[SUM_COLS].sum()
    total = monthly.groupby('month', as_index=False)[SUM_COLS].sum()
    total['overhead'] = overhead.overhead.sum()
    total['operating_profit'] = total.gp - total.overhead
    # Residual variability: within-weekday noise, rather than raw weekly seasonality.
    train = grid[grid.date > end - pd.Timedelta(days=int(row.window))].copy()
    train['residual'] = train.units_sold - train.groupby(['kitchen', 'sku', 'dow']).units_sold.transform('mean')
    stats = train.groupby(['kitchen', 'sku'], as_index=False).agg(mean_daily=('units_sold', 'mean'), std_daily=('residual', 'std'), history_days=('date', 'size'))
    return future, monthly, total, score, selected, eco, stats


def promo_comparison(orders):
    keys = ['date', 'kitchen', 'sku', 'platform_code', 'base_code']
    days = orders.groupby(keys, as_index=False)[['units_sold', 'revenue', 'contribution']].sum()
    days['month'] = days.date.dt.strftime('%Y-%m')
    days['dow'] = days.date.dt.dayofweek
    strata = ['month', 'dow', 'kitchen', 'sku', 'platform_code']
    base = days[days.base_code == 'RC000'].groupby(strata, as_index=False).agg(control_days=('date', 'nunique'), baseline_units=('units_sold', 'mean'), baseline_contribution=('contribution', 'mean'))
    promos = days[days.base_code != 'RC000'].merge(base, on=strata, how='left', validate='many_to_one')
    promos['matched'] = promos.control_days.ge(2)
    rows = []
    for (code, sku), group in promos.groupby(['base_code', 'sku']):
        matched = group[group.matched]
        n = len(matched)
        units_base = matched.baseline_units.sum()
        cp_base = matched.baseline_contribution.sum()
        rows.append({'base_code': code, 'sku': sku, 'promo_days_groups': len(group), 'matched_groups': n, 'match_coverage': n / len(group), 'units_lift': float(matched.units_sold.sum() / units_base - 1) if units_base else None, 'contribution_lift': float(matched.contribution.sum() / cp_base - 1) if cp_base > 0 else None, 'contribution_difference_thb': float((matched.contribution - matched.baseline_contribution).sum()), 'mean_contribution_difference_thb': float((matched.contribution - matched.baseline_contribution).mean()) if n else None})
    return pd.DataFrame(rows), promos


def pricing_table(orders, daily, costs, assumptions):
    end = orders.date.max()
    recent = orders[orders.date > end - pd.Timedelta(days=56)]
    g = recent.groupby(['sku', 'platform_code'], as_index=False).agg(units=('units_sold', 'sum'), revenue=('revenue', 'sum'), contribution=('contribution', 'sum'), commission_rate=('commission_rate', 'first'), base_price=('base_price_thb', 'first'))
    g['realized_price'] = g.revenue / g.units
    recent_cost = costs[costs.week_start > costs.week_start.max() - pd.Timedelta(weeks=4)].groupby('sku', as_index=False).fruit_cost_per_cup_thb.mean()
    g = g.merge(recent_cost, on='sku', validate='many_to_one').merge(assumptions[['sku', 'packaging_cost_per_cup_thb', 'labor_cost_per_cup_thb']], on='sku', validate='many_to_one')
    wg = daily[daily.date > end - pd.Timedelta(days=56)].groupby('sku', as_index=False)[['units_sold', 'units_wasted']].sum()
    wg['waste_per_sold'] = wg.units_wasted / wg.units_sold
    g = g.merge(wg[['sku', 'waste_per_sold']], on='sku', validate='many_to_one')
    g['variable_cost_including_waste'] = g.fruit_cost_per_cup_thb + g.packaging_cost_per_cup_thb + g.labor_cost_per_cup_thb + g.waste_per_sold * (g.fruit_cost_per_cup_thb + g.packaging_cost_per_cup_thb)
    g['break_even_price'] = g.variable_cost_including_waste / (1 - g.commission_rate)
    g['price_for_10pct_margin'] = g.variable_cost_including_waste / (1 - g.commission_rate - .1)
    g['recent_contribution_per_cup'] = g.contribution / g.units
    g['base_price_gp_per_cup'] = g.base_price * (1 - g.commission_rate) - g.variable_cost_including_waste
    return g


def build(source=SOURCE, output=RESULTS):
    start = time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    sheets, orders, waste, overhead, costs, assumptions, excluded, price_exceptions, audit = load_and_clean(source)
    daily = make_daily(orders, waste)
    waste_coverage = orders[['date', 'kitchen', 'sku']].drop_duplicates().merge(waste[['date', 'kitchen', 'sku']], on=['date', 'kitchen', 'sku'], how='left', indicator=True)
    audit['sales_day_groups_without_waste_record'] = int(waste_coverage['_merge'].eq('left_only').sum())
    monthly_detail = daily.groupby(['month', 'kitchen', 'sku'], as_index=False)[SUM_COLS].sum()
    kitchen_monthly = monthly_detail.groupby(['month', 'kitchen'], as_index=False)[SUM_COLS].sum().merge(overhead, on='kitchen', validate='many_to_one')
    kitchen_monthly['operating_profit'] = kitchen_monthly.gp - kitchen_monthly.overhead
    monthly = kitchen_monthly.groupby('month', as_index=False)[SUM_COLS + ['overhead', 'operating_profit']].sum()
    budget = sheets['monthly_budget'].copy()
    budget['month'] = pd.to_datetime(budget.month).dt.strftime('%Y-%m')
    monthly = monthly.merge(budget[['month', 'budget_revenue_thb', 'budget_gross_profit_thb']], on='month', how='left', validate='one_to_one')
    require(monthly.budget_revenue_thb.notna().all(), 'Missing budget')
    monthly['revenue_variance'] = monthly.revenue - monthly.budget_revenue_thb
    monthly['gp_variance'] = monthly.gp - monthly.budget_gross_profit_thb
    monthly['gross_profit_before_commission'] = monthly.gp + monthly.commission
    products = daily.groupby('sku', as_index=False)[SUM_COLS].sum()
    products['margin'] = products.gp / products.revenue
    products['waste_rate_prepared'] = products.units_wasted / (products.units_sold + products.units_wasted)
    kitchens = kitchen_monthly.groupby('kitchen', as_index=False)[SUM_COLS + ['overhead', 'operating_profit']].sum()
    grid = daily_grid(daily)
    audit['zero_sales_active_day_groups'] = int(grid.units_sold.eq(0).sum())
    promo, matched_days = promo_comparison(orders)
    future, forecast_detail, forecast_total, scores, selected, econ, inventory = forecast(grid, daily, orders, costs, assumptions, overhead)
    pricing = pricing_table(orders, daily, costs, assumptions)
    hours = orders.groupby(['month', 'kitchen', 'sku', 'hour'], as_index=False)[['units_sold', 'revenue', 'contribution']].sum()
    channels = orders.groupby(['month', 'kitchen', 'sku', 'platform_code'], as_index=False)[['units_sold', 'revenue', 'commission', 'contribution']].sum()
    totals = {c: float(monthly[c].sum()) for c in SUM_COLS + ['overhead', 'operating_profit', 'budget_revenue_thb', 'budget_gross_profit_thb']}
    checks = {
        'cleaning_row_bridge': audit['raw_rows'] == audit['clean_rows'] + audit['duplicate_rows_removed'] + audit['out_of_scope_rows_removed'],
        'revenue_reconciles_to_orders': abs(monthly.revenue.sum() - orders.revenue.sum()) < .01,
        'waste_reconciles_once': abs(monthly.waste_cost.sum() - waste.waste_cost.sum()) < .01,
        'gp_identity': bool(np.allclose(monthly.gp, monthly.revenue - monthly[['fruit_cost', 'packaging_cost', 'labor_cost', 'commission', 'waste_cost']].sum(axis=1), atol=.01)),
        'overhead_once_per_month_kitchen': abs(monthly.overhead.sum() - overhead.overhead.sum() * monthly.month.nunique()) < .01,
        'forecast_has_three_months': forecast_total.month.nunique() == 3,
        'forecast_nonnegative_units': bool(future.units_sold.ge(0).all()),
        'forecast_gp_identity': bool(np.allclose(future.gp, future.revenue - future[['fruit_cost', 'packaging_cost', 'labor_cost', 'commission', 'waste_cost']].sum(axis=1), atol=.01)),
    }
    checks = {key: bool(value) for key, value in checks.items()}
    require(all(checks.values()), f'Reconciliation failed: {checks}')
    exported = {
        'monthly_pnl': monthly, 'monthly_sku_kitchen': monthly_detail, 'kitchen_monthly_pnl': kitchen_monthly,
        'product_performance': products, 'kitchen_performance': kitchens, 'promo_matched_comparison': promo,
        'promo_matched_days': matched_days, 'pricing_thresholds': pricing, 'forecast_monthly': forecast_total,
        'forecast_sku_kitchen': forecast_detail, 'forecast_daily': future, 'forecast_backtest': scores,
        'inventory_inputs': inventory, 'excluded_rows': excluded, 'price_exceptions': price_exceptions,
        'clean_orders': orders, 'daily_pnl': daily,
        'sku_mapping': pd.DataFrame([{'item_name_raw': a, 'sku': s} for s, aa in ALIASES.items() for a in aa]),
    }
    for name, frame in exported.items():
        frame.to_csv(output / f'{name}.csv', index=False, encoding='utf-8-sig')
    data = {
        'meta': {'start': str(orders.date.min().date()), 'end': str(orders.date.max().date()), 'forecast_start': str(future.date.min().date()), 'forecast_end': str(future.date.max().date()), 'selected_model': selected, 'python': platform.python_version(), 'pandas': pd.__version__, 'numpy': np.__version__, 'source': Path(source).name, 'synthetic': True, 'build_seconds': round(time.perf_counter()-start, 2)},
        'audit': audit, 'checks': checks, 'totals': totals,
        'monthly': records(monthly), 'detail': records(monthly_detail), 'kitchen_monthly': records(kitchen_monthly),
        'products': records(products), 'kitchens': records(kitchens), 'promo': records(promo),
        'pricing': records(pricing), 'forecast': records(forecast_total), 'forecast_detail': records(forecast_detail),
        'backtest': records(scores), 'inventory': records(inventory), 'economics': records(econ),
        'hours': records(hours), 'channels': records(channels), 'costs': records(costs), 'overhead': records(overhead),
        'downloads': [f'{name}.csv' for name in exported],
    }
    from app import scenario
    case_rows = []
    for name, params in [('Base', {}), ('Downside', {'volume': ['-15'], 'fruit': ['10']}), ('Waste reduction only', {'waste': ['25']}), ('Targeted experimental plan', {'plan': ['targeted']})]:
        result = scenario(data, params)
        for row in result['monthly']:
            case_rows.append(dict(scenario=name, **row, assumptions_json=json.dumps(result['assumptions'], ensure_ascii=False)))
    pd.DataFrame(case_rows).to_csv(output / 'scenario_comparison.csv', index=False, encoding='utf-8-sig')
    data['downloads'].append('scenario_comparison.csv')
    data['scenarios'] = case_rows
    (output / 'dashboard.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'validation.json').write_text(json.dumps({'checks': checks, 'audit': audit}, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'meta': data['meta'], 'audit': audit, 'totals': totals, 'selected_model': selected, 'checks': checks}, ensure_ascii=False, indent=2))
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=RESULTS)
    args = parser.parse_args()
    build(args.source, args.output)
