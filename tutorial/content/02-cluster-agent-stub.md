# Session 2: The Full Graph Skeleton

---

## What you're building and why

In this session you build the **complete application skeleton** — both graphs, all state schemas, and the entry point — as stub implementations that compile, run, and produce dummy output.

No LLM. No real analysis. Just structure.

By the end you will have a working end-to-end pipeline:

```
python main.py
```
```
=== Supervisor demo (full graph) ===
Status:   completed
Summary:  [STUB] Received 1 finding(s) from 2 cluster(s).
Findings: 1
  - [cluster-north] stub_placeholder (confidence=0.5)
    [STUB] classify node not yet implemented for cluster cluster-north
Commands: 0
```

The reason to do this before writing any real logic: **you need to understand the shape of the whole thing before you can reason about any one part of it.** The supervisor's fan-out pattern, the state boundary between the two graphs, the synchronization barrier — these are structural decisions that affect every session that follows. Getting them wrong early is expensive. Understanding them now is not.

---

## The full picture

Here is the complete data flow. Read this carefully — the rest of the session explains each piece.

```
main.py
  │
  └─▶  supervisor_graph.invoke(SupervisorState)
         │
         │  fan_out_to_clusters()          ← conditional edge off START
         │  returns List[Send]             ← one Send per active cluster
         │
         ├─▶  run_cluster_agent(ClusterAgentState)   ← parallel
         │      └─▶  cluster_agent_graph.invoke()    ← Python call
         │             ├─▶ ingest_events
         │             ├─▶ classify          (stub)
         │             └─▶ report_findings
         │             returns anomalies ──────────────────────┐
         │                                                     │
         ├─▶  run_cluster_agent(ClusterAgentState)   ← parallel│
         │      └─▶  cluster_agent_graph.invoke()             │
         │             ...                                     │
         │             returns anomalies ──────────────────────┤
         │                                                     │
         │  [synchronization barrier]                          │
         │  aggregate_findings reducer merges all ◀────────────┘
         │
         ├─▶  assess_situation     (stub)
         ├─▶  decide_actions       (stub)
         └─▶  dispatch_commands    (stub)
                │
                └─▶  END
```

Two things to notice immediately:

1. **There are two separate LangGraph graphs.** The cluster agent is compiled independently. The supervisor calls it from a regular Python node — not via LangGraph's subgraph nesting mechanism.

2. **The cluster agents run in parallel.** The supervisor fans out to N clusters simultaneously and waits for all of them before continuing. This is the `Send` API.

---

## Why two separate graphs, and why called from Python?

LangGraph supports true subgraph nesting: you can `add_node("cluster", cluster_subgraph)` and LangGraph manages the invocation. We deliberately do not use that here.

The reason: **the Send API fan-out requires each parallel invocation to carry its own state payload.** When `fan_out_to_clusters` returns `List[Send]`, each `Send` object carries a complete `ClusterAgentState` built from the supervisor's `events_by_cluster` dict. LangGraph runs all of those in parallel, each with isolated state.

If the cluster agent were a native subgraph node, its state would be whatever field of `SupervisorState` you mapped to it — shared across all parallel runs. With the Python invocation pattern, each `run_cluster_agent` call gets its own `ClusterAgentState` from the `Send`, invokes the compiled cluster graph with it, and returns only the findings it cares about back to the supervisor.

The state types are different at the boundary by design:
- `fan_out_to_clusters` reads `SupervisorState`, builds `ClusterAgentState` per cluster
- `run_cluster_agent` receives `ClusterAgentState` (from `Send`), returns `{"cluster_findings": anomalies}` into `SupervisorState`

That explicit boundary is what lets the cluster agent be tested in complete isolation — no supervisor needed.

---

## Files you'll create

