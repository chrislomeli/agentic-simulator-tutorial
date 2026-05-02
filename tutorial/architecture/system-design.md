# OGAR System Design

**Operational Ground-level Agent Response**

---

## Problem Statement

Wildfire ignition is predictable. The physical conditions that precede a fire — temperature, humidity, wind speed, fuel moisture — are measurable, and their dangerous combinations are well understood. What's hard is synthesizing those readings across a large sensor network in real time, detecting when conditions are converging toward danger, and doing so with enough lead time to be useful.

This system takes a continuous stream of sensor readings from a simulated wildfire environment and answers one question per geographic cluster, per time step:

> **Has this cluster crossed the threshold for elevated fire danger, and how confident are we?**

When the answer is yes, the system escalates findings to a supervisor that correlates across clusters and assesses whether the available resources are positioned to respond.

---

## What This System Does

1. **Ingests sensor events** — temperature, humidity, wind, smoke, fuel moisture — grouped by geographic cluster.

2. **Evaluates fire danger per cluster** — an LLM agent applies domain rules to the event window, weighs corroborating evidence across sensor types, and produces a structured finding: danger level, affected sensors, confidence, summary.

3. **Correlates across clusters** — a supervisor agent receives all cluster findings, identifies regional patterns (isolated anomaly vs. multi-cluster event), and produces a situation assessment.

4. **Assesses resource preparedness** *(later sessions)* — given elevated danger, are the right resources (air support, ground crews, equipment) available and positioned to respond?

---

## What This System Does Not Do

**Sensor fusion is out of scope.** This system receives events that have already been grouped by cluster. The grouping policy — whether fixed geographic assignment, proximity-based, or a dedicated fusion model — is upstream and outside this system's boundary. The supervisor receives `events_by_cluster: Dict[str, List[SensorEvent]]` and does not care how that dict was produced.

This is a deliberate boundary. Sensor fusion is a valid and interesting future extension, but it slots in *before* the supervisor without changing anything this system builds. If we attempt it later, it does not affect the agent architecture.

**Actuator execution is out of scope.** The system produces `ActuatorCommand` objects (dispatch helicopter, alert ground crew, escalate to incident command). What executes those commands — a real dispatch system, a simulation callback, a human operator — is outside scope. The tutorial stubs this indefinitely.

---

## System Layers

```
┌─────────────────────────────────────────────┐
│              Simulation Layer               │
│  World engine · Fire physics · Cell states  │
└───────────────────┬─────────────────────────┘
                    │ cell state per tick
┌───────────────────▼─────────────────────────┐
│               Sensor Layer                  │
│  Temperature · Humidity · Wind · Smoke ···  │
│  Each sensor reads local conditions,        │
│  adds noise, emits SensorEvent              │
└───────────────────┬─────────────────────────┘
                    │ List[SensorEvent] per tick
┌───────────────────▼─────────────────────────┐
│              Bridge Layer  (not yet built)  │
│  Drives world ticks                         │
│  Groups events by cluster_id                │
│  Invokes supervisor once per tick           │
└───────────────────┬─────────────────────────┘
                    │ SupervisorState(events_by_cluster)
┌───────────────────▼─────────────────────────┐
│            Supervisor Agent                 │
│  Fans out to cluster agents in parallel     │
│  Waits for all findings (sync barrier)      │
│  Correlates across clusters (LLM)           │
│  Produces situation assessment + commands   │
└──────┬────────────────────────┬─────────────┘
       │ Send(ClusterAgentState) │ (parallel)
┌──────▼──────┐          ┌──────▼──────┐
│   Cluster   │          │   Cluster   │  ···
│   Agent N   │          │   Agent S   │
│             │          │             │
│ ingest      │          │ ingest      │
│ classify    │          │ classify    │
│ report      │          │ report      │
└──────┬──────┘          └──────┬──────┘
       │ AnomalyFinding          │ AnomalyFinding
       └────────────┬────────────┘
                    │ aggregate_findings reducer
              SupervisorState.cluster_findings
```

---

## Agent Architecture — Why Two Levels

