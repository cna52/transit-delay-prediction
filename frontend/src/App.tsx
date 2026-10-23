import { useMemo, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  Activity, ArrowRight, BarChart3, BusFront, Check, ChevronRight, CircleAlert,
  Clock3, CloudCog, Database, GitBranch, Info, MapPin, Radio, RefreshCw,
  Server, ShieldCheck,
} from "lucide-react"
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { api } from "./lib/api"
import type { Observation, Prediction } from "./lib/types"
import { Badge, Button, Card } from "./components/ui"
import { cn } from "./lib/utils"

type View = "live" | "performance" | "system"

function time(value: string, offsetMinutes = 0) {
  const date = new Date(value)
  date.setMinutes(date.getMinutes() + offsetMinutes)
  return new Intl.DateTimeFormat("en-CA", {
    hour: "numeric", minute: "2-digit", timeZone: "America/Vancouver",
  }).format(date)
}

function ageLabel(seconds: number | undefined) {
  if (seconds == null) return "Timestamp unavailable"
  if (seconds < 60) return `Updated ${seconds}s ago`
  if (seconds < 3600) return `Updated ${Math.round(seconds / 60)}m ago`
  if (seconds < 86_400) return `Updated ${Math.round(seconds / 3600)}h ago`
  return `Updated ${Math.round(seconds / 86_400)}d ago`
}

function delayLabel(value: number | null | undefined) {
  if (value == null) return "Unavailable"
  if (Math.abs(value) < 0.5) return "On time"
  return `${Math.abs(value).toFixed(1)} min ${value > 0 ? "late" : "early"}`
}

function signedMinutes(value: number | null | undefined) {
  if (value == null) return "—"
  return `${value > 0 ? "+" : ""}${value.toFixed(1)} min`
}

function routeClass(route: string) {
  return route.startsWith("R") ? "route-rapid" : "route-regular"
}

function stopLabel(row: Observation) {
  return row.target_stop_name || `Stop ${row.target_stop_id}`
}

function destinationLabel(row: Observation) {
  return row.trip_headsign ? `Toward ${row.trip_headsign}` : `Route ${row.route}`
}

function delayPosition(value: number | null | undefined) {
  if (value == null) return 50
  return Math.max(3, Math.min(97, ((value + 15) / 30) * 100))
}

function Header({ view, setView, system }: {
  view: View
  setView: (view: View) => void
  system?: import("./lib/types").SystemInfo
}) {
  const items: Array<[View, string, typeof Radio]> = [
    ["live", "Forecast", Radio],
    ["performance", "Model evidence", BarChart3],
    ["system", "System health", Server],
  ]
  const live = system?.data_status === "live"
  const statusLabel = !system ? "API unavailable" : live ? "Live data" :
    system.data_status === "stale" ? "Data is stale" :
      system.data_status === "missing" ? "Waiting for data" : `${system.data_status} mode`
  return <>
    <header className="topbar">
      <button className="brand" onClick={() => setView("live")} aria-label="OnTime forecast home">
        <span className="brand-mark"><BusFront size={21} /></span>
        <span><b>OnTime</b><small>Metro Vancouver</small></span>
      </button>
      <nav aria-label="Main navigation">
        {items.map(([id, label, Icon]) => <button key={id} onClick={() => setView(id)} aria-current={view === id ? "page" : undefined} className={cn("nav-button", view === id && "active")}>
          <Icon size={16} />{label}
        </button>)}
      </nav>
      <div className={cn("connection", live ? "online" : system ? "stale" : "offline")}><span aria-hidden="true" />{statusLabel}</div>
    </header>
    <nav className="mobile-nav" aria-label="Mobile navigation">
      {items.map(([id, label, Icon]) => <button key={id} onClick={() => setView(id)} aria-current={view === id ? "page" : undefined} className={cn(view === id && "active")}><Icon size={19} /><span>{label.split(" ")[0]}</span></button>)}
    </nav>
  </>
}

function EmptyState({ error }: { error?: Error | null }) {
  return <Card className="empty-state" role="status">
    <span className="empty-icon"><Database size={24} /></span>
    <h3>{error ? "Live forecasts are unavailable" : "Waiting for current trips"}</h3>
    <p>{error ? "The prediction service could not be reached. Check System health for details." : "Supported buses will appear here as fresh realtime observations arrive."}</p>
  </Card>
}

