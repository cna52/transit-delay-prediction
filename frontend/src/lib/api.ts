import type { CollectionMetrics, EvaluationReport, Observation, Prediction, PredictionMetrics, SystemInfo } from "./types"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  observations: () => request<{ items: Observation[]; count: number; generated_at: string }>("/v1/observations?limit=200"),
  collection: () => request<CollectionMetrics>("/v1/metrics/collection"),
  evaluation: () => request<EvaluationReport>("/v1/metrics/evaluation"),
  predictions: () => request<PredictionMetrics>("/v1/metrics/predictions"),
  system: () => request<SystemInfo>("/v1/system"),
  predict: (observation: Observation) => request<Prediction>("/v1/predictions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trip_id: observation.trip_id,
      service_date: observation.service_date,
      start_time: observation.start_time,
      target_stop_id: observation.target_stop_id,
      as_of: observation.as_of,
    }),
  }),
}
