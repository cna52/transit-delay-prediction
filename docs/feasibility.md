# Feasibility audit and first vertical slice

The regression task is gated on actual producer behaviour. GTFS permits past and future stop
updates, and producers may discard past updates. A future estimate must not be renamed an actual
arrival merely because its timestamp has passed.

## Run the audit

1. Register for a TransLink API key and configure `.env`.
2. Download and profile the current Static feed.
3. Collect both realtime feeds every four minutes for two service days for the spike.
4. Replay route `099`; use `R4` if its coverage is higher.
5. For at least ten trip timelines, inspect:
   - field presence and timestamp freshness;
   - unique Static joins;
   - whether target stop updates persist after passage;
   - whether their time/delay changes after passage;
   - agreement with Vehicle Position stop transitions;
   - cancellation, skipping, missingness, and service-day boundaries.
6. Record storage bytes/day and projected eight-week volume.

The slice passes with two service days, at least 100 joined eligible target events, at least 90%
unique schedule joins, and at least 70% candidate-label coverage within 30 minutes. Those are
engineering gates, not achieved claims.

Run `transit-delay feed-audit` and `transit-delay trip-timelines --config configs/evidence.yaml`.
Run `transit-delay feasibility-report --config configs/evidence.yaml` after refreshing the
collection and dataset-quality reports. It marks each gate, counts only complete Vancouver days,
requires feature examples from two of those dates in the frozen audit, and names routes worth a
scoped replay if the all-route candidate rate fails. A route suggestion
is provisional until its own strict Static join rate and manual timelines are checked.
The timeline report samples ten distinct trips across available routes and service dates for
manual review. Once two complete usable dates exist, it samples from those dates so the required
review cannot be filled with trips from a partial startup date. Candidate coverage includes only
examples whose full 30-minute window has elapsed;
newer examples appear as pending. Create a label policy only after the gates and manual review
pass. Copy the generated timeline report to `trip-timelines-reviewed.json`, mark ten distinct
trips from both days as `reviewed`, and record a substantive `review_notes` entry for each. The
report carries the checksum of its frozen feed audit; the policy archives and verifies both exact
files. The CLI enforces two usable service days, at least 90% strict Static joins, at least 100
eligible examples, and 70% candidate coverage. A
`measured_arrival` policy additionally requires at least ten post-passage target updates retained
across snapshots and ten cases corroborated by vehicle positions. The exact audit is copied to a
checksum-addressed artifact under `data/state/label-audits/`.

The safe default is `reported_delay_state`: predict TransLink's reported target-stop delay state
10–15 minutes later and describe it as a proxy, not an observed arrival. If that target is too
sparse or unstable, run `transit-delay route-scope-report 099 --config configs/evidence.yaml`
for a recommended route. This replay writes a separate report and leaves live serving data
untouched. Narrow the active configuration only if the scoped join and label gates also pass. If strict Static joins or
even the proxy remain unreliable, stop or change the project rather than mislabel it.
An exploratory shorter-horizon replay can use
`transit-delay route-scope-report R5 --config configs/evidence.yaml --min-horizon-seconds 300 --max-horizon-seconds 600`.
The report is isolated under `route-scopes/` and does not change the approved 10–15-minute target,
the live service, or its gate. A shorter horizon is a different prediction question and needs a
new policy decision before evaluation.
To inspect a fixed future reporting lag, add `--label-lag-seconds 300` and
`--candidate-window-seconds 480` to the route replay. This asks whether the previously selected
target stop has a reported delay value 5–13 minutes after prediction. The replay records the
actual candidate observation lag and marks its decision `exploratory_target`; it cannot approve
a production label policy. The original target and its 30-minute candidate window remain the
production audit until a new protocol is reviewed and locked.

The feasibility report explains missing candidates as no trip update during the window, a trip
update without the target stop, or a target stop without an arrival value. It further separates
windows with no successful Trip Updates poll from windows where the feed was polled but the trip
was absent. `candidate_coverage_when_feed_polled` is diagnostic only: the 70% gate still uses all
mature examples. `by_service_date` shows coverage by the feature's GTFS service date, which can
cross a local midnight.

The initial live sample does not establish feasibility: it contains too few examples and no
confirmed retained post-passage updates. That is a current finding, not a permanent conclusion
about the feed.