function ObservationCard({ row, active, onSelect }: { row: Observation; active: boolean; onSelect: () => void }) {
  return <button className={cn("trip-card", active && "active")} onClick={onSelect} aria-pressed={active}>
    <span className={cn("route-pill", routeClass(row.route))}>{row.route}</span>
    <span className="trip-main">
      <b>{destinationLabel(row)}</b>
      <small><MapPin size={12} /> {stopLabel(row)}</small>
      <small>{row.stops_to_target} stops away · scheduled {time(row.scheduled_target_arrival)}</small>
    </span>
    <span className={cn("trip-delay", row.current_delay_minutes > 0.5 ? "late" : row.current_delay_minutes < -0.5 ? "early" : "ontime")}><b>{delayLabel(row.current_delay_minutes)}</b><small>reported now</small></span>
    <ChevronRight size={18} className="chevron" aria-hidden="true" />
  </button>
}

function ForecastPanel({ observation, prediction, loading, error, onRefresh }: {
  observation: Observation
  prediction?: Prediction
  loading: boolean
  error?: Error | null
  onRefresh: () => void
}) {
  const predictedDelay = prediction?.prediction_minutes
  const expectedArrival = predictedDelay == null ? null : time(observation.scheduled_target_arrival, predictedDelay)
  const lower = prediction?.lower_minutes
  const upper = prediction?.upper_minutes
  const isFallback = prediction?.quality === "fallback" || prediction?.quality === "degraded"
  return <Card className="forecast-panel" aria-live="polite">
    <div className="forecast-head">
      <div>
        <span className="eyebrow">Your selected bus</span>
        <h2><span className={cn("route-pill", routeClass(observation.route))}>{observation.route}</span>{destinationLabel(observation)}</h2>
        <p><MapPin size={14} /> {stopLabel(observation)}</p>
      </div>
      <Badge tone={observation.freshness_seconds <= 90 ? "green" : "amber"}><Radio size={12} /> {ageLabel(observation.freshness_seconds)}</Badge>
    </div>

    <div className={cn("forecast-outcome", loading && "loading")}>
      <span className="outcome-label">Expected at this stop</span>
      <strong>{loading ? "Checking…" : expectedArrival ?? "—"}</strong>
      <div className={cn("delay-summary", predictedDelay != null && predictedDelay > 0.5 ? "late" : predictedDelay != null && predictedDelay < -0.5 ? "early" : "ontime")}>
        {loading ? "Using the latest vehicle report" : prediction ? delayLabel(predictedDelay) : "Forecast unavailable"}
      </div>
      <small>{observation.horizon_minutes.toFixed(1)} minutes ahead · scheduled {time(observation.scheduled_target_arrival)}</small>
    </div>

    {prediction && <div className="delay-scale" aria-label={`Estimated delay range from ${delayLabel(lower)} to ${delayLabel(upper)}`}>
      <div className="scale-labels"><span>Early</span><span>On time</span><span>Late</span></div>
      <div className="scale-track">
        <span className="range" style={{ left: `${delayPosition(lower)}%`, width: `${Math.max(2, delayPosition(upper) - delayPosition(lower))}%` }} />
        <i className="zero" />
        <i className="estimate" style={{ left: `${delayPosition(predictedDelay)}%` }} />
      </div>
      <div className="range-copy"><span>{signedMinutes(lower)}</span><b>Estimated range</b><span>{signedMinutes(upper)}</span></div>
    </div>}

    <div className="forecast-facts">
      <div><Clock3 /><span>Forecast window<b>{observation.horizon_minutes.toFixed(1)} min</b></span></div>
      <div><MapPin /><span>Target distance<b>{observation.stops_to_target} stops</b></span></div>
      <div><GitBranch /><span>Current change<b>{observation.delay_trend_minutes == null ? "Still learning" : signedMinutes(observation.delay_trend_minutes)}</b></span></div>
    </div>

    {error && <div className="inline-error" role="alert"><CircleAlert size={17} />{error.message}</div>}
    <Button variant="ghost" onClick={onRefresh} disabled={loading} className="refresh-forecast">
      <RefreshCw className={loading ? "spin" : ""} size={16} /> Refresh forecast
    </Button>
    {prediction && <div className={cn("model-note", isFallback && "fallback-note")}><Info size={16} /><span>
      {isFallback ? <><b>Current-delay baseline.</b> This estimate assumes the reported delay continues to the target stop because no trained model has been promoted yet.</> : <><b>ML forecast.</b> Served by model {prediction.model_version} after passing the project’s evaluation gates.</>}
    </span></div>}
  </Card>
}

