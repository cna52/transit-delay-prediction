import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><App /></QueryClientProvider>)
}

const system = {
  status: "ready",
  api_status: "healthy",
  collector_status: "healthy",
  worker_status: "healthy",
  data_status: "live",
  data_mode: "live",
  observation_count: 1,
}

describe("App", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("renders the rider question and an honest empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path.includes("observations")
        ? { items: [], count: 0, generated_at: new Date().toISOString() }
        : system
      return { ok: true, json: async () => body } as Response
    }))

    renderApp()

    expect(screen.getByText("Will this bus still be late")).toBeInTheDocument()
    expect(await screen.findByText("Waiting for current trips")).toBeInTheDocument()
  })

  it("uses rider-facing GTFS names and automatically requests a forecast", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.includes("observations")) return {
        ok: true,
        json: async () => ({
          count: 1,
          generated_at: "2026-08-10T18:00:00Z",
          items: [{
            example_id: "example-1",
            trip_id: "trip-1",
            service_date: "2026-08-10",
            start_time: null,
            route: "099",
            direction_id: 0,
            target_stop_id: "s3",
            target_stop_name: "Broadway at Cambie Street",
            trip_headsign: "UBC",
            target_stop_sequence: 14,
            current_stop_sequence: 8,
            stops_to_target: 6,
            scheduled_target_arrival: "2026-08-10T18:12:00Z",
            as_of: "2026-08-10T18:00:00Z",
            current_delay_minutes: 2,
            horizon_minutes: 12,
            freshness_seconds: 10,
            delay_trend_minutes: 0.5,
          }],
        }),
      } as Response
      if (path.includes("predictions")) return {
        ok: true,
        json: async () => ({
          prediction_id: "prediction-1",
          example_id: "example-1",
          target_stop_id: "s3",
          prediction_minutes: 4,
          lower_minutes: 1,
          upper_minutes: 7,
          model_version: "persistence-v1",
          quality: "fallback",
          observation_timestamp: "2026-08-10T18:00:00Z",
          freshness_seconds: 10,
          fallback_reason: "no_promoted_model",
          data_mode: "live",
        }),
      } as Response
      return { ok: true, json: async () => system } as Response
    })
    vi.stubGlobal("fetch", fetchMock)

    renderApp()

    expect((await screen.findAllByText("Toward UBC")).length).toBeGreaterThan(0)
    expect((await screen.findAllByText("Broadway at Cambie Street")).length).toBeGreaterThan(0)
    expect(await screen.findByText(/4.0 min late/)).toBeInTheDocument()
    expect(await screen.findByText(/11:16/)).toBeInTheDocument()
    expect(await screen.findByText(/Current-delay baseline/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/v1/predictions"))).toBe(true)
  })
})
