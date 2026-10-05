# Validation record

Validated on 6 October 2026 against the bundled source files. This is a snapshot of checks performed, not a claim of production certification.

## Source preservation

The copied XLSX and DOCX match their original files byte-for-byte by SHA-256. Source workbook hash:

`c2869ce419bf796bf1351c46b6bdd813a4c35add7031c4e143630858a0a6c6f8`

## Analysis reconciliation: 8 checks passed

- Raw rows = retained rows + exact duplicates + out-of-scope rows.
- P&L revenue reconciles to cleaned orders.
- Waste cost is counted exactly once, including the documented launch-day estimate.
- Management GP reconciles to revenue less its component costs.
- Fixed overhead is charged once per kitchen per month.
- Forecast includes three months.
- Forecast volumes are nonnegative.
- Forecast GP reconciles to its component costs.

Additional ingestion guards check required fields, positive prices and integer cup counts, weekday alignment, hour range, price × quantity, valid promotion/SKU/platform codes, unique dimension joins, cost coverage, nonnegative waste, business-key duplicates, and absence of mixed promotion codes within a day/platform/SKU/kitchen. Unexpected missing costs stop the pipeline.

## Automated tests: 16 passed

Command:

```powershell
python -m unittest discover -s tests -v
```

Coverage: base-scenario reconciliation; correct net revenue effect of a price change; SKU-specific volume changes; waste savings counted once; fruit inflation applied to sold and wasted units; invalid and non-finite inputs; unknown SKU; no negative inventory order; on-hand and in-transit deduction; shelf-life/service conflict; invalid inventory inputs; historical cleaning bridge; forecast dates relative to source cutoff; targeted plan reconciles to independently composed menu scenarios; future targets cannot affect an earlier forecast; insufficient history fails explicitly.

App-only tests (14 cases) also passed under the system Python 3.14, confirming the standard-library app functions work with the user's default interpreter. The two pandas-dependent forecast tests were run under the bundled Python 3.12.14.

## HTTP checks

Successful responses: homepage, health, dashboard data, targeted scenario, inventory, monthly P&L download, and scenario download with embedded assumptions.

Rejected as expected: non-finite scenario input (400), invalid service target (400), attempted traversal outside the download allowlist (404), and direct access to bundled source data over HTTP (404).

## Browser checks

Verified the Thai dashboard in the in-app browser, including:

- Historical month filter: August P&L shows revenue THB 2,211,914.80 and operating loss THB 246,489.95.
- Targeted experimental plan displays approximately THB 99,270 three-month operating profit and THB 895,912 improvement from baseline, with its assumptions visible.
- Increasing usable on-hand stock to 100 cup equivalents in the default inventory example changes the proposed order from 67 to 0.
- Visual inspection of dashboard and inventory layouts.
- JavaScript syntax validation.

## Performance observed on this machine

Final analysis build took approximately 12 seconds. The precomputed dashboard JSON is approximately 1 MB; the app does not reread Excel when filters change. In one local smoke check the targeted scenario endpoint returned in approximately 1.5 ms and inventory in approximately 0.9 ms. These are observations from this machine, not statistically sampled performance guarantees.

## Remaining limits

No public hosting, multi-user authentication or load test was performed. No actual purchase orders or business changes were made. Forecast validation is at a one-month horizon, with a separate August holdout, not a proven three-month confidence interval. The inventory heuristic is not a full perishables optimization model. The projected turnaround depends on unverified demand responses and feasible overhead savings, excludes implementation costs, and assumes changes take effect immediately.
