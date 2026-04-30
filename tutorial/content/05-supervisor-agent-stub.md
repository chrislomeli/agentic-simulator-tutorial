# Session 5: The Supervisor Agent (Stub Mode)

---

## What you're doing and why

Sessions 2–3 built the cluster agent — a graph that classifies sensor events for one geographic cluster. The cluster agent is a specialist: it only knows its own sensors. It has no idea what's happening in other clusters.

This session adds the supervisor: the agent that sees across all clusters. It coordinates cluster agents using the Send API (dynamic fan-out), merges their findings with a custom reducer, and produces action decisions.

As in Session 2, you build in stub mode first. The stub supervisor proves the multi-agent structure works before adding LLM reasoning in Session 6.

**Key concept:** the cluster agent is a *subgraph*. The supervisor invokes it as a black box inside a node — `cluster_agent_graph.invoke(state)` — the same as any Python function call. See `docs/tutorial/assets/diag-05-supervisor-to-subgraph.md` for a visual.

---

## Setup

This session builds on Sessions 1–4. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/world/ src/domains/ src/sensors/ src/transport/ src/bridge/ src/resources/ src/config.py tests/
git checkout tutorial/main -- src/agents/cluster/ src/tools/
pytest tests/agents/test_cluster.py -q   # should pass before you start
```

---

## Rubric coverage

| Skill | Level | Where in this session |
|-------|-------|-----------------------|
| Parallel node execution (Send API) | mid-level | `fan_out_to_clusters` returns `List[Send]` — one per cluster |
| Subgraphs — compile and invoke | mid-level | `cluster_agent_graph.invoke(state)` inside `run_cluster_agent` node |
| State schema handoff between graphs | mid-level | Supervisor constructs `ClusterAgentState` dict, maps `anomalies` → `cluster_findings` |
| Reducers and Annotated state | mid-level | `aggregate_findings_reducer` merges parallel results |
| Supervisor pattern | mid-level | The whole graph — fan-out, aggregate, assess, decide, dispatch |

---

## What you're building

| File | Change | What it contains |
|------|--------|-----------------|
| `src/agents/supervisor/state.py` | **Create** | `SupervisorState` TypedDict, `aggregate_findings_reducer` |
| `src/agents/supervisor/graph.py` | **Create** | `fan_out_to_clusters`, `run_cluster_agent`, stub nodes, `build_supervisor_graph` |

When you're done:

```bash
pytest tests/agents/test_supervisor.py -v
```

---

## Concept Box: The Send API

> **Read this before the code.** The Send API is the key new LangGraph primitive this session introduces. It enables dynamic parallel execution — something you can't do with regular edges.

### What Send does mechanically

A normal node returns a `dict` (partial state update). A Send-based function returns a `List[Send]` instead. Each `Send` object is an instruction: "run this node with this input."

```python
from langgraph.graph import Send

def fan_out(state) -> List[Send]:
    return [
        Send("target_node", {"key": "value_1"}),
        Send("target_node", {"key": "value_2"}),
        Send("target_node", {"key": "value_3"}),
    ]
```

LangGraph receives the list and:
1. **Invokes the target node once per Send**, in parallel
2. Each invocation gets its **own isolated copy** of the input dict — no state collision
3. When **all** invocations complete (sync barrier), their return values are **merged via reducers** into the parent state
4. Execution continues to the next node only after all Sends finish

### How it wires into the graph

Send functions are wired as **conditional edges**, not as regular nodes:

```python
builder.add_conditional_edges(START, fan_out_to_clusters)
```

LangGraph sees the `List[Send]` return type and treats it as dynamic fan-out instead of a routing decision.

### The sync barrier

This is the key thing to understand: after all Send targets complete, **the reducer merges their results**, then the **next normal edge** fires. You don't write any join/gather logic — LangGraph does it automatically.

```
fan_out → [Send A, Send B, Send C]
              ↓         ↓         ↓
          target_node  target_node  target_node   (parallel)
              ↓         ↓         ↓
           reducer merges all results              (automatic)
              ↓
          next_node                                 (sequential)
