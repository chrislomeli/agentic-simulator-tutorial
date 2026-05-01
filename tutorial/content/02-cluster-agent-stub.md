# Session 2: The Cluster Agent (Stub Mode)

---

## What you're doing and why

This is the first session where you write agent code. You're building your first LangGraph graph.

The graph is called the **cluster agent**. Its job is simple: take in a batch of sensor readings from one geographic cluster and produce **findings** — structured conclusions about what the agent determined is happening in that part of the world. A finding might say: "fire risk is high near grid position (2,3), rate of spread would be fast given current wind conditions." Or in sensor fault terms: "temperature sensor temp-A1 appears to be stuck — reading hasn't changed in 10 ticks."

Findings are what flows upward to the supervisor in later sessions. The cluster agent doesn't know about resources, other clusters, or what to do about what it found. It only answers: *"what is happening in my cluster right now?"*

<!-- TODO: insert diagram — sensor events pulled from queue into cluster agent, agent returning AnomalyFinding objects -->

In this session the classification logic is a stub (hardcoded). Session 3 replaces it with an LLM. Starting in stub mode separates two learning curves:
- **This session:** LangGraph primitives — state schemas, nodes, edges, reducers
- **Session 3:** LLM integration — tool binding, ReAct loops, prompt engineering

When something breaks in stub mode you know exactly which layer failed. Once the graph structure works, swapping the stub for an LLM is just changing one function.

---
## Changes
git commit
```bash
 3 files changed, 423 insertions(+)
 create mode 100644 main.py
 create mode 100644 src/agents/cluster/cluster_graph.py
 create mode 100644 src/agents/cluster/state.py

```
validate
```bash
> python main.py 

=== Cluster agent demo ===
2026-04-30 17:44:05,635 [INFO] agents.cluster.cluster_graph: ClusterAgent subgraph compiled (stub mode)
2026-04-30 17:44:05,639 [INFO] agents.cluster.cluster_graph: ClusterAgent[cluster-north]:       NODE: ingest_events: ingesting event from source=temp-n1
2026-04-30 17:44:05,639 [INFO] agents.cluster.cluster_graph: ClusterAgent[cluster-north]:       NODE classify: STUB (no LLM)
2026-04-30 17:44:05,639 [INFO] agents.cluster.cluster_graph: ClusterAgent[cluster-north]        ROUTER: route_after_classify 
2026-04-30 17:44:05,639 [INFO] agents.cluster.cluster_graph: ClusterAgent[cluster-north]        NODE: report_findings:  reporting 1 finding(s) to supervisor
Status:   completed
Findings: 1
  - stub_placeholder (confidence=0.5)
    [STUB] classify node not yet implemented for cluster cluster-north
```

---

## Setup

If you're starting from a fresh clone:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
```

---

## Rubric coverage

This session covers the following skills from the [LangGraph Skills Rubric](../rubric.md):

| Skill | Level | Where in this session |
|-------|-------|-----------------------|
| StateGraph + Pydantic state | foundational | `ClusterAgentState` in `state.py` |
| Nodes — functions vs runnables | foundational | `ingest_events`, `classify`, `report_findings` in `cluster_graph.py` |
| Edges — normal vs conditional | foundational | `add_edge` and `add_conditional_edges` in `build_cluster_agent_graph` |
| Reducers and Annotated state | mid-level | `append_events` reducer, `add_messages` reducer in `state.py` |
| Compile + invoke | foundational | `builder.compile()` and `graph.invoke()` |
| Subgraphs — compile and invoke | mid-level | Cluster agent is compiled as a standalone subgraph, invoked by the supervisor in Session 5 |

---

## What you're building

Two files:

| File | What it contains |
|------|-----------------|
| `src/agents/cluster/state.py` | The state schema — the data structure that flows through the graph |
| `src/agents/cluster/cluster_graph.py` | The graph — nodes, edges, and the builder function |

When you're done, this test should pass:

```bash
pytest tests/agents/test_cluster.py -v
```

---

## Concept Box: LangGraph fundamentals

> **Read this before the code.** This is your first LangGraph session. These four concepts are all you need to understand to write the code below.

### 1. StateGraph — the container

A `StateGraph` is a directed graph where **state** flows from node to node. You create one with a state schema (a Pydantic `BaseModel` or TypedDict), add nodes and edges, then `compile()` it into a runnable graph.

```python
from langgraph.graph import StateGraph, START, END

