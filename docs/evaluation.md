# Evaluation protocol

Primary metric: MAE in minutes on valid labelled examples.

Every report includes persistence, hierarchical historical median, Ridge, and optionally LightGBM.
Secondary measures are median and p90 absolute error and signed bias. Results are sliced by route,
10–12 versus 12–15 minute horizon, time of day, and feed freshness.

With four or more usable weeks, reserve the last seven complete service days as a locked test and
the preceding seven as validation. Train on earlier data and run weekly rolling-origin backtests.
Keep trip instances intact, fit all preprocessing and historical aggregates on training data, and
do not tune after opening the final test report.

Validation residual q05/q95 values form empirical intervals. Coverage and width must be measured
on held-out data. Stale or unsupported input falls back to a baseline with a degraded flag; missing
labels and fallback coverage accompany every MAE.

Model selection is made on validation data. The selected model is refit on train plus validation,
then evaluated once on the locked test period. Promotion requires all of the following:

- lower trip-weighted test MAE than persistence;
- an upper 95% bound below zero for the paired MAE difference, using a trip-clustered bootstrap;
- no route with at least 100 test examples regressing by more than 10% against persistence.

An isolated score is never sufficient. Reports retain the baseline comparison, chronological
boundaries, rolling-origin folds, route/horizon/time/freshness slices, fallback rate, and interval
coverage. Synthetic and replay results are development checks and are excluded from résumé claims.

## Early validation preview

After at least 14 complete usable days, `preview-evaluation` compares Ridge with persistence and
historical median on past days only. It trains on earlier complete Vancouver dates and uses the
latest seven of the first 21 complete dates for exploratory validation. The split preserves trip
instances, purges 30 minutes around its boundary, verifies the dataset and label-policy checksums,
and reports missing labels and a trip-clustered paired interval. It does not create a serving
artifact or make a promotion decision. Dates 22–28 of the locked evaluation remain untouched.

```bash
.venv311/bin/transit-delay preview-evaluation \
  data/evidence-2026-10-22/processed/datasets/DATASET_VERSION/rows.jsonl \
  --config configs/evidence.yaml
```