```

### What can go wrong

| Symptom | Cause | Fix |
|---------|-------|-----|
| `KeyError` in target node | Send input dict is missing required fields | Every field in the target's TypedDict must be present in the Send input — including optional fields (set them to `None` or `[]`) |
| Results overwrite instead of merge | No reducer on the output field | Use `Annotated[List[...], my_reducer]` on the field that collects parallel results |
| Only one Send runs | `active_cluster_ids` has one item | Not a bug — dynamic fan-out scales to N, including N=1 |
| Graph hangs | One Send target raises an exception | Add error handling inside the target node so it returns error status instead of raising |

---

## Why a supervisor matters

Sessions 06–08 gave you cluster agents. Each cluster agent sees sensor events from its own cluster and produces findings: "temperature spike in cluster-north", "smoke detected in cluster-south". But cluster agents don't talk to each other. They don't know what's happening in other clusters.

The supervisor solves this. It:
1. **Coordinates** — invokes all cluster agents in parallel when significant events occur
2. **Aggregates** — collects findings from all clusters into a single view
3. **Correlates** — looks for patterns across clusters (same anomaly in multiple places)
4. **Decides** — produces actuator commands based on the overall situation

This is the **supervisor pattern** in multi-agent systems. Cluster agents are specialists (local experts). The supervisor is the generalist (global coordinator). The supervisor doesn't replace cluster agents — it orchestrates them.

---

## SupervisorState: the outer state schema

The supervisor has its own state schema, separate from `ClusterAgentState`:

```python
class SupervisorState(TypedDict):
    active_cluster_ids: List[str]                                    # Which clusters to fan out to
    cluster_findings: Annotated[List[AnomalyFinding], aggregate_findings_reducer]  # Aggregated results
    messages: Annotated[List[BaseMessage], add_messages]             # LLM conversation (Session 10)
    pending_commands: List[ActuatorCommand]                          # Actions to dispatch
    situation_summary: Optional[str]                                 # Human-readable assessment
    status: Literal["idle", "aggregating", "assessing", "deciding", "dispatching", "complete", "error"]
    error_message: Optional[str]
```

**Key differences from ClusterAgentState:**
- No `sensor_events` — the supervisor doesn't see raw sensor data
- No `trigger_event` — the supervisor is triggered by cluster findings, not sensor events
- Has `active_cluster_ids` — the list of clusters to coordinate
- Has `cluster_findings` with a custom reducer — this is where parallel results merge
- Has `pending_commands` — the supervisor's output (cluster agents produce findings, supervisor produces commands)

**The custom reducer:**

```python
def aggregate_findings_reducer(
    existing: List[AnomalyFinding],
    incoming: List[AnomalyFinding],
) -> List[AnomalyFinding]:
    existing_ids = {f["finding_id"] for f in existing}
    new_findings = [f for f in incoming if f["finding_id"] not in existing_ids]
    return existing + new_findings
```

When cluster agents run in parallel via the Send API, each returns a list of findings. The reducer merges them into `cluster_findings`, deduplicating by `finding_id`. This is how parallel results accumulate into the supervisor's state.

---

## The Send API: dynamic fan-out

The Send API is LangGraph's pattern for dynamic parallel execution. Here's how it works:

**1. A function returns `List[Send]` instead of a state dict:**

```python
def fan_out_to_clusters(state: SupervisorState) -> List[Send]:
    cluster_ids = state.get("active_cluster_ids", [])
    sends = []
    for cluster_id in cluster_ids:
        cluster_state: ClusterAgentState = {
            "cluster_id": cluster_id,
            "workflow_id": f"{cluster_id}::supervisor-fanout",
            "sensor_events": [],
            "trigger_event": None,
            "messages": [],
            "anomalies": [],
            "status": "idle",
            "error_message": None,
        }
        sends.append(Send("run_cluster_agent", cluster_state))
    return sends