| File | Purpose |
|------|---------|
| `src/agents/cluster/state.py` | `ClusterAgentState` — data flowing through the cluster graph |
| `src/agents/cluster/nodes.py` | Cluster node functions: `ingest_events`, `classify`, `report_findings` |
| `src/agents/cluster/graph.py` | Cluster graph builder + module-level compiled instance |
| `src/agents/supervisor/state.py` | `SupervisorState` — data flowing through the supervisor graph |
| `src/agents/supervisor/nodes.py` | Supervisor node functions: `fan_out_to_clusters`, `run_cluster_agent`, `assess_situation`, `decide_actions`, `dispatch_commands` |
| `src/agents/supervisor/graph.py` | Supervisor graph builder + module-level compiled instance |
| `main.py` | Entry point — builds and invokes the supervisor graph |

You also need empty `__init__.py` files in `src/agents/`, `src/agents/cluster/`, and `src/agents/supervisor/` to make them importable.

---

## Get the code

Copy the skeleton from the tutorial repo:

```bash
git fetch tutorial
git checkout tutorial/tutorial-02 -- src/agents/ main.py
```

Then run it to confirm the baseline works:

```bash
python main.py
```

You should see the output shown at the top of this session. If you see `ImportError`, make sure your virtual environment is active and the project is installed:

```bash
source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
```

---

## Concept boxes

> Read these before the walkthrough. They are short.

### StateGraph and Pydantic state

A `StateGraph` is a directed graph where a state object flows from node to node. You define the state schema, add nodes and edges, then `compile()` it into a runnable.

We use Pydantic `BaseModel` for state rather than `TypedDict`. Both work identically with LangGraph. The trade-off: Pydantic gives field validation, defaults, and serialization out of the box. Nodes read fields as attributes (`state.cluster_id`) rather than dict keys.

```python
builder = StateGraph(MyState)
builder.add_node("step_a", fn_a)
builder.add_node("step_b", fn_b)
builder.add_edge(START, "step_a")
builder.add_edge("step_a", "step_b")
builder.add_edge("step_b", END)
graph = builder.compile()
result = graph.invoke(MyState(cluster_id="x", workflow_id="y"))
```

Every node receives the full current state and returns a **partial dict** of only the fields it changed. LangGraph merges the partial update back into the state.

### Reducers

By default, returning `{"items": ["new"]}` **overwrites** the `items` field. If you want to **append** instead, annotate the field with a reducer function:

```python
from typing import Annotated
from operator import add

class MyState(BaseModel):
    items: Annotated[List[str], add] = Field(default_factory=list)
```

Now returning `{"items": ["new"]}` calls `add(existing, ["new"])` and appends. LangGraph handles the merge.

This project uses two custom reducers:
- `append_events` on `ClusterAgentState.sensor_events` — accumulates events in a capped rolling window
- `aggregate_findings` on `SupervisorState.cluster_findings` — merges findings from parallel cluster agents, deduplicating by `finding_id`

### Edges and conditional edges

- `add_edge("a", "b")` — always go from a to b
- `add_conditional_edges("a", router_fn)` — call `router_fn(state)`, go to the node it returns
- `add_conditional_edges(START, fan_out_fn, ["target"])` — **special form**: `fan_out_fn` returns `List[Send]` instead of a node name. LangGraph runs all Send targets in parallel.

The last form is how `fan_out_to_clusters` works. It is **not** a regular node — it is a conditional edge function attached to START. This distinction matters: it has no entry in `add_node`, and it receives `SupervisorState` but returns routing instructions, not a state update.

### The Send API

`Send("node_name", state_payload)` tells LangGraph: run `node_name` with `state_payload` as its input state. Return a list of these from a conditional edge and LangGraph runs all of them in parallel, then merges their state updates via reducers before continuing.

```python
from langgraph.types import Send

def fan_out_to_clusters(state: SupervisorState) -> List[Send]:
    return [
        Send("run_cluster_agent", ClusterAgentState(cluster_id=cid, ...))
        for cid in state.active_cluster_ids
    ]
```

After all `run_cluster_agent` invocations finish, LangGraph applies all their returned `{"cluster_findings": [...]}` updates via `aggregate_findings` and advances to `assess_situation`. That automatic wait-for-all is the **synchronization barrier**.

---

## Walkthrough: the cluster agent

### `src/agents/cluster/state.py`

`ClusterAgentState` is the data contract for one cluster agent execution. The key fields:

| Field | Type | Reducer | Purpose |
|-------|------|---------|---------|
| `cluster_id` | `str` | — | Which cluster this agent is working on |
| `workflow_id` | `str` | — | Links back to the supervisor run |
| `trigger_event` | `Optional[SensorEvent]` | — | The event that caused this invocation |
| `sensor_events` | `List[SensorEvent]` | `append_events` | Rolling window of recent events |
| `messages` | `List[BaseMessage]` | `add_messages` | LLM conversation (unused in stub mode, wired now for Session 3) |
| `anomalies` | `List[AnomalyFinding]` | — | Findings produced by classify |
| `status` | `StatusValue` | — | `idle → processing → completed` (or `error`) |

`AnomalyFinding` is also defined here — it is the output type the supervisor cares about. Defining it in the cluster state module means the supervisor can import it without a circular dependency.

`StatusValue` is a `StrEnum`. Nodes write it (`StatusValue.PROCESSING`), routers read it. In stub mode the lifecycle is linear: `idle → processing → completed`. Later sessions add an `error` exit path and an LLM tool loop that cycles through `processing` multiple times.

### `src/agents/cluster/nodes.py`

Three nodes, three responsibilities:

**`ingest_events`** — bookkeeping. Logs the incoming trigger event, sets status to `PROCESSING`. In a real implementation this is where you'd pre-filter events or load history from the store. For now it just marks the state as in-flight.

**`classify`** — the brain. In stub mode it produces a hardcoded `AnomalyFinding` with `anomaly_type="stub_placeholder"`. Session 3 replaces this node with an LLM ReAct loop. Nothing else in the graph changes.

**`make_report_findings(store=None)`** — returns a closure. The outer function captures the `store` at graph-build time; the inner function is the actual node. This pattern lets us inject a `BaseStore` without putting it in the state schema. When `store` is provided, the node writes each finding to `("incidents", cluster_id)` in the store so the supervisor can recall past incidents.

### `src/agents/cluster/graph.py`

The graph topology:

```
START → ingest_events → classify → route_after_classify
                                        │
                              ┌─────────┴──────────┐
                         report_findings          END
                              │                (on error)
                             END
```

`route_after_classify` is a conditional edge. In stub mode it always routes to `report_findings` unless `status == ERROR`. The error branch is real — it's there for Session 3's LLM mode which can fail mid-loop.

The module-level `cluster_agent_graph = build_cluster_agent_graph()` compiles once at import time. The supervisor's `run_cluster_agent` node imports and invokes this instance.

---

## Walkthrough: the supervisor

### `src/agents/supervisor/state.py`

`SupervisorState` owns one complete analysis cycle:

| Field | Type | Reducer | Purpose |
|-------|------|---------|---------|
| `active_cluster_ids` | `List[str]` | — | Which clusters to fan out to |
| `events_by_cluster` | `Dict[str, List[...]]` | — | Input events, keyed by cluster |
| `cluster_findings` | `List[AnomalyFinding]` | `aggregate_findings` | Merged findings from all cluster agents |
| `situation_summary` | `Optional[str]` | — | Written by `assess_situation` |
| `pending_commands` | `List[ActuatorCommand]` | — | Written by `decide_actions` |
| `status` | `StatusValue` | — | Shared with cluster agent — same enum |

`aggregate_findings` is the critical reducer here. Multiple `run_cluster_agent` nodes run in parallel and each returns `{"cluster_findings": [finding, ...]}`. Without a reducer, each return would overwrite the field. With `aggregate_findings`, LangGraph calls it once per parallel return, accumulating all findings into one deduplicated list.

### `src/agents/supervisor/nodes.py`

**`fan_out_to_clusters(state: SupervisorState) -> List[Send]`** — not a node. A conditional-edge function attached to START. Reads `active_cluster_ids` and `events_by_cluster` from supervisor state, builds one `ClusterAgentState` per cluster, wraps each in `Send("run_cluster_agent", ...)`. Returns the list to LangGraph, which dispatches them in parallel.

**`run_cluster_agent(state: ClusterAgentState) -> dict`** — receives a `ClusterAgentState` (from the `Send`), calls `cluster_agent_graph.invoke(state)`, extracts `anomalies` from the result, returns `{"cluster_findings": anomalies}`. That return updates `SupervisorState.cluster_findings` via the `aggregate_findings` reducer.