function LiveView({ dataStatus, dataMode }: { dataStatus?: string; dataMode?: string }) {
  const observations = useQuery({ queryKey: ["observations"], queryFn: api.observations, refetchInterval: 30_000 })
  const [route, setRoute] = useState("All")
  const [selectedId, setSelectedId] = useState<string>()
  const rows = useMemo(() => observations.data?.items ?? [], [observations.data?.items])
  const routes = useMemo(() => ["All", ...Array.from(new Set(rows.map(row => row.route))).sort()], [rows])
  const visible = route === "All" ? rows : rows.filter(row => row.route === route)
  const selected = visible.find(row => row.example_id === selectedId) ?? visible[0]
  const forecast = useQuery({
    queryKey: ["forecast", selected?.example_id],
    queryFn: () => selected ? api.predict(selected) : Promise.reject(new Error("Select a trip")),
    enabled: Boolean(selected),
    retry: 0,
    staleTime: 30_000,
  })
  const modeLabel = dataStatus === "live" ? "Using live vehicle reports" : dataMode === "synthetic" ? "Synthetic portfolio demonstration" : dataMode === "replay" ? "Historical replay" : "Historical data snapshot"

  return <main>
    <section className="rider-intro">
      <div><Badge tone={dataStatus === "live" ? "green" : "amber"}><Activity size={12} /> {modeLabel}</Badge><h1>Will this bus still be late<br/><em>when it reaches your stop?</em></h1><p>Select a current trip to estimate its delay at a downstream stop 10–15 minutes from now.</p></div>
      <div className="intro-stats" aria-label="Available forecast coverage"><div><b>{rows.length}</b><span>current trips</span></div><div><b>{routes.length - 1}</b><span>routes</span></div><div><b>10–15</b><span>minutes ahead</span></div></div>
    </section>
    <section className="workspace">
      <div className="list-column">
        <div className="section-title"><div><span className="eyebrow">Current service</span><h2>Choose a bus</h2></div><button className="icon-button" onClick={() => observations.refetch()} aria-label="Refresh current trips"><RefreshCw size={17} className={observations.isFetching ? "spin" : ""} /></button></div>
        <div className="filters" aria-label="Filter by route">{routes.map(value => <button className={cn(route === value && "active")} onClick={() => { setRoute(value); setSelectedId(undefined) }} aria-pressed={route === value} key={value}>{value === "All" ? "All routes" : value}</button>)}</div>
        <div className="trip-list">
          {observations.isLoading && Array.from({ length: 4 }, (_, index) => <div className="trip-skeleton" key={index} />)}
          {!observations.isLoading && !visible.length && <EmptyState error={observations.error} />}
          {visible.map(row => <ObservationCard row={row} key={row.example_id} active={selected?.example_id === row.example_id} onSelect={() => setSelectedId(row.example_id)} />)}
        </div>
      </div>
      <div className="forecast-column">{selected ? <ForecastPanel observation={selected} prediction={forecast.data} loading={forecast.isLoading || forecast.isFetching} error={forecast.error} onRefresh={() => forecast.refetch()} /> : <Card className="forecast-placeholder"><BusFront size={34}/><h2>Select a current bus</h2><p>Its downstream delay estimate will appear here automatically.</p></Card>}</div>
    </section>
  </main>
}

