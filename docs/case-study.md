# Transit delay evidence trail (scoped proxy label)

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

The original intended label was **reported target-stop delay state approximately 10–15 minutes later**.
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
The final feasibility gate uses the feature's **local prediction date** and only dates whose
collection day has closed; the partial October 22 and ongoing October 23 observations above are
diagnostics, not gate inputs.

An isolated R5 replay at a shorter 5–10-minute horizon produced 101 candidates among 394 mature
examples (25.6%), below the 31.1% observed at the planned 10–15-minute horizon. This is an
exploratory target change, not an approved label or a live configuration change. The retained
`route-scopes/R5-h300-600.json` report records its joins and missingness.

Further exploratory replays kept the original 10–15-minute-ahead target stop but sampled its
*reported delay state* five minutes after prediction, accepting the first value over the next
eight minutes. Coverage was 47.7% across all four routes and 51.7% on R5 (85.5% and 85.3%,
respectively, after excluding windows with no feed snapshot); the median actual
observation lag among candidates was about eight minutes. A 10-minute lag with the same window
reached only 34.3% on R5. These variants remain below the 70% all-example gate and change the
prediction question; they are retained under `route-scopes/` as exploratory reports. The
shorter fixed lag appears promising only when the feed is actually polled during the window,
which is not a substitute for reliable collection or the two-day review.

At the 22:44 collection check, all 324 attempted fetches succeeded, but each feed had only 162
attempts across approximately 351 four-minute cadence slots between its first and latest poll:
46.2% cadence coverage. The largest same-feed gap was about 83 minutes. This explains much of
the short-window candidate loss and makes uninterrupted collection the immediate operational
priority. The cadence denominator is the observed first-to-last collection span, not a claim of
full-day uptime.

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

The 28-day labelled collection, locked split dates and MAE comparison, seven subsequent days of
delayed prediction evaluation, and final report screenshots are pending.
An unavailable computer or feed extends the collection window; gaps are recorded rather than
filled. Replay and synthetic material are demo content and never included in live metrics.
The serving probe records baseline behavior now; only predictions in the seven-day window after
the locked evaluation will enter the final online result.

## Two-day feasibility decision — October 25

The first two complete usable Vancouver collection dates are October 23 and 24. The retained
`feasibility.json` report, refreshed at 08:34 on October 25, has 5,774 mature examples from
those dates, 1,621 candidate labels within 30 minutes (28.1%), and a 99.4% strict Static join
rate. The 100-example, two-day, and join gates pass; the required 70% candidate-label gate
fails. Route coverage is 18.8% on 049, 30.3% on 099, 31.9% on R4, and 35.3% on R5. An isolated
R5 replay confirms 396 candidates among 1,123 mature examples and a 99.9% strict join rate.
The current reported target-stop delay-state label is therefore a dataset limitation, and no
label policy or model result is approved.

The October 24 collection attempted 335 of 360 four-minute slots per feed (93.1%) and succeeded
on 334 for each. Even on that better-polled date, the R5 candidate rate was only 37.7%, compared
with 31.3% on October 23. Feed gaps contribute to missingness, but target-stop removal remains a
major limit under reliable polling.

The checksum-matched ten-trip packet covers ten distinct trips from both complete local dates
and all four routes. The ignored `trip-timelines-reviewed.json` retains an observation for each.
Six trips had a target value in the candidate window; one more had the target stop but no arrival
value. Several targets disappeared after earlier estimates, while other estimates revised or
persisted after reported passage. No sampled trip was cancelled. This review supports the audit's
missingness diagnosis and does not establish measured arrivals.

At the same reporting snapshot, 1,286 of 1,288 fetch attempts succeeded, and projected compressed
raw storage for 56 days was about 1.96 GB. The two-day decision is limited to this collection
window and its selected routes. Collection continues while alternative target feasibility is
examined; the 28-day model evaluation remains gated on an approved label.

## Scoped R5 proxy decision — October 25

The isolated R5 replay selects a stop ten to fifteen minutes ahead at prediction time, then
labels its **producer-reported delay state** from the first usable update received five to
thirteen minutes later. The actual median observation lag was about eight minutes. This is a
future reported estimate, not an observed arrival or actual delay. The original target's failed
gate remains a separate result.

Across the two complete dates, the fixed-lag replay has 872 candidates among 1,123 mature R5
examples (77.6%) and 99.9% strict Static joins. Coverage was 54.8% on October 23 and 91.5% on
October 24, so date-level missingness needs explicit reporting during evaluation. The reviewed
R5 packet contains ten distinct trips, five from each date; seven have a future reported-state
value, while three are censored after earlier target estimates. Neither the packet nor the
aggregate rate establishes measured arrivals. The ignored `route-scopes/R5-lag300-w480.json`
and matching reviewed timeline packet retain the exact evidence and checksums.

The active evidence configuration now selects R5. A checksummed fixed-lag policy binds the
frozen audit, reviewed timelines, route scope, five-minute lag, and eight-minute candidate
window. This target change resets the scope of subsequent model claims to R5 alone. Model MAE,
promotion, and online accuracy remain unavailable until enough complete labelled days have
accrued and the locked chronological evaluation has run.
