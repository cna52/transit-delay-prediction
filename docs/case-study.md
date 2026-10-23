# Transit delay evidence trail (collection in progress)

This is a live evidence log, not a completed model result. The baseline repository commit is
`d15cd2f89963689354d1427f54497c1fb8aeb49a`. The new collection window began on
2026-10-22 in Vancouver and is isolated under `data/evidence-2026-10-22/`; the August sample is
excluded. Raw feed bytes, the API key, generated reports, and model artifacts are kept out of Git.
The evaluation gates and four-minute collection configuration are committed at `effbb44`.

## Current result

The first successful Trip Update and Vehicle Position polls were received at 2026-10-22 23:21
Vancouver time. The first worker pass joined 19 selected route updates without a join failure and
produced 14 feature rows. These are startup observations from one snapshot, not a feasibility
rate or model evaluation. The Docker API answered `/healthz`, `/readyz`, and one live
`POST /v1/predictions`; that request served `persistence-v1` as a fallback because no model is
promoted. Its recorded latency was 4.34 ms and source freshness was 79 seconds. The retained
`collection.json`, `dataset-quality.json`, and `predictions.json` reports under the isolated data
directory are the source of these provisional observations.

## Target and locked protocol

The intended label is **reported target-stop delay state approximately 10–15 minutes later**.
It is a producer-reported proxy; measured arrival requires separate retained post-passage and
vehicle-position evidence. A policy can only be locked after two complete usable service days,
100 eligible examples, 90% strict unique Static joins, 70% candidate coverage within 30 minutes,
and review of ten trip timelines. If coverage fails, route scope is narrowed in the evidence
configuration and the audit is rerun. If no route passes, no model claim will be made.

The locked test requires 28 complete usable service days with labels. The last seven service
days are test, the preceding seven validation, and earlier days training. The committed evaluation
code selects Ridge or LightGBM on validation, compares it with persistence and historical median,
reports slices, rolling folds, a 90% interval, missing labels, and trip-clustered uncertainty.
Promotion is conditional on all gates in [the evaluation protocol](evaluation.md).

## Reproduce and inspect

```bash
launchctl list | grep com.cna52.transit-delay
docker compose -f compose.evidence.yaml ps
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
.venv311/bin/transit-delay collection-report --config configs/evidence.yaml
.venv311/bin/transit-delay feed-audit --config configs/evidence.yaml
.venv311/bin/transit-delay evidence-report --config configs/evidence.yaml
```

When a checksummed policy and a versioned dataset exist, the DuckDB catalog contains
`dataset_coverage` and `dataset_label_quality` views over the latest immutable Parquet version.
The catalog's `dataset_versions` table retains every version and its exact Parquet path.

## Pending evidence

The two-day trip timeline review, 28-day collection, locked split dates and MAE comparison,
seven subsequent days of delayed prediction evaluation, and final UI screenshots are pending.
An unavailable computer or feed extends the collection window; gaps are recorded rather than
filled. Replay and synthetic material are demo content and never included in live metrics.
