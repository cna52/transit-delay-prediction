# Data contract

## Identity

A scheduled trip instance is identified by:

```text
(static_feed_version, service_date, trip_id, optional_start_time)
```

`trip_id` is never assumed stable across weekly Static feeds. Stop updates join by
`stop_sequence`; `stop_id` validates or disambiguates that join.

## Time

- Source and storage timestamps are UTC and timezone-aware.
- GTFS service-day operations use `America/Vancouver`.
- Static times above 24:00 are offsets from service-day midnight.
- Every transform receives an explicit `as_of` time.

## Example

One example selects the first downstream stop whose persistence-estimated arrival is 10–15
minutes after `as_of`. Persistence-estimated arrival equals scheduled arrival plus current
reported delay. The selected stop is immutable thereafter.

The default target is the delay value TransLink reports for that same target stop at
`as_of + horizon`. It is named `reported_delay_state` and is a forecast-state proxy, not a claim
that an arrival was observed. `measured_arrival` may be enabled only by the stricter retained-update
and vehicle-position audit.

One example per trip every five minutes is the intended collection policy. All examples from a
trip instance remain in the same temporal split.

`target_stop_name` and `trip_headsign` are nullable presentation metadata copied from the same
point-in-time Static feed version. They are returned by the observation API but are excluded from
the model feature lists. Older snapshots without them remain readable and fall back to stop ID and
direction in the UI.

## Label states

- `labelled`: a delayed value passed the versioned policy for its explicitly named target.
- `audit_required`: compatibility state used before a label policy exists; production dataset
  commands refuse to run without the checksummed policy file.
- `censored`: no trustworthy target event became available.
- `invalid`: cancellation, skipped target stop, or another event makes regression undefined.

Cancellation and censoring rates are monitored separately and never silently scored as zero delay.

## Unsupported v1 inputs

Added, unscheduled, duplicated, replacement, cancelled, unknown-version, and ambiguous trip
instances are quarantined or returned unavailable. Fuzzy route/time matching is prohibited for
training labels.