**Cluster agents** run in parallel, one per active cluster. Each has a narrow job: given the sensor event window for my cluster, is there a fire danger? The cluster agent is the domain expert — it knows the thresholds, weighs corroborating evidence, and produces a finding with a confidence score. It does not know about other clusters.

**The supervisor** runs once per tick after all cluster agents complete. Its job is pattern recognition across clusters: a single elevated cluster is different from three adjacent clusters all showing critical conditions simultaneously. The supervisor has the full geographic picture; cluster agents do not. The supervisor also owns the resource layer — matching findings to available response capacity.

This separation is deliberate:
- Cluster agents are cheap and parallel. You can have 20 of them running simultaneously.
- The supervisor makes one expensive cross-cluster reasoning call with the aggregated results.
- Either layer can be upgraded independently. A better cluster agent doesn't change the supervisor contract. A richer supervisor doesn't change what cluster agents produce.

---

## Data Model

### SensorEvent
The universal envelope for all sensor readings. Produced by sensors, consumed by cluster agents.

```
source_id     — which physical sensor
source_type   — "temperature" | "humidity" | "wind" | "smoke" | ...
cluster_id    — routing key (pre-assigned upstream)
sim_tick      — simulation time step
confidence    — sensor health estimate (0.0–1.0)
payload       — domain dict: {"celsius": 52.4} or {"relative_humidity_pct": 12.0} etc.
```

`payload` is opaque to the routing layer. Only the cluster agent's LLM (and tools) interpret it.

### AnomalyFinding
Produced by cluster agents, consumed by the supervisor. The output of one cluster agent invocation.

```
finding_id        — UUID, stable across retries
cluster_id        — which cluster produced this
anomaly_type      — "threshold_breach" | "sensor_fault" | "correlated_event" | "none"
affected_sensors  — source_ids that contributed to the finding
confidence        — 0.0–1.0, weighted by corroborating evidence
summary           — human-readable explanation for the supervisor's context
raw_context       — sensor readings that led to this finding
```

### ActuatorCommand
Produced by the supervisor, execution is out of scope.

```
command_type  — "dispatch_aircraft" | "alert_ground_crew" | "escalate" | ...
cluster_id    — target area
payload       — command-specific parameters
priority      — 1 (critical) to 5 (advisory)
```

---

## Key Design Decisions

### 1. The classifier contract is immutable
`classify` always receives `state.sensor_events: List[SensorEvent]`. This never changes across sessions. What changes is how that list gets populated — single-tick events early, then a rolling window with historical context later. The LLM prompt iterates over the list regardless of source.

### 2. Persistence via LangGraph PostgreSQL store
All persistence runs through `langgraph-checkpoint-postgres`. This gives:
- **Checkpointing** — resumable graph runs, crash recovery
- **BaseStore** — keyed document store for event windows and historical findings

Every node that needs persistence already has `store: Optional[BaseStore]` in its signature. The store is wired in — but currently not used for cross-tick history.

The rolling event window is the key missing piece: `ingest_events` will load the previous window from the store and merge it with the current tick's events before `classify` runs. Without this, the cluster agent only sees single-tick data and cannot detect trends.

pgvector is available for semantic search over historical findings in later sessions.

### 3. One supervisor invocation per sim tick
The bridge drives world ticks and invokes the supervisor once per tick with all events from that tick. This is the production-analogous pattern (fixed time window → one pipeline invocation). A pre-filter in `ingest_events` (skip the LLM if all readings are nominal) is a future optimization.

### 4. Parallel cluster agents via LangGraph Send API
`fan_out_to_clusters` returns `List[Send]`, one per active cluster. LangGraph dispatches these in parallel (thread pool under `invoke`, async under `ainvoke`). The `aggregate_findings` reducer merges results after the synchronization barrier. This is already implemented.

### 5. Resource assessment is additive
The resource layer — evaluating whether available personnel, equipment, and air support are positioned to respond — bolts on after fire danger evaluation without changing the agent architecture. The supervisor's `decide_actions` node produces `ActuatorCommand` objects. Resource tools (querying `ResourceInventory`) are added to the supervisor's tool set in a later session. Nothing earlier changes.

### 6. The `classify` node — three cognitive responsibilities, one ReAct loop