function PerformanceView() {
  const evaluation = useQuery({ queryKey: ["evaluation"], queryFn: api.evaluation })
  const online = useQuery({ queryKey: ["prediction-metrics"], queryFn: api.predictions })
  const reports = evaluation.data?.reports ?? []
  const chartData = reports.map(report => ({ name: report.model_name.replaceAll("_", " "), MAE: Number(report.overall.mae.toFixed(2)), P90: Number(report.overall.p90_absolute_error.toFixed(2)) }))
  const best = reports.length ? [...reports].sort((a, b) => a.overall.mae - b.overall.mae)[0] : undefined
  return <main className="page-content">
    <section className="page-heading"><Badge tone="blue"><ShieldCheck size={12}/> Leakage-aware evaluation</Badge><h1>Evidence before<br/><em>model promotion.</em></h1><p>Scores use future chronological windows and must outperform simple delay baselines.</p></section>
    {online.data && online.data.requests > 0 && <div className="metric-cards"><Card><span>Prediction requests</span><b>{online.data.requests.toLocaleString()}</b><small>{(online.data.request_error_rate * 100).toFixed(1)}% errors</small></Card><Card><span>p95 API latency</span><b>{online.data.latency_ms.p95 == null ? "—" : `${online.data.latency_ms.p95.toFixed(1)} ms`}</b><small>observed locally</small></Card><Card><span>Delayed online MAE</span><b>{online.data.mae_minutes == null ? "Pending" : `${online.data.mae_minutes.toFixed(2)} min`}</b><small>{online.data.labelled} matured forecasts</small></Card></div>}
    {evaluation.isLoading ? <div className="metric-skeleton" /> : reports.length ? <><div className="metric-cards"><Card><span>Best test MAE</span><b>{best?.overall.mae.toFixed(2)} min</b><small>{best?.model_name}</small></Card><Card><span>Evaluated examples</span><b>{best?.overall.count.toLocaleString()}</b><small>chronological test set</small></Card><Card><span>Models compared</span><b>{reports.length}</b><small>including baselines</small></Card></div><Card className="chart-card"><div className="card-heading"><div><span className="eyebrow">Held-out test window</span><h2>Model versus baselines</h2></div><Badge tone="neutral">Lower is better</Badge></div><div className="chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}><CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#d7e1e8"/><XAxis dataKey="name" tick={{ fill: "#526779", fontSize: 12 }} axisLine={false} tickLine={false}/><YAxis unit="m" tick={{ fill: "#526779", fontSize: 12 }} axisLine={false} tickLine={false}/><Tooltip contentStyle={{ background: "#fff", border: "1px solid #cad7df", borderRadius: 10 }}/><Bar dataKey="MAE" fill="#0070c9" radius={[6,6,0,0]}/><Bar dataKey="P90" fill="#ffcc33" radius={[6,6,0,0]}/></BarChart></ResponsiveContainer></div></Card></> : <Card className="evaluation-gate"><div className="gate-icon"><ShieldCheck /></div><div><Badge tone="amber">Evidence pending</Badge><h2>The model is not ready—and the product says so</h2><p>{evaluation.data?.message ?? "No evaluation report exists yet."} Results remain hidden until real labels and chronological tests are available.</p><div className="gate-steps"><span><i>1</i>Collect service days</span><span><i>2</i>Audit delay labels</span><span><i>3</i>Compare baselines</span><span><i>4</i>Pass promotion gates</span></div></div></Card>}
  </main>
}

function StatusRow({ icon, title, detail, ok = true }: { icon: ReactNode; title: string; detail: string; ok?: boolean }) {
  return <div className="status-row"><span className="status-icon">{icon}</span><div><b>{title}</b><small>{detail}</small></div><Badge tone={ok ? "green" : "amber"}>{ok ? <Check size={12}/> : <CircleAlert size={12}/>} {ok ? "Healthy" : "Attention"}</Badge></div>
}