Note the state type: this node receives `ClusterAgentState`, not `SupervisorState`. The `Send` delivers exactly what `fan_out_to_clusters` put in it.

**`assess_situation`**, **`decide_actions`**, **`dispatch_commands`** — all stubs. They log and return placeholder values. `dispatch_commands` uses the same closure/factory pattern as `report_findings` — it captures a `store` parameter for future use.

### `src/agents/supervisor/graph.py`

The graph topology:

```
START
  │
  └─▶ fan_out_to_clusters()   ← conditional edge, returns List[Send]
        │
        ├─▶ run_cluster_agent  ← parallel (one per Send)
        ├─▶ run_cluster_agent
        └─▶ run_cluster_agent
        [synchronization barrier — aggregate_findings reducer runs]
        │
        ├─▶ assess_situation
        ├─▶ decide_actions
        └─▶ dispatch_commands → END
```

The `add_conditional_edges(START, fan_out_to_clusters, ["run_cluster_agent"])` call tells LangGraph that `fan_out_to_clusters` can only route to `"run_cluster_agent"`. This is required when the function returns `List[Send]` so LangGraph knows which nodes to expect.

---

## Run it

```bash
python main.py
```

Expected output:

```
=== Supervisor demo (full graph) ===
2026-05-01 ... [INFO] agents.supervisor.nodes: Supervisor fanning out to 2 cluster(s): ['cluster-north', 'cluster-south']
2026-05-01 ... [INFO] agents.supervisor.nodes: Supervisor invoking cluster agent for cluster=cluster-north
2026-05-01 ... [INFO] agents.cluster.nodes: ClusterAgent[cluster-north] ingest_events: ingesting event from source=temp-n1
2026-05-01 ... [INFO] agents.cluster.nodes: ClusterAgent[cluster-north] classify: STUB (no LLM)
2026-05-01 ... [INFO] agents.cluster.nodes: ClusterAgent[cluster-north] report_findings: reporting 1 finding(s)
2026-05-01 ... [INFO] agents.supervisor.nodes: Supervisor invoking cluster agent for cluster=cluster-south
2026-05-01 ... [INFO] agents.cluster.nodes: ClusterAgent[cluster-south] ingest_events: ingesting event from source=unknown
2026-05-01 ... [INFO] agents.cluster.nodes: ClusterAgent[cluster-south] classify: STUB (no LLM)
2026-05-01 ... [INFO] agents.cluster.nodes: ClusterAgent[cluster-south] report_findings: reporting 1 finding(s)
2026-05-01 ... [INFO] agents.supervisor.nodes: Supervisor dispatching 0 command(s)
Status:   completed
Summary:  [STUB] Received 2 finding(s) from 2 cluster(s).
Findings: 2
  - [cluster-north] stub_placeholder (confidence=0.5)
    [STUB] classify node not yet implemented for cluster cluster-north
  - [cluster-south] stub_placeholder (confidence=0.5)
    [STUB] classify node not yet implemented for cluster cluster-south
Commands: 0
```

Two things to look for:

1. **Both cluster agents ran** — one for `cluster-north` (with a real event) and one for `cluster-south` (with no event, so trigger is `None`). The stub handles both without crashing.
2. **The findings were merged** — `aggregate_findings` combined two separate `{"cluster_findings": [...]}` returns into one list of 2.

You can also inspect the graph diagrams written to disk:
- `cluster_graph.png` — the cluster agent topology
- `supervisor_graph.png` — the supervisor topology

---

## What's next

Session 3 adds structured logging via `node_tracer` — a decorator that wraps each node to emit timing and structured log records. The graph topology and state schemas do not change. You are adding observability around existing structure.

Session 4 adds prompt management — a registry that loads and renders Jinja2 prompt templates. Still no LLM calls.

Session 5 replaces the stub `classify` node with a real LLM ReAct loop. At that point the graph topology of the cluster agent changes (it gains a cycle), but the supervisor graph and the state boundary between them stay exactly as you built them here.
