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

An initial ten-trip timeline sample was inspected during the first collection hour. All ten had
target-stop updates and vehicle-position records; none yet had a retained post-passage target
update in the available snapshots. These trips are too recent for the candidate-label gate: the
corrected audit marks all 47 feature examples pending until each full 30-minute window closes.
This is an early diagnostic, not the required two-day review or a coverage result. The detailed
sample is retained in the ignored `trip-timelines.json` report.

At the 2026-10-23 22:18 Vancouver check, the retained reports showed 310 successful polls out of
310 attempts, with a largest same-feed gap of about 83 minutes. The offline rebuild had 2,336
feature rows, 2,299 matured examples, and a 98.4% strict Static join rate. Candidate coverage was
22.7% overall; the highest route, R5, was 31.4%. The date was still in progress and the brief
October 22 start did not qualify as a usable day. These measurements fail the 70% label gate so
far. A second complete usable day and the final ten-trip review are still required before any
target decision. No model MAE can be reported from this window yet.

A refreshed ten-trip diagnostic at 22:22 sampled ten distinct trips across routes 049, 099, R4,
and R5 and both observed local dates. Six had a target update in the candidate window; three had
an update after the reported passage time; six had a position that passed the target. All ten had
changing reported delays in their captured histories, and none of these sampled trip histories
contained a cancellation. These are observations from the retained timeline sample, not the
required review of two complete usable days. Its review statuses remain pending.

The October 23 serving probe recorded 71 live requests with no request errors. Latency was
1.154 ms at p50 and 3.75 ms at p95; input freshness was 169 seconds at p50 and 287 seconds at
p95. Every response used the persistence fallback because no model has been promoted. None has
an approved delayed label, so the probe cannot report prediction MAE. This is baseline serving
evidence and does not count toward the seven subsequent monitoring days.

## Label coverage diagnosis

At the 2026-10-23 22:33 Vancouver audit, 521 of 2,321 mature examples had a target-stop value in
the 30-minute candidate window: 22.4% coverage. Of the 1,800 misses, 355 had no Trip Updates
poll in that window, 344 had polls but no update for the trip, 1,099 had a trip update without the
target stop, and two had the stop without an arrival value. A target value had been present before
the window in 1,727 misses. Excluding only windows with no feed poll raises coverage to 26.5%,
still far below the 70% gate. This points to short target-stop retention and trip disappearance as
well as collection gaps; it does not establish why the producer drops each update.

The isolated R5 replay had 118 candidates among 380 mature examples (31.1%), or 35.6% after
excluding its 49 windows without a feed poll. It also fails the gate. By *feature service date*,
the brief October 22 slice reached 58.7% across 184 examples and the ongoing October 23 date
reached 19.3% across 2,137. Neither is a two-complete-day result. The retained
`feasibility.json` and `route-scopes/R5.json` reports hold these counts.

An isolated R5 replay at a shorter 5–10-minute horizon produced 101 candidates among 394 mature
examples (25.6%), below the 31.1% observed at the planned 10–15-minute horizon. This is an
exploratory target change, not an approved label or a live configuration change. The retained
`route-scopes/R5-h300-600.json` report records its joins and missingness.

## Reproduce and inspect

```bash
launchctl list | grep com.cna52.transit-delay
docker compose -f compose.evidence.yaml ps
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
.venv311/bin/transit-delay collection-report --config configs/evidence.yaml
.venv311/bin/transit-delay feed-audit --config configs/evidence.yaml
.venv311/bin/transit-delay trip-timelines --config configs/evidence.yaml
.venv311/bin/transit-delay feasibility-report --config configs/evidence.yaml
.venv311/bin/transit-delay evidence-report --config configs/evidence.yaml
```

When a checksummed policy and a versioned dataset exist, the DuckDB catalog contains
`dataset_coverage` and `dataset_label_quality` views over the latest immutable Parquet version.
The catalog's `dataset_versions` table retains every version and its exact Parquet path.

## Pending evidence

The two-day trip timeline review, 28-day collection, locked split dates and MAE comparison,
seven subsequent days of delayed prediction evaluation, and final report screenshots are pending.
An unavailable computer or feed extends the collection window; gaps are recorded rather than
filled. Replay and synthetic material are demo content and never included in live metrics.
The serving probe records baseline behavior now; only predictions in the seven-day window after
the locked evaluation will enter the final online result.