builder = StateGraph(MyState)
builder.add_node("step_a", my_function_a)
builder.add_node("step_b", my_function_b)
builder.add_edge(START, "step_a")
builder.add_edge("step_a", "step_b")
builder.add_edge("step_b", END)
graph = builder.compile()

result = graph.invoke(MyState(field_1="value", field_2=[]))
```

### 2. Pydantic state — the data contract

The state schema defines **what fields exist** and **what types they have**. Every node receives the full state and returns a partial dict of only the fields it changed.

LangGraph examples typically use `TypedDict` for state. We use Pydantic `BaseModel` instead — it gives us field validation, defaults via `Field(default_factory=...)`, and clean serialization. Both work identically with `StateGraph`, reducers, and `Annotated` fields. The trade-off: nodes read state with **attribute access** (`state.cluster_id`) rather than dict access (`state.get("cluster_id")`).

```python
from pydantic import BaseModel, Field

class MyState(BaseModel):
    name: str
    items: List[str] = Field(default_factory=list)
    status: str = Field(default="idle")

# A node that only changes status:
def my_node(state: MyState) -> dict:
    return {"status": "done"}  # Only return what changed
```

### 3. Reducers — how fields merge

By default, returning `{"items": ["new"]}` **overwrites** the `items` field. If you want to **append** instead, you annotate the field with a reducer:

```python
from typing import Annotated
from operator import add

class MyState(BaseModel):
    items: Annotated[List[str], add] = Field(default_factory=list)  # add = list concatenation
