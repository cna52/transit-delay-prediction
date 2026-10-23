# Operations runbook

## Local operation

Create `.env` from `.env.example`, keep it uncommitted, and start the collector, worker, API, and
React production build with Docker Compose:

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

For a durable offline demo, run `transit-delay seed-demo` and serve `configs/replay.yaml`. The UI
must say replay/synthetic and those rows must not be included in live reliability or model claims.

## Incidents

- HTTP 401: stop collection and rotate/check the key; retries consume quota.
- HTTP 429/quota exhaustion: do not bypass the durable counter; resume next Vancouver service day.
- Static join-rate drop: download a new Static feed and replay; do not fuzzy-match.
- Disk warning: sync, verify hashes, then reduce Vehicle Position cadence or retention.
- Corrupt or unapproved model: promotion is refused and persistence remains available.
- Stale snapshot: API returns a degraded baseline prediction.
