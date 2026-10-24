# Operations runbook

## Local operation

Create `.env` from `.env.example`, keep it uncommitted, and start the collector, worker, and API
with Docker Compose:

```bash
docker compose up --build
docker compose ps
curl http://localhost:8000/healthz
curl http://localhost:8000/v1/system
```

Collection can be stopped whenever the laptop is unavailable; immutable manifests make gaps
visible instead of hiding them. Aim for 28 usable service days before the locked comparison. A
usable day has successful Trip Update snapshots spanning at least eight distinct local hours.
Do not put the API key in a URL, log, image layer, or committed file.

The October 2026 evidence run uses `configs/evidence.yaml` and an isolated ignored data directory.
User LaunchAgents `com.cna52.transit-delay.collector` and `com.cna52.transit-delay.worker`
run the two feeds every four minutes and rebuild reports on the configured schedule. Check
`launchctl list | grep com.cna52.transit-delay` and the state files under
`data/evidence-2026-10-22/state/`. The Docker API mounts that same directory through
`compose.evidence.yaml`; run `docker compose -f compose.evidence.yaml up --build -d` to restart it.
Sleeping or powering off this computer creates real collection gaps and extends the evidence
window. Do not combine this directory with the August sample.

The `com.cna52.transit-delay.probe` LaunchAgent requests one fresh prediction per selected route
every 15 minutes. Its attempts are retained under the isolated data directory, and the API logs
prediction time, latency, freshness, and fallback reason. Check current telemetry with
`transit-delay prediction-report --config configs/evidence.yaml`. After the locked evaluation,
pass `--start-date YYYY-MM-DD --end-date YYYY-MM-DD` to retain a separate seven-day report for
the subsequent monitoring window. Earlier probes are baseline diagnostics and do not count toward
that seven-day window.

Serving refreshes replay the latest hour of Trip Updates for low latency. The daily offline
rebuild, feed audit, and evaluation still read the full immutable archive.

For a durable offline demo, run `transit-delay seed-demo` and serve `configs/replay.yaml`. API
responses identify replay/synthetic mode; those rows must not be included in live reliability or
model claims.

## Incidents

- HTTP 401: stop collection and rotate/check the key; retries consume quota.
- HTTP 429/quota exhaustion: do not bypass the durable counter; resume next Vancouver service day.
- Static join-rate drop: download a new Static feed and replay; do not fuzzy-match.
- Disk warning: sync, verify hashes, then reduce Vehicle Position cadence or retention.
- Corrupt or unapproved model: promotion is refused and persistence remains available.
- Stale snapshot: API returns a degraded baseline prediction.
