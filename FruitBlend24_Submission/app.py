"""Local FruitBlend24 dashboard. Run: python app.py --port 8765.

Viewing the bundled results requires only Python's standard library.
Rebuilding uses pandas/numpy/openpyxl via analysis.py.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import NormalDist
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
TARGETED_PLAN = {
    'Watermelon': {'price_pct': 10, 'volume_pct': -5},
    'Pineapple': {'price_pct': 10, 'volume_pct': -5},
    'Guava': {'price_pct': 10, 'volume_pct': -5},
    'PassionFruit': {'price_pct': 15, 'volume_pct': -10},
    'MixedBerryPremium': {'price_pct': 40, 'volume_pct': -25},
}


def read_data():
    path = ROOT / 'results' / 'dashboard.json'
    if not path.exists():
        from analysis import build
        build()
    return json.loads(path.read_text(encoding='utf-8'))


def numeric(params, name, default, low, high):
    value = float(params.get(name, [default])[0])
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    return value


def scenario(data, params):
    plan = params.get('plan', ['custom'])[0]
    if plan not in ['custom', 'targeted']:
        raise ValueError('Unknown scenario plan')
    price = numeric(params, 'price', 0, -30, 50) / 100
    volume = numeric(params, 'volume', 0, -60, 60) / 100
    fruit = numeric(params, 'fruit', 0, -30, 50) / 100
    waste = numeric(params, 'waste', 0, 0, 80) / 100
    overhead_cut = numeric(params, 'overhead', 0, 0, 30) / 100
    sku = params.get('sku', ['All'])[0]
    if sku not in ['All'] + [r['sku'] for r in data['products']]:
        raise ValueError('Unknown SKU')
    if plan == 'targeted':
        fruit, waste, overhead_cut = 0, .25, .15
    results = {}
    for r in data['forecast_detail']:
        selected = sku == 'All' or r['sku'] == sku
        v, p = (1 + volume, 1 + price) if selected else (1, 1)
        if plan == 'targeted':
            v = 1 + TARGETED_PLAN[r['sku']]['volume_pct'] / 100
            p = 1 + TARGETED_PLAN[r['sku']]['price_pct'] / 100
        rev = r['revenue'] * v * p
        comm = r['commission'] * v * p
        fruit_cost = r['fruit_cost'] * v * (1 + fruit)
        pack, labor = r['packaging_cost'] * v, r['labor_cost'] * v
        # Recover the fruit share of forecast waste cost from unit economics.
        eco = next(e for e in data['economics'] if e['sku'] == r['sku'] and e['kitchen'] == r['kitchen'])
        wasted = r['units_wasted'] * v * (1 - waste)
        wc = wasted * (eco['fruit_cost_per_cup_thb'] * (1 + fruit) + eco['packaging_cost_per_cup_thb'])
        row = results.setdefault(r['month'], dict(month=r['month'], units_sold=0, revenue=0, gp=0, waste_cost=0, units_wasted=0))
        row['units_sold'] += r['units_sold'] * v
        row['revenue'] += rev
        row['gp'] += rev - comm - fruit_cost - pack - labor - wc
        row['waste_cost'] += wc
        row['units_wasted'] += wasted
    fixed = sum(r['overhead'] for r in data['overhead']) * (1 - overhead_cut)
    for month, r in results.items():
        r['overhead'] = fixed
        r['operating_profit'] = r['gp'] - fixed
        r['base_operating_profit'] = next(x['operating_profit'] for x in data['forecast'] if x['month'] == month)
        r['change_from_base'] = r['operating_profit'] - r['base_operating_profit']
    assumptions = {'plan': plan, 'fruit_cost_pct': fruit*100, 'waste_reduction_pct': waste*100, 'overhead_reduction_pct': overhead_cut*100}
    if plan == 'targeted':
        assumptions['menu_assumptions'] = TARGETED_PLAN
    else:
        assumptions.update({'sku': sku, 'price_pct': price*100, 'volume_pct': volume*100})
    return {'assumptions': assumptions, 'monthly': list(results.values())}


def inventory_plan(data, params):
    lead = numeric(params, 'lead', 1, 0, 7)
    review = numeric(params, 'review', 1, .25, 7)
    shelf = numeric(params, 'shelf', 2, .25, 14)
    service = numeric(params, 'service', 95, 50, 99.9) / 100
    onhand = numeric(params, 'onhand', 0, 0, 100000)
    transit = numeric(params, 'transit', 0, 0, 100000)
    kitchen = params.get('kitchen', [data['inventory'][0]['kitchen']])[0]
    sku = params.get('sku', [data['inventory'][0]['sku']])[0]
    matches = [r for r in data['inventory'] if r['kitchen'] == kitchen and r['sku'] == sku]
    if len(matches) != 1:
        raise ValueError('Unknown kitchen/SKU')
    r = matches[0]
    horizon = lead + review
    safety = NormalDist().inv_cdf(service) * r['std_daily'] * math.sqrt(horizon)
    unconstrained = r['mean_daily'] * horizon + safety
    cap = r['mean_daily'] * shelf
    target = math.ceil(min(unconstrained, cap))
    return {**r, 'lead_days': lead, 'review_days': review, 'shelf_days': shelf, 'service_pct': service*100, 'safety_stock_cups': safety, 'unconstrained_target_cups': unconstrained, 'freshness_cap_cups': cap, 'target_stock_cups': target, 'on_hand_cups': onhand, 'in_transit_cups': transit, 'order_cup_equivalents': max(0, math.ceil(target - onhand - transit)), 'freshness_cap_binding': unconstrained > cap, 'horizon_exceeds_shelf_life': horizon > shelf}


def make_handler(data):
    class Handler(BaseHTTPRequestHandler):
        def send(self, body, content_type='application/json; charset=utf-8', status=200, filename=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            elif isinstance(body, str):
                body = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            params = parse_qs(url.query)
            try:
                if url.path == '/':
                    return self.send((ROOT / 'dashboard.html').read_bytes(), 'text/html; charset=utf-8')
                if url.path == '/health':
                    return self.send({'status': 'ok', 'source_sha256': data['audit']['source_sha256']})
                if url.path == '/api/data':
                    return self.send(data)
                if url.path == '/api/scenario':
                    return self.send(scenario(data, params))
                if url.path == '/api/inventory':
                    return self.send(inventory_plan(data, params))
                if url.path == '/download/scenario.csv':
                    result = scenario(data, params)
                    rows = [dict(r, assumptions_json=json.dumps(result['assumptions'], ensure_ascii=False)) for r in result['monthly']]
                    stream = io.StringIO()
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                    return self.send('\ufeff' + stream.getvalue(), 'text/csv; charset=utf-8', filename='scenario.csv')
                if url.path.startswith('/download/'):
                    name = url.path.removeprefix('/download/')
                    if name not in data['downloads']:
                        return self.send({'error': 'Unknown download'}, status=404)
                    return self.send((ROOT / 'results' / name).read_bytes(), 'text/csv; charset=utf-8', filename=name)
                return self.send({'error': 'Not found'}, status=404)
            except (ValueError, TypeError) as exc:
                return self.send({'error': str(exc)}, status=400)

    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    if args.rebuild:
        from analysis import build
        build()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(read_data()))
    print(f'FruitBlend24: http://127.0.0.1:{args.port} | Ctrl+C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
