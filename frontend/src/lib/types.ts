export type Observation = {
  example_id: string
  trip_id: string
  service_date: string
  start_time: string | null
  route: string
  direction_id: number | null
  target_stop_id: string
  target_stop_name: string | null
  trip_headsign: string | null
  target_stop_sequence: number
  current_stop_sequence: number
  stops_to_target: number
  scheduled_target_arrival: string
  as_of: string
  current_delay_minutes: number
  horizon_minutes: number
  freshness_seconds: number
  delay_trend_minutes: number | null
}

export type Prediction = {
  prediction_id: string
  example_id: string
  target_stop_id: string
  prediction_minutes: number | null
  lower_minutes: number | null
  upper_minutes: number | null
  model_version: string
  quality: "normal" | "fallback" | "degraded"
  observation_timestamp: string
  freshness_seconds: number
  fallback_reason: string | null
  data_mode: "live" | "replay" | "synthetic"
}

export type PredictionMetrics = {
  status: "available" | "pending"
  predictions: number
  requests: number
  labelled: number
  label_coverage: number
  mae_minutes: number | null
  fallback_rate: number
  request_error_rate: number
  latency_ms: { p50: number | null; p95: number | null }
}

export type CollectionMetrics = {
  status: "available" | "pending"
  message?: string
  attempts?: number
  successes?: number
  success_rate?: number
  duplicate_rate?: number
  largest_gap_seconds?: number
  bytes_downloaded?: number
  unique_payloads?: number
  date_from?: string
  date_to?: string
}

export type EvaluationReport = {
  status: "available" | "pending"
  message?: string
  reports?: Array<{
    model_name: string
    overall: { count: number; mae: number; median_absolute_error: number; p90_absolute_error: number; bias: number }
    slices: Record<string, Record<string, { mae: number; count: number }>>
  }>
}

export type SystemInfo = {
  status: string
  api_status: string
  collector_status: string
  worker_status: string
  data_status: "live" | "stale" | "missing" | "replay" | "synthetic"
  data_mode: "live" | "replay" | "synthetic"
  snapshot_age_seconds: number | null
  latest_observation_at: string | null
  snapshot_available: boolean
  observation_count: number
  model_loaded: boolean
  model_error: string | null
  model_version: string
  selected_routes: string[]
  collection: Omit<CollectionMetrics, "status"> | null
  feed_audit: {
    snapshots?: number
    trip_updates?: number
    vehicle_positions?: number
    freshness_seconds?: { median: number; p95: number; max: number }
    stop_field_presence?: Record<string, number>
  } | null
  checked_at: string
}
