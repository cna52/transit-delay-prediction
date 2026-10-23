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

For the React development UI (Node 20+):

```bash
# Terminal 1
.venv/bin/transit-delay serve
# Terminal 2
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies API calls to FastAPI on port 8000. A production
`docker compose up --build` compiles the frontend and serves it from FastAPI at
`http://localhost:8000`, keeping the project on one origin and in one deployable image.

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
.venv/bin/transit-delay create-label-policy --target-type reported_delay_state
.venv/bin/transit-delay worker --once
```

`measured_arrival` is available only when the stricter audit also demonstrates retained
post-passage updates corroborated by vehicle positions. Until then the default target is honestly
named “reported target-stop delay state 10–15 minutes later.” The audit used to authorize a label
policy is copied to an immutable, checksum-addressed artifact.

For an offline portfolio demo that never masquerades as live evidence:

```bash
.venv/bin/transit-delay seed-demo
.venv/bin/transit-delay serve --config configs/replay.yaml
```

The rider-first product UI exposes named destinations and stops, automatic downstream forecasts,
plain-language delay ranges, model evidence, and system health. Its light navy/blue/yellow visual
language is transit-inspired while remaining independently branded. The underlying API includes
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
