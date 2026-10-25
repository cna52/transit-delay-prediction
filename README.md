# TransLink delay prediction

An end-to-end, local-first machine-learning system for predicting a selected bus trip's reported
delay state at a downstream stop approximately 10–15 minutes ahead, with a stricter measured-
arrival target available only if feed audits support it. The repository is
designed to demonstrate collection, immutable data lineage, point-in-time feature construction,
chronological evaluation, model serving, and delayed-label monitoring—not merely a notebook.

## Current status

The engineering system is implemented, but the evidence collection is still in progress. The
current short live sample is deliberately prevented from training because it does not meet the
minimum label-audit gates. No model-performance or long-term reliability claim is made yet. See
[the feasibility runbook](docs/feasibility.md).

Official constraints reflected in the implementation:

- TransLink publishes separate authenticated [Trip Update and Vehicle Position endpoints](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-realtime).
- The [Open API terms](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/terms-of-use)
  cap a key at 1,000 requests/day. The configured schedule uses 864, and a durable counter caps
  all attempts at 900.
- Static GTFS is [published weekly](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data).
- GTFS-Realtime fields are optional in many cases; the project follows the
  [official reference](https://gtfs.org/documentation/realtime/reference/) and does not assume
  that TransLink populates them.

## Quick start

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
# Add your TransLink key to .env or export it in the shell.
.venv/bin/transit-delay download-static
.venv/bin/transit-delay collect --once
.venv/bin/pytest
```

The API can be run locally with `.venv/bin/transit-delay serve`; its interactive documentation is
at `http://localhost:8000/docs`. `docker compose up --build` runs the API, collector, and worker.

Long-running local operation (collector plus the worker that refreshes serving features, reports,
datasets, and delayed-label joins):

```bash
docker compose up --build
# or, in separate local terminals:
.venv/bin/transit-delay collect
.venv/bin/transit-delay worker
```

The worker uses a point-in-time Static GTFS registry, choosing the schedule version available for
each trip's service date and realtime receipt time. After at least 100 eligible examples and 70%
candidate-label coverage, inspect the audit and create an explicit, checksummed label policy:

```bash
.venv/bin/transit-delay feed-audit
.venv/bin/transit-delay trip-timelines
# Copy trip-timelines.json to trip-timelines-reviewed.json; review ten distinct
# trips from two service days, setting review_status and review_notes for each.
.venv/bin/transit-delay create-label-policy --target-type reported_delay_state
.venv/bin/transit-delay worker --once
```

`measured_arrival` is available only when the stricter audit also demonstrates retained
post-passage updates corroborated by vehicle positions. The October 23–24 live audit found only
28.1% candidate coverage for the original reported-state target, so that policy was not approved.
The active R5 evidence configuration instead uses a reviewed, checksummed
`reported_delay_state_fixed_lag` policy: a future producer-reported target-stop delay value first
available 5–13 minutes after prediction. It is a proxy, not observed arrival. Its isolated
two-day replay reached 77.6% candidate coverage; see [the case study](docs/case-study.md) for
the day-level gap and missingness limits. The audit, ten-trip review, and route-scope report are
archived by checksum outside Git. The production policy command is:

```bash
.venv311/bin/transit-delay create-label-policy --config configs/evidence.yaml \
  --target-type reported_delay_state_fixed_lag \
  --review data/evidence-2026-10-22/reports/route-scopes/R5-lag300-w480-timelines-reviewed.json \
  --scope-report data/evidence-2026-10-22/reports/route-scopes/R5-lag300-w480.json
```

For an offline portfolio demo that never masquerades as live evidence:

```bash
.venv/bin/transit-delay seed-demo
.venv/bin/transit-delay serve --config configs/replay.yaml
```

The API includes
`/healthz`, `/readyz`, `/v1/model`, `/v1/observations`,
`/v1/metrics/*`, `/v1/system`, and `POST /v1/predictions`. Interactive API documentation remains
at `/docs`. Without a promoted model it deliberately serves the persistence baseline and
identifies it as a fallback; missing evaluation reports are shown as pending rather than replaced
with made-up metrics.

## Reproducibility and safety

- Exact protobuf and Static ZIP bytes are immutable and content-addressed.
- Every fetch attempt is preserved, including errors and duplicate snapshots.
- Every trip key includes Static feed version and service date.
- Feature builders reject source timestamps later than `as_of`.
- Labels remain blocked until a versioned, checksummed live-feed audit enables their policy.
- Training uses chronological partitions and evaluates against persistence and historical medians.
- Promotion requires a trip-clustered bootstrap improvement over persistence and route guardrails.
- Model artifacts carry dataset, environment, Git, and checksum lineage.
- The API refuses corrupt artifacts and falls back for stale features.

Generated raw data, licensed data, secrets, and model binaries are excluded from Git. Any public
display must include TransLink's required disclaimer from its API terms.

## Documentation

- [Architecture](docs/architecture.md)
- [Data contract](docs/data_contract.md)
- [Feasibility and first vertical slice](docs/feasibility.md)
- [Evaluation protocol](docs/evaluation.md)
- [Local operations runbook](docs/runbook.md)
- [Evidence and completion rubric](docs/evidence.md)
- [Live case study and pending gates](docs/case-study.md)