```

Each `Send("run_cluster_agent", cluster_state)` is an instruction: "invoke the `run_cluster_agent` node with this state as input".

**2. LangGraph runs all Send targets in parallel:**

If `active_cluster_ids = ["cluster-north", "cluster-south"]`, the function returns 2 Send objects. LangGraph invokes `run_cluster_agent` twice in parallel, once with `cluster_id="cluster-north"` and once with `cluster_id="cluster-south"`.

**3. Results merge via the reducer:**

Each `run_cluster_agent` invocation returns `{"cluster_findings": [finding1, finding2, ...]}`. The `aggregate_findings_reducer` merges all the lists into the supervisor's `cluster_findings` field.

**Why this matters:** The number of cluster agents is determined at runtime from `active_cluster_ids`. If you have 1 cluster, 1 agent runs. If you have 10 clusters, 10 agents run in parallel. No code changes. This is dynamic fan-out.

---

## State schema handoff: SupervisorState → ClusterAgentState

The supervisor and cluster agents have different state schemas. The supervisor constructs a `ClusterAgentState` dict for each Send:

```python
cluster_state: ClusterAgentState = {
    "cluster_id": cluster_id,                    # From supervisor's active_cluster_ids
    "workflow_id": f"{cluster_id}::supervisor-fanout",
    "sensor_events": [],                         # Empty — supervisor doesn't have sensor data
    "trigger_event": None,                       # No specific trigger
    "messages": [],                              # Fresh conversation
    "anomalies": [],                             # Will be populated by cluster agent
    "status": "idle",
    "error_message": None,
}
```

This is **state mapping** — translating between two different state schemas. The supervisor knows what the cluster agent needs (a `ClusterAgentState` dict) and constructs it from its own state.

When the cluster agent finishes, it returns a state dict with `anomalies` populated. The `run_cluster_agent` wrapper extracts `anomalies` and maps it to the supervisor's `cluster_findings`:

```python
def run_cluster_agent(state: ClusterAgentState) -> dict:
    result_state = cluster_agent_graph.invoke(state)
    return {
        "cluster_findings": result_state.get("anomalies", []),
    }
```

The supervisor never sees the cluster agent's `messages` or `sensor_events`. It only gets the findings.

---

## The graph topology (stub mode)

Here's the supervisor graph structure in stub mode:

```
START → fan_out_to_clusters (conditional edge)
            ↓
        run_cluster_agent (×N, parallel)
            ↓
        assess_situation (stub)
            ↓
        decide_actions (stub)
            ↓
        route_after_decide (conditional edge)
            ↓
        dispatch_commands → END
```

**Edges:**
- `START → fan_out_to_clusters` — **conditional edge**, returns `List[Send]`
- `fan_out_to_clusters → run_cluster_agent` — LangGraph interprets the Send objects as parallel invocations
- `run_cluster_agent → assess_situation` — normal edge, runs after all parallel invocations complete
- `assess_situation → decide_actions` — normal edge
- `decide_actions → route_after_decide` — conditional edge, checks for errors
- `route_after_decide → dispatch_commands` — router returns `"dispatch_commands"`
- `dispatch_commands → END` — normal edge

**Key insight:** `fan_out_to_clusters` is wired as a conditional edge from START, not a regular node. It's a routing function that returns Send objects instead of a state dict. This is how you tell LangGraph "run these nodes in parallel".

---

## The stub nodes

### 1. `assess_situation` — stub summary

```python
def assess_situation(state: SupervisorState, store: Optional[BaseStore] = None) -> dict:
    findings = state.get("cluster_findings", [])
    cluster_ids = state.get("active_cluster_ids", [])
    
    past_count = 0
    if store is not None:
        for cid in cluster_ids:
            items = store.search(("incidents", cid))
            past_count += len(items)
    
    summary = (
        f"[STUB] Received {len(findings)} finding(s) from "
        f"{len(cluster_ids)} cluster(s). "
        f"Store contains {past_count} past incident(s) across all clusters."
    )
    
    return {
        "situation_summary": summary,
        "status": "deciding",
        "messages": [AIMessage(content=summary)],
    }
```

This stub:
- Counts findings and clusters
- Reads past incidents from the LangGraph Store (if provided) to include historical context
- Produces a hardcoded summary string
- Sets `status="deciding"` to move to the next phase

Session 10 will replace this with an LLM that actually reasons about the findings.

### 2. `decide_actions` — stub (no commands)

```python
def decide_actions(state: SupervisorState) -> dict:
    return {
        "pending_commands": [],
        "status": "dispatching",
    }
```

The stub produces no commands. Session 10 will replace this with an LLM that decides what actuator commands to issue based on the situation summary.

### 3. `dispatch_commands` — write to Store

```python
def dispatch_commands(state: SupervisorState, store: Optional[BaseStore] = None) -> dict:
    commands = state.get("pending_commands", [])
    summary = state.get("situation_summary", "")
    
    if store is not None and summary:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        store.put(
            ("situations", "global"),
            ts,
            {
                "situation_summary": summary,
                "command_count": len(commands),
                "command_types": [c.command_type for c in commands],
            },
        )
    
    return {"status": "complete"}
