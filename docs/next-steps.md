# Next steps

The offline collection and locked evaluation are complete. The next unfinished deliverable is seven days of post-evaluation serving evidence, followed by a reconciled case study. Do not collect more training data for this phase.

## 1. Preserve the evaluation snapshot

- Keep dataset `ds-a8cd233959b0`, policy `label-reported-delay-state-fixed-lag-a66765a09644`, evaluation report, and model artifact together as the final offline evidence.
- The evaluation was run from code commit `8235d9bda170dc6eac321a13c9a2a370d7376c46`.
- Do not rerun the locked test or tune against it. A new model or changed protocol needs a separately documented evaluation.

## Execution status — 2026-11-25

The API is running in Docker and reports healthy/readiness status with `model-911a62d1e48c`
loaded. The evidence collector and worker are running, and a 15-minute serving probe is scheduled
through the declared window end. A live R5 prediction succeeded at `2026-11-26T01:00:27.610372Z`;
this is the exact monitoring start. The seven-day window ends at `2026-12-03T01:00:27.610372Z`. Startup health, artifact, live-prediction, and service checks are retained in [the serving-window start record](evidence/serving-window-start-2026-11-26.json). Keep the window open through that end and extend it for any interruption. Old telemetry before this timestamp and prior failed probe attempts do not count.

## 2. Start the post-evaluation serving window

- [x] Confirm the selected Ridge artifact (`model-911a62d1e48c`) is available to the API and the API is configured to serve it.
- [x] Start the Docker API and verify `/healthz`, `/readyz`, `/v1/model`, and a live prediction request.
- [x] Recorded start: `2026-11-26T01:00:27.610372Z`. Recorded seven-day end: `2026-12-03T01:00:27.610372Z`. Only predictions in this exact UTC interval count.
- [x] Ensure the collector and worker are running for live features and delayed labels. Keep this serving window's evidence separate from the training collection.

## 3. Capture daily serving evidence for seven days

For each day, retain counts and report:

- prediction requests, request errors, and p50/p95 latency;
- input freshness and stale-input fallbacks;
- model versus persistence fallback counts and reasons;
- predictions whose delayed reported-state labels matured, plus missing/censored labels;
- MAE and bias on matured predictions, with date and route slices where sample sizes allow.

Treat the label as a future reported-delay proxy, not an observed arrival. Report the number of matured and missing labels so accuracy is not presented without coverage context.

## 4. Close and reconcile monitoring

- After seven full days, run the existing monitoring report over only the declared window.
- Check that all API, freshness, fallback, and delayed-label claims can be reproduced from retained reports.
- If serving was interrupted, report the gap and extend the window until seven complete monitored days accrue; do not fill gaps with replay data.
- Verify the API is still healthy and its active model version matches the evaluated artifact.

## 5. Finish and publish the case study

- Update `docs/case-study.md` with the exact dataset and policy versions, code commit, split dates, test results, promotion decision, uncertainty, interval coverage, missing-label rate, and limitations.
- Add the seven-day serving results and clearly separate offline locked-test metrics from online delayed-label monitoring.
- Include reproduction commands and links to the retained evaluation and monitoring reports. Label any replay or synthetic material as demo content.
- Commit and push the documentation and any sanitized summary reports. Keep raw licensed feeds, credentials, and model binaries out of Git.

## Completed offline evaluation snapshot

The test period is November 15–21, 2026 (3,916 labeled examples). Ridge MAE was 1.85 minutes, compared with 2.37 for persistence and 2.48 for historical median. The promotion gate approved Ridge; 90% interval coverage was 90.2%, and the evaluation's overall missing-label rate was 9.3%. These results concern the future reported-delay proxy. Source: `data/evidence-2026-10-22/reports/evaluation.json` (local, Git-ignored).
