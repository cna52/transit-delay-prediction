# Evidence and completion rubric

Do not write résumé claims until generated evidence supports them.

Collect and publish:

- unique raw snapshots, parsed observations/trips, feature rows, labelled examples, dates, feed
  versions, storage bytes, and label coverage;
- scheduled/attempted/successful polls, largest gap, parse and join rates, quota use, deployment
  duration, and restarts;
- exact temporal split dates, model and baseline MAE, paired differences, rolling-fold wins,
  slice errors, and interval coverage;
- API request count, error/fallback rates, p50/p95 latency, artifact checksum, and deployment dates;
- test count/coverage and named failure cases;
- monitoring findings and resulting changes.

Core completion requires a defensible label or honestly renamed proxy, a multi-week versioned
archive, reproducible point-in-time dataset, locked chronological comparison with both baselines,
a Docker-served champion or baseline, one week of delayed evaluation, and an offline replay demo.
The dashboard is optional.

Generate the current evidence summary with `transit-delay evidence-report`. It reports pending
items instead of inventing values and separates live, replay, and synthetic data modes. Before
publishing a case study, retain the JSON/HTML reports for collection reliability, label semantics,
dataset quality, locked evaluation and promotion, API telemetry, and delayed-label monitoring.

Recommended minimum evidence window: 28 usable service days for train/validation/test and rolling
checks, plus at least seven days of delayed online evaluation after promotion. These are completion
criteria, not claims that the project has already reached them.
