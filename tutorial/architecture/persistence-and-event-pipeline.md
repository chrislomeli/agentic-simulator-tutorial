---
name: Persistence and Event Pipeline Architecture
type: project
status: decided — not yet implemented
---

## Core decisions

### Persistence stack
- **LangGraph PostgreSQL store** (`langgraph-checkpoint-postgres`) for all persistence
- Provides both checkpointing (resumable graph runs) and BaseStore (keyed document store)
- Already wired: every node that needs persistence has `store: Optional[BaseStore]`
- **pgvector** for semantic search over historical findings in later sessions
- **No Redis** — Postgres covers the use case without added operational complexity

### The classifier contract (immutable)
`classify` always receives `state.sensor_events: List[SensorEvent]`. This never changes.
What changes over sessions is how that list gets populated — richer context,
same interface. The LLM prompt iterates over the list regardless of source.

### Event pipeline (bridge layer — not yet built)
```
World engine tick
  → sensors read cell states → List[SensorEvent] (one per sensor per tick)
  → bridge groups by cluster_id
  → supervisor invoked: SupervisorState(active_cluster_ids, events_by_cluster)
  → fan_out → one ClusterAgentState per cluster
  → ingest_events loads history from store + merges current tick events
  → classify sees full window
```

Trigger policy: one supervisor invocation per sim tick. Pre-filter (skip LLM
if all readings nominal) is a future session concern.

### Rolling event window
- Key: `("events", cluster_id)` in the store
- Written by: `report_findings` at end of each invocation
- Read by: `ingest_events` at start of next invocation
- Merged with current tick's events before `classify` runs
- Cap: 50 events (existing `append_events` reducer MAX_EVENT_WINDOW)

### What gets stored

| Data | Key | Written by | Read by |
|------|-----|-----------|--------|
| Rolling event window | `("events", cluster_id)` | `report_findings` | `ingest_events` |
| Historical findings | `("incidents", cluster_id)` | `report_findings` (already wired) | Supervisor LLM |
| Situation summaries | `("situations", workflow_id)` | `dispatch_commands` | Supervisor LLM |

### Why this matters for the LLM
Without cross-tick history, the agent can only detect single-tick anomalies.
The confidence calibration rules ("single spike = possible sensor fault,
3+ corroborating readings = high confidence") require trend data across ticks.
Persisting the event window is what makes those rules work in practice.

## Implementation sequence

| Session | What changes |
|---------|-------------|
| 7 | LLM classify — single-tick list, no store changes |
| 8 | `ingest_events` loads history from store; `report_findings` writes window back |
| 9+ | Supervisor LLM reads historical findings for cross-cluster correlation |
| Later | pgvector semantic search over past AnomalyFinding summaries |

## Open questions (deferred)
- Exact batching policy in the bridge (every tick? threshold-triggered?)
- What actuator commands do in the simulation (stub indefinitely for tutorial purposes)
- Whether situation summaries feed back into the world engine
