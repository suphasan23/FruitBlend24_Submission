# FruitBlend24 — Submission note

This submission is a working local Python application with a reproducible analysis pipeline, source workbook, CSV outputs, Thai executive summary, and presentation guide.

Run `python app.py` inside the extracted folder and open `http://127.0.0.1:8765`. Viewing bundled results requires Python only. Rebuilding requires the pinned packages in `requirements.txt`.

## Tools and approach

Python 3.12, pandas 3.0.1, NumPy 2.3.5 and openpyxl 3.1.5 are used for source ingestion and analysis. Python's standard-library HTTP server provides a localhost dashboard and scenario/inventory APIs. The browser interface uses self-contained HTML/CSS/JavaScript and SVG charts, without external services.

The analysis covers explicit data cleaning and reconciliation, a reconstructed management P&L, SKU/kitchen/channel economics, descriptive matched promotion comparisons, and a three-month planning forecast selected through chronological validation with a separate holdout. Unit tests cover financial identities, scenario changes, inventory boundaries, and forecast leakage.

## Main findings

- Annual core-menu revenue is THB 31.15m, but operating profit after fixed overhead is negative THB 0.403m.
- Watermelon and Pineapple generate about 71% of management GP. Mixed Berry has a 20.54% waste rate on prepared cups and negative GP after waste.
- Matched promotion observations increase units but have lower contribution than comparable standard-price days. These are descriptive associations, not causal estimates.
- Both Bangkok kitchens show annual operating losses, requiring an avoidable-cost and capacity review.
- The three-month baseline remains loss-making. A conditional, explicitly stated pricing/volume/waste/overhead scenario demonstrates a possible route to profitability, subject to validation through experiments and cost feasibility checks.

## Important assumptions

Gross-profit budget definition is not fully specified, so management GP includes commission and waste before overhead; the pre-commission alternative is also exported. Missing launch-day berry costs are explicitly estimated from the first supplied week. Six missing waste records are assumed zero and disclosed. Forecast dates are September–November 2026, relative to the source cutoff, not the date the app is opened.

## With more time

Collect stockout and inventory-age data, recipes/yields, real supplier lead times, customer repeat-purchase data, platform-funded promotion details and avoidable overhead. Run controlled pricing/promotion experiments, evaluate additional seasonal forecasting models against a new holdout, and validate inventory service levels under realistic perishability and supplier constraints.

AI assisted with code and explanation drafting. The submission includes source-to-result audit trails and tests so the methodology and assumptions can be independently reviewed. The presenter should verify the findings and be prepared to explain them.