```

Now `return {"items": ["new"]}` **appends** `"new"` to the existing list. LangGraph calls `add(existing_items, ["new"])` behind the scenes.

You can write custom reducers for more complex merge logic (deduplication, capped windows, etc.).

### 4. Edges — wiring nodes together

- **Normal edge:** `add_edge("a", "b")` — always go from a to b
- **Conditional edge:** `add_conditional_edges("a", router_fn)` — the router function reads state and returns the name of the next node
- `START` — the entry point of the graph
- `END` — the exit point of the graph

### What can go wrong

| Symptom | Cause | Fix |
|---------|-------|-----|
| Validation error at invoke time | Initial state is missing a required field | Pass all required fields when constructing the state |
| Node return value ignored | Returned a field not declared in the state model | Only return fields that are declared in the state schema |
| List field gets overwritten instead of appended | No reducer annotation | Add `Annotated[List[...], my_reducer]` to the field |
| Graph runs forever | Conditional edge never routes to END | Ensure every path eventually reaches END |

---

## File 1: `src/agents/cluster/state.py`

This file defines the data that flows through the cluster agent graph. Every node reads from it and writes partial updates back to it.

Create `src/agents/cluster/state.py`:

```python
"""
ogar.agents.cluster.state

State schema for the cluster agent LangGraph subgraph.

What is a cluster agent?
────────────────────────
One cluster agent runs per geographic/logical cluster of sensors.
Its job is to:
  1. Accumulate sensor events from its cluster (rolling window).
  2. Run a LangGraph tool loop to classify anomalies.
  3. Report findings (structured anomaly records) upward to the supervisor.

The cluster agent is a LangGraph subgraph — it has its own state schema
that is separate from the supervisor's state.  The supervisor maps
its own state in/out when it invokes the cluster agent subgraph.

State design principles
────────────────────────
  - Only fields that at least one node reads OR writes belong here.
  - Fields the LLM tool loop needs (messages) use LangGraph's add_messages
    reducer so new messages are appended rather than overwriting the list.
  - sensor_events uses a custom reducer (append-only) for the same reason:
    we want to accumulate events across invocations, not replace them.
  - Fields are Optional where they may not be set yet at graph start.

Node responsibilities (skeleton — logic comes later)
──────────────────────────────────────────────────────
  ingest_events    : Receives incoming SensorEvent, adds to sensor_events.
                     Sets status to "processing".
  classify         : LLM tool loop node.  Reads sensor_events and messages.
                     Uses tools to query history, cross-reference readings.
                     Writes anomalies when detected.
  report_findings  : Packages anomalies into Finding objects for the supervisor.
                     Sets status to "complete".
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Annotated
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from transport.schemas import SensorEvent




# ── Custom reducer for sensor event accumulation ──────────────────────────────

def append_events(
        existing: List[SensorEvent],
        new: List[SensorEvent],
) -> List[SensorEvent]:
    """
    Reducer that appends new sensor events to the existing list.

    LangGraph calls the reducer when a node returns a partial state update.
    Without a reducer, the default behaviour is to OVERWRITE the field.
    With this reducer, returning {"sensor_events": [new_event]} APPENDS
    to the existing list rather than replacing it.

    We also cap the window at MAX_EVENT_WINDOW to prevent unbounded growth.
    The oldest events are dropped first.
    """
    MAX_EVENT_WINDOW = 50  # Keep the last 50 events per cluster agent
    combined = existing + new
    return combined[-MAX_EVENT_WINDOW:]  # Trim from the front (oldest first)



# ── Finding model ─────────────────────────────────────────────────────────────

class AnomalyFinding(BaseModel):
    """
    A structured anomaly record produced by the cluster agent.

    The cluster agent writes these; the supervisor reads them.

    finding_id      : UUID string.
    cluster_id      : Which cluster detected this.
    anomaly_type    : e.g. "sensor_fault", "threshold_breach", "correlated_event"
    affected_sensors: List of source_ids involved.
    confidence      : Agent's confidence this is a real event (not noise).
    summary         : Human-readable description for the supervisor's context.
    raw_context     : Relevant sensor readings that led to this finding.
                      Passed to the supervisor for cross-cluster correlation.
    """
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_id: str
    anomaly_type: str
    affected_sensors: List[str] = Field(default_factory=list)
    confidence: float
    summary: str
    raw_context: Dict[str, Any]



# ── State values  ───────────────────────────────────────────────────────
class StatusValue(StrEnum):
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


# ── Cluster agent state ───────────────────────────────────────────────────────

class ClusterAgentState(BaseModel):
    """
    The internal working state for a single cluster agent execution.

    This state lives inside the LangGraph subgraph.
    It is NOT shared directly with the supervisor — the supervisor
    invokes the subgraph and receives only the output mapping.
    """

    # ── Identity ──────────────────────────────────────────────────────
    cluster_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # Which workflow execution this state belongs to.
    # Matches the workflow_id in WorkflowRunner.
    workflow_id: str

    # ── Incoming sensor data ──────────────────────────────────────────
    # Annotated with append_events reducer so new events accumulate.
    # ingest_events node writes here; classify node reads here.
    sensor_events: Annotated[List[SensorEvent], append_events] = Field(default_factory=list)

    # The single most-recent event that triggered this invocation.
    # Separate from sensor_events so classify can easily find the trigger.
    trigger_event: Optional[SensorEvent]

    # ── LLM tool loop ─────────────────────────────────────────────────
    # add_messages reducer appends new messages rather than overwriting.
    # classify node reads and writes here via the ToolNode loop.
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)

    # ── Findings output ───────────────────────────────────────────────
    # Populated by classify when anomalies are detected.
    # Read by report_findings to package for the supervisor.
    anomalies: List[AnomalyFinding] = Field(default_factory=list)

    # ── Control ───────────────────────────────────────────────────────
    # idle       : Waiting for a new trigger event
    # processing : Currently running the classify loop
    # complete   : Finished this invocation, findings are ready
    # error      : Something went wrong — details in error_message
    status: StatusValue = Field(default=StatusValue.IDLE)

    error_message: Optional[str]
```

**What to understand here:**

- `ClusterAgentState` is a Pydantic `BaseModel`. LangGraph uses it to validate node return values. Unlike TypedDict, Pydantic gives us field defaults (`Field(default_factory=list)`) and validation out of the box.
- `sensor_events` uses `Annotated[..., append_events]` — this tells LangGraph to call `append_events(existing, new)` when merging updates instead of overwriting. Same pattern for `messages` with LangChain's built-in `add_messages` reducer.
- `StatusValue` is a `StrEnum` — same string values as a `Literal[...]` would give you, but with named members (`StatusValue.PROCESSING`) you can reference from nodes and tests without typo risk.
- The `messages` field is declared now even though the stub doesn't use it. Session 3 swaps in the LLM, and keeping the schema stable means *only* the `classify` node has to change.
- Every node receives the full state and returns only the fields it changed. LangGraph merges the partial update into the current state.

---

## File 2: `src/agents/cluster/cluster_graph.py`

This file defines the graph — three nodes connected by edges, plus a builder function.

In stub mode the topology is a straight line: `START → ingest_events → classify → report_findings → END`. The `route_after_classify` conditional edge is wired in even though stub mode only routes one way — it's there so the error path works and so Session 3 can swap the `classify` node without rewiring the graph.

Create `src/agents/cluster/cluster_graph.py`:

```python
"""
ogar.agents.cluster.graph