Any classification task has three distinct cognitive steps:

1. **Evidence extraction** — turn raw sensor data into structured signals (max temp, min humidity, how many sensor types agree)
2. **Reasoning** — apply domain rules to the structured signals (do these readings meet the fire-weather threshold? is this corroboration or noise?)
3. **Decision** — commit to an anomaly type and confidence score

A naive implementation attempts all three in a single LLM call from raw event JSON. This is fragile: the LLM has to find the signal in noise, apply rules, and decide simultaneously with up to 50 raw readings in context.

The ReAct tool loop solves this without adding graph nodes. The `classify` node runs a loop:

```
classify:
  LLM sees: prompt + all messages so far (including tool results)
  LLM does: call get_sensor_summary() → structured features
  LLM does: call check_threshold() → which rules fire
  LLM does: (when satisfied) produce final JSON → ClassifyOutput
```

The three cognitive steps happen in the same node, driven by the LLM's own judgment about when it has enough evidence. This is strictly better than three hardcoded nodes because:

- The LLM decides how many tool calls it needs. Simple cases (one sensor far above threshold) need one call. Ambiguous cases (marginal readings across three types) may need three.
- No intermediate state format to design. Tool results are messages — the LLM sees them in context.
- Fewer graph nodes, fewer failure modes.

**The tools give the LLM structured access to data it already has.** `get_sensor_summary` doesn't fetch new data — it aggregates `state.sensor_events` into a tidy dict. `check_threshold` applies the domain rules programmatically. The LLM uses these to do evidence extraction cleanly, then reasons over the structured results.

Session 07 makes the first LLM call without tools — a single call from raw event JSON, deliberately limited. Session 08 adds the tool loop and shows why the tools matter.

---

## Domain Rules (current implementation)

These live in the classify prompt template and guide the LLM's confidence calibration:

| Condition | Threshold | Significance |
|-----------|-----------|-------------|
| Temperature | > 38°C | Elevated fire danger |
| Humidity | < 15% | Extreme dryness, fuels ignite easily |
| Wind speed | > 10 m/s | Rapid spread potential |
| Fuel moisture | < 8% | Strongest ignition predictor |
| All three (temp + humidity + wind) | combined | Critical fire weather |

**Confidence calibration:**
- 3+ sensor types corroborating → 0.8–1.0
- 2 sensor types corroborating → 0.5–0.8
- 1 sensor type elevated alone → 0.2–0.4 (likely sensor fault)

These rules are encoded in the prompt, not hardcoded. They can evolve without code changes.

---

## What Is Built vs. What Is Coming

| Component | Status | Session |
|-----------|--------|---------|
| World engine + fire physics | ✅ built | 01 |
| Sensors + SensorEvent | ✅ built | 01 |
| Cluster agent graph (stub) | ✅ built | 02 |
| Supervisor graph (stub) | ✅ built | 02 |
| Node tracer + structured logging | ✅ built | 03 |
| Prompt registry + Jinja templates | ✅ built | 04 |
| LLM registry (role → model mapping) | ✅ built | 05 |
| Routing helpers (`_route_base`) | ✅ built | 06 |
| LLM classify node | 🔜 session 07 | |
| ReAct tool loop + ToolNode | 🔜 session 08 | |
| Store wiring (cross-tick history) | 🔜 session 08 | |
| Bridge layer (tick driver) | 🔜 session 09 | |
| Supervisor LLM (assess + decide) | 🔜 session 10 | |
| Resource inventory + tools | 🔜 session 11 | |
| Full pipeline wired end-to-end | 🔜 session 12 | |
| pgvector semantic history search | 🔜 later | |

---

## Open Questions

These are known unknowns, deferred intentionally:

1. **Pre-filter threshold** — At what point does `ingest_events` skip the LLM entirely (all readings nominal)? Optimization for later.
2. **Cross-tick window size** — 50 events is the current cap. The right value depends on tick rate and sensor density; tune after the store is wired.
3. **Situation summary feedback** — Does the supervisor's situation summary feed back into the world engine (e.g., trigger resource deployment that changes fire spread)? Out of scope for the tutorial but architecturally possible.