```

This node:
- Logs the command count
- Writes the situation summary to the Store under namespace `("situations", "global")` with a timestamp key
- Sets `status="complete"`

The Store write gives the supervisor memory across invocations. Future runs can read past situations to avoid duplicate alerts or to reason about escalation patterns.

---

## Running it

Here's a complete script that invokes the supervisor in stub mode:

```python
from agents.supervisor.graph import build_supervisor_graph

# Build the graph (stub mode, no LLM)
graph = build_supervisor_graph()

# Invoke with 2 active clusters
result = graph.invoke({
    "active_cluster_ids": ["cluster-north", "cluster-south"],
    "cluster_findings": [],
    "messages": [],
    "pending_commands": [],
    "situation_summary": None,
    "status": "idle",
    "error_message": None,
})

# Inspect the result
print(f"Status: {result['status']}")
print(f"Findings aggregated: {len(result['cluster_findings'])}")
print(f"Summary: {result['situation_summary']}")
print(f"Commands: {len(result['pending_commands'])}")

# Inspect individual findings
for i, f in enumerate(result["cluster_findings"], 1):
    print(f"\n{i}. [{f['anomaly_type']}] cluster={f['cluster_id']} conf={f['confidence']:.2f}")
    print(f"   Summary: {f['summary'][:80]}")
```

**Expected output (stub mode):**

```
Status: complete
Findings aggregated: 2
Summary: [STUB] Received 2 finding(s) from 2 cluster(s). Store contains 0 past incident(s) across all clusters.
Commands: 0

1. [stub_placeholder] cluster=cluster-north conf=0.50
   Summary: [STUB] classify node not yet implemented for cluster cluster-north

2. [stub_placeholder] cluster=cluster-south conf=0.50
   Summary: [STUB] classify node not yet implemented for cluster cluster-south
```

The supervisor:
1. Fanned out to 2 clusters in parallel
2. Each cluster agent ran and produced 1 stub finding
3. The reducer merged both findings into `cluster_findings`
4. `assess_situation` produced a summary counting the findings
5. `decide_actions` produced no commands (stub)
6. Status reached `"complete"`

---

## What you learned: Multi-agent coordination

This session introduced the multi-agent patterns:

**1. Send API** — a function returns `List[Send]` to trigger parallel node invocations. Each Send specifies a target node and an input state.

**2. Dynamic fan-out** — the number of parallel invocations is determined at runtime from state. Add a cluster to `active_cluster_ids`, and the supervisor automatically invokes its agent.

**3. Custom reducer** — `aggregate_findings_reducer` merges results from parallel Send targets, deduplicating by `finding_id`.

**4. State schema handoff** — the supervisor constructs `ClusterAgentState` dicts for each cluster agent, mapping between two different state schemas.

**5. Subgraph invocation** — `cluster_agent_graph.invoke(state)` runs the cluster agent as a synchronous call. The cluster agent's internal state is completely isolated from the supervisor's state.

**6. Store integration** — the supervisor reads past incidents from `("incidents", cluster_id)` and writes situation summaries to `("situations", "global")` for cross-invocation memory.

The supervisor doesn't replace cluster agents. It coordinates them. Cluster agents are still responsible for classifying sensor events. The supervisor is responsible for seeing the big picture and deciding what to do about it.

---

## Checkpoint

```bash
pytest tests/agents/test_supervisor.py -v
```

Key tests to look for:
- `test_fan_out_to_clusters` — Send API produces the right number of parallel invocations
- `test_aggregate_findings_reducer` — deduplication works correctly
- `test_invoke_stub_mode` — full graph runs to completion with stub nodes
- `test_invoke_with_store_writes_situation` — dispatch_commands writes to the Store

---

## Key files

- `src/agents/supervisor/state.py` — `SupervisorState` TypedDict, `aggregate_findings_reducer`
- `src/agents/supervisor/graph.py` — `build_supervisor_graph()`, `fan_out_to_clusters`, `run_cluster_agent`, stub nodes
- `src/actuators/base.py` — `ActuatorCommand` (the supervisor's output format)

---

*Next: Session 6 replaces the stub assess and decide nodes with LLM-powered ReAct loops. The supervisor will use tools to examine findings, correlate across clusters, and produce reasoned actuator commands. The graph topology changes to add two separate tool loops (assess and decide), but the Send API fan-out and the reducer stay exactly the same.*