Cluster agent LangGraph subgraph — stub mode.

Topology:
  START → ingest_events → classify → route_after_classify
        → report_findings → END

Usage:
  graph = build_cluster_agent_graph()

Why a subgraph?
───────────────
The cluster agent is compiled as a standalone subgraph.
The supervisor invokes it as a node (via Send API fan-out).
Each invocation gets its own state, which is why it can run in
parallel for multiple clusters without state collision.

Compiling separately also means it can be tested in isolation —
you can invoke the cluster agent directly with a SensorEvent
without needing the supervisor running.
"""

import logging
from typing import Literal, Optional
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from agents.cluster.state import AnomalyFinding, ClusterAgentState, StatusValue

logger = logging.getLogger(__name__)


# ── Node functions ────────────────────────────────────────────────────────────
# Each node receives the full ClusterAgentState state and returns a PARTIAL state update.
# LangGraph merges the partial update into the current state using reducers.
# Nodes should only return the fields they actually changed.

def ingest_events(state: ClusterAgentState) -> dict:
    """
    First node — acknowledges the trigger event and sets status to processing.
    It takes a ClusterAgentState in, and adds the status to the state - all of the actual processing will happen in the classify node (next)

    In a real implementation this node might also:
      - Validate the incoming event schema
      - Load recent history from the LangGraph Store
      - Decide whether the event is worth classifying (pre-filter)

    For now, we just log and set the status to "processing"
    """
    trigger = state.trigger_event
    logger.info(
        "ClusterAgent[%s] ingesting event from source=%s",
        state.cluster_id,
        trigger.source_id if trigger else "unknown",
    )

    # Return only the fields we're changing.
    # LangGraph merges this with the existing state.
    return {
        "status": StatusValue.PROCESSING,
        "error_message": None,   # Clear any previous error
    }


def classify(state: ClusterAgentState) -> dict:
    """
    Stub classify node — used when no LLM is provided.

    Produces a placeholder finding so the rest of the pipeline
    has something to work with end-to-end.
    """
    cluster_id = state.cluster_id
    trigger = state.trigger_event

    logger.info(
        "ClusterAgent[%s] classify — STUB (no LLM)",
        cluster_id,
    )

    stub_finding: AnomalyFinding = AnomalyFinding(
        finding_id= str(uuid4()),
        cluster_id= cluster_id,
        anomaly_type= "stub_placeholder",
        affected_sensors= [trigger.source_id] if trigger else [],
        confidence= 0.5,
        summary= f"[STUB] classify node not yet implemented for cluster {cluster_id}",
        raw_context={
            "trigger_event_id": trigger.event_id if trigger else None,
            "event_count_in_window": len(state.sensor_events),
        },
    )

    return {
        "anomalies": [stub_finding],
        "status": StatusValue.COMPLETED,
    }


def report_findings(state: ClusterAgentState, store: Optional[BaseStore] = None) -> dict:
    """
    Final node — logs findings and writes each AnomalyFinding to the
    LangGraph Store so the supervisor can recall past incidents.

    Store write (when store is provided):
      namespace : ("incidents", cluster_id)
      key       : finding_id  (UUID — stable across restarts)
      value     : the full AnomalyFinding dict

    store is injected by LangGraph at compile time via
    builder.compile(store=store) — any node whose signature includes
    `store: Optional[BaseStore]` receives it automatically.
    """
    anomalies = state.anomalies or []
    cluster_id = state.cluster_id

    logger.info(
        "ClusterAgent[%s] reporting %d finding(s) to supervisor",
        cluster_id,
        len(anomalies),
    )

    if store is not None and anomalies:
        for finding in anomalies:
            store.put(
                ("incidents", cluster_id),
                finding.finding_id,
                finding.model_dump(),
            )
        logger.info(
            "ClusterAgent[%s] wrote %d finding(s) to store",
            cluster_id,
            len(anomalies),
        )

    # No state change needed — anomalies are already in state
    return {}


# ── Routers ──────────────────────────────────────────────────────────────────

def route_after_classify(
    state: ClusterAgentState,
) -> Literal["report_findings", "__end__"]:
    """
    Router for stub mode — classify always goes to report_findings.
    """
    if state.status == StatusValue.ERROR:
        logger.warning(
            "ClusterAgent[%s] exiting due to error: %s",
            state.cluster_id,
            state.error_message,
        )
        return "__end__"

    return "report_findings"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_cluster_agent_graph(store: Optional[BaseStore] = None):
    """
    Compile and return the cluster agent subgraph (stub mode).

    Returns a compiled LangGraph graph ready for .invoke() or .stream().

    To test the cluster agent in isolation:
      graph = build_cluster_agent_graph()           # no store
      graph = build_cluster_agent_graph(store=s)    # with InMemoryStore
      result = graph.invoke({
          "cluster_id": "cluster-north",
          "workflow_id": "test-run-1",
          "trigger_event": some_sensor_event,
      })
    """

    builder = StateGraph(ClusterAgentState)
    builder.add_node("ingest_events", ingest_events)
    builder.add_node("classify", classify)
    builder.add_node("report_findings", report_findings)

    # ── Stub mode: deterministic classify ──────────────────────────
    builder.add_edge(START, "ingest_events")
    builder.add_edge("ingest_events", "classify")
    builder.add_conditional_edges("classify", route_after_classify)

    builder.add_edge("report_findings", END)

    # Passing store=store makes LangGraph inject it into any node whose
    # signature includes `store: Optional[BaseStore]`.
    # store=None is safe — nodes receive None and guard against it.
    logger.info("ClusterAgent subgraph compiled (stub mode)")
    compiled = builder.compile(store=store)
    return compiled


# Module-level compiled graph (stub mode).
# The graph is compiled once when the module is first imported.
cluster_agent_graph = build_cluster_agent_graph()
```

**What to understand here:**

- The three nodes correspond exactly to the three responsibilities in the `state.py` docstring: `ingest_events` (bookkeeping), `classify` (the brain — stubbed for now), `report_findings` (output + store write).
- Each node returns only the fields it changes. LangGraph merges those partial updates into the full state using the reducers from `state.py`.
- `route_after_classify` is a conditional edge. In stub mode it always routes to `report_findings` unless `status == ERROR`. The error branch is real — Session 3's LLM mode can fail mid-loop and uses the same exit path.
- `build_cluster_agent_graph(store=...)` accepts an optional `BaseStore`. The store is **not** in the state schema; LangGraph injects it into any node whose signature includes `store: Optional[BaseStore]` (only `report_findings` here).
- The module-level `cluster_agent_graph = build_cluster_agent_graph()` is compiled at import time. The supervisor and the tests both import this same compiled instance.

---

## Checkpoint

Run the test:

```bash
pytest tests/agents/test_cluster.py -v
```

You should see green for the reducer tests, the node tests, the router tests, and the graph integration tests. The `test_invoke_with_store_writes_findings` test is the end-to-end check: build the graph with an `InMemoryStore`, invoke it with a trigger event, then read `("incidents", "cluster-north")` back out and confirm the stub finding landed.

---

*Next: Session 3 replaces the stub `classify` node with an LLM-powered ReAct loop. The LLM calls tools to inspect sensor data, reasons about anomalies, and produces findings based on actual analysis. The graph topology adds a cycle — the ReAct loop — but the state schema and the other two nodes stay exactly the same.*

---

<!--
## TALKING POINTS — not yet written into prose

Things we need to communicate to the reader in this session. Rough notes, not wordsmithed.

### On state

- `ClusterAgentState` is a Pydantic `BaseModel`. LangGraph uses it to validate node outputs
  and to know what fields exist. We use Pydantic over TypedDict for field defaults, validation,
  and serialisation. Both work identically with StateGraph.
- The *reducer* concept is the key thing to nail. Without a reducer, every node return
  *replaces* the field. With `append_events`, returning `{"sensor_events": [new_event]}`
  *appends*. Same for `add_messages`. This is how state accumulates across nodes and
  across invocations.
- `status` is a `StrEnum` — the graph uses it as a lightweight FSM. Nodes write it,
  routers read it. In stub mode: IDLE → PROCESSING → COMPLETED. In LLM mode: add a
  possible loop through tool calls, plus an ERROR exit.
- The store is NOT in the state model. It's injected by LangGraph at compile time
  via `builder.compile(store=store)`. Any node with `store: Optional[BaseStore] = None`
  in its signature gets it automatically. If you see it in `report_findings` but not in
  `state.py`, that's why.

### On nodes

Three nodes, three responsibilities:
1. `ingest_events` — bookkeeping. Sets status, clears errors. Nothing interesting yet.
   In a real system: pre-filtering, history loading, schema validation.
2. `classify` (stub here, LLM in Session 3) — the brain. This is the only node
   that differs between modes. Stub returns a hardcoded placeholder.
3. `report_findings` — output packaging + store write. Takes `anomalies` from state
   and writes them to the LangGraph Store so the supervisor can recall past incidents.

### On graph topology

- In stub mode: linear. START → ingest → classify → report → END.
  The conditional edge still exists (`route_after_classify`) but only routes to one place.
  It's there so the error path works and so Session 3 can swap the node without changing
  the wiring.
- In LLM mode (Session 3): adds a cycle. classify → [tool_node → classify]*N → parse_findings.
  The cycle is the ReAct loop. LangGraph supports this — graphs are not required to be DAGs.

### On stub vs. LLM mode

- Why ship stub mode at all? Two reasons. First: separates the "did I wire the graph
  correctly" question from the "did I prompt the LLM correctly" question. Second:
  the stub stays available for tests and offline development (no API key needed).
- The stub produces a real `AnomalyFinding` (just with `anomaly_type: "stub_placeholder"`),
  so everything downstream — supervisor, store reads, evaluation — works without
  knowing the difference.

### On where node logic lives (for readers who ask)

- All node functions are in `cluster_graph.py`. In production you'd probably split into
  `nodes.py` and `cluster_graph.py` (topology only). For a tutorial, colocation is
  intentional — you can read the whole graph without jumping files.

### On what the cluster agent does NOT do

- It does NOT query resources. That's the supervisor's job (Sessions 6–7).
- It does NOT know about other clusters. Each cluster agent only sees its own events.
- It does NOT decide what to do. It only answers: "what is happening in my cluster?"
- The output (`AnomalyFinding`) is a *description*, not an action. The supervisor turns
  descriptions into commands.

### Diagram TODO

- Need a diagram showing: sensor events enter from the left → cluster agent box
  (showing the 3 nodes) → AnomalyFinding exits to the right.
- Secondary: show that N cluster agents run in parallel (stub for now — Session 5 shows
  the supervisor fan-out with Send API).
- Reference: `docs/tutorial/assets/diag-02-cluster-agent-topology.md`

### Open questions / things to resolve before writing full prose

- The docstring in `state.py` is really good — consider excerpting it directly into the
  tutorial rather than rewriting.
- Should we show the test as part of the session? `pytest tests/agents/test_cluster.py -v`
  is already in the checkpoint — but showing what the test *checks* might help readers
  understand what "done" looks like.
-->