function SystemView() {
  const system = useQuery({ queryKey: ["system"], queryFn: api.system, refetchInterval: 30_000 })
  const collection = system.data?.collection
  const audit = system.data?.feed_audit
  return <main className="page-content"><section className="page-heading compact"><Badge tone="green"><CloudCog size={12}/> Operations</Badge><h1>How each forecast<br/><em>gets to the screen.</em></h1><p>Live collection, data freshness, processing, and model readiness are shown separately.</p></section><div className="system-grid"><Card className="status-card"><div className="card-heading"><div><span className="eyebrow">Runtime</span><h2>Service status</h2></div><span className="pulse-dot" /></div><StatusRow icon={<Server/>} title="Prediction API" detail="Responding to requests" ok={system.data?.api_status === "healthy"}/><StatusRow icon={<Radio/>} title="Realtime collector" detail={system.data?.collector_status ?? "Unavailable"} ok={["healthy", "synthetic"].includes(system.data?.collector_status ?? "")}/><StatusRow icon={<GitBranch/>} title="Pipeline worker" detail={system.data?.worker_status ?? "Unavailable"} ok={["healthy", "synthetic"].includes(system.data?.worker_status ?? "")}/><StatusRow icon={<Database/>} title="Forecast data" detail={`${system.data?.observation_count ?? 0} observations · ${system.data?.data_status ?? "missing"}`} ok={["live", "replay", "synthetic"].includes(system.data?.data_status ?? "")}/></Card><Card className="pipeline-card"><div className="card-heading"><div><span className="eyebrow">Data path</span><h2>Current pipeline</h2></div></div><div className="pipeline-flow"><div className="pipeline-node"><Radio/><span><b>GTFS realtime</b><small>quota-aware polling</small></span></div><i/><div className="pipeline-node"><Database/><span><b>Raw archive</b><small>immutable payloads</small></span></div><i/><div className="pipeline-node"><GitBranch/><span><b>Features</b><small>point-in-time joins</small></span></div><i/><div className="pipeline-node"><Server/><span><b>FastAPI</b><small>versioned inference</small></span></div></div></Card></div><div className="metric-cards operations"><Card><span>Archived attempts</span><b>{collection?.attempts?.toLocaleString() ?? "—"}</b><small>{collection ? `${collection.date_from} to ${collection.date_to}` : "Report pending"}</small></Card><Card><span>Median source freshness</span><b>{audit?.freshness_seconds ? `${audit.freshness_seconds.median.toFixed(1)}s` : "—"}</b><small>{audit ? `${audit.snapshots} audited snapshots` : "Audit pending"}</small></Card><Card><span>Unique payloads</span><b>{collection?.unique_payloads?.toLocaleString?.() ?? "—"}</b><small>{collection?.duplicate_rate == null ? "Report pending" : `${(collection.duplicate_rate * 100).toFixed(1)}% duplicates`}</small></Card><Card><span>Largest collection gap</span><b>{collection?.largest_gap_seconds == null ? "—" : `${Math.round(collection.largest_gap_seconds)}s`}</b><small>within reporting window</small></Card></div><Card className="audit-card"><div className="card-heading"><div><span className="eyebrow">Feed feasibility</span><h2>Observed field coverage</h2></div><Badge tone={audit ? "green" : "neutral"}>{audit ? "Audited" : "Pending"}</Badge></div>{audit?.stop_field_presence ? <div className="coverage-list">{Object.entries(audit.stop_field_presence).map(([field, value]) => <div key={field}><span>{field.replaceAll("_", " ")}</span><div><i style={{ width: `${value * 100}%` }}/></div><b>{(value * 100).toFixed(1)}%</b></div>)}</div> : <p className="pending-copy">Field evidence appears after both realtime feeds have been collected and audited.</p>}</Card></main>
}

export default function App() {
  const [view, setView] = useState<View>("live")
  const system = useQuery({ queryKey: ["app-system"], queryFn: api.system, refetchInterval: 30_000, retry: 0 })
  return <div className="app-shell"><Header view={view} setView={setView} system={system.data}/>{view === "live" && <LiveView dataStatus={system.data?.data_status} dataMode={system.data?.data_mode}/>} {view === "performance" && <PerformanceView/>}{view === "system" && <SystemView/>}<footer><div><BusFront size={18}/><b>OnTime</b><span>Independent transit-delay project</span></div><p>Not affiliated with or endorsed by TransLink. Transit data is supplied by TransLink under its Open API terms. Forecasts are experimental and should not be the sole basis for travel decisions.</p><a href="/docs">API docs <ArrowRight size={14}/></a></footer></div>
}
