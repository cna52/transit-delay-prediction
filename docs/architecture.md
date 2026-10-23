# Architecture

```text
TransLink Static + GTFS-Realtime
          │
          ▼
 quota-aware collector ──► immutable compressed payloads + fetch manifests + heartbeat
          │
          ▼
 point-in-time Static registry / strict schedule join ──► quarantine and quality counts
          │
          ▼
 local worker: serving refresh / reports / delayed labels ──► versioned datasets
          │
          ▼
 baselines / Ridge / optional LightGBM ──► checksummed promoted artifact
          │
          ▼
 FastAPI + immutable serving snapshot ──► prediction log / delayed evaluation
```

The collector, worker, and API run locally through Docker Compose. Training and analytics run on
the same laptop. The complete API and UI remain demonstrable in explicitly marked replay or
synthetic mode when live collection is stopped.

DuckDB and Zstandard-compressed Parquet form the analytical layer. Dataset builds also retain
deterministic JSONL as a portable interchange and serving format, while the DuckDB catalog records
dataset lineage and points to immutable Parquet artifacts.

There is no Kafka, Spark, orchestration server, feature store, MLflow server, PostgreSQL server,
or Kubernetes cluster. None solves a current scale or concurrency problem.

The collector and worker publish separate atomic heartbeats. `/v1/system` reports API health,
collector state, worker state, data freshness, and data mode independently, so a healthy API
cannot make stale data look live.
