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
| StateGraph + TypedDict state | foundational | `ClusterAgentState` in `state.py` |
| Nodes — functions vs runnables | foundational | `ingest_events`, `classify`, `report_findings` in `graph.py` |
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
| `src/agents/cluster/graph.py` | The graph — nodes, edges, and the builder function |

When you're done, this test should pass:

```bash
pytest tests/agents/test_cluster.py -v
```

---

## Concept Box: LangGraph fundamentals

> **Read this before the code.** This is your first LangGraph session. These four concepts are all you need to understand to write the code below.

### 1. StateGraph — the container

A `StateGraph` is a directed graph where **state** (a dict) flows from node to node. You create one with a state schema (a TypedDict), add nodes and edges, then `compile()` it into a runnable graph.

```python
from langgraph.graph import StateGraph, START, END

builder = StateGraph(MyState)
builder.add_node("step_a", my_function_a)
builder.add_node("step_b", my_function_b)
builder.add_edge(START, "step_a")
builder.add_edge("step_a", "step_b")
builder.add_edge("step_b", END)
graph = builder.compile()

result = graph.invoke({"field_1": "value", "field_2": []})
```

### 2. TypedDict state — the data contract

The state schema is a Python `TypedDict`. It defines **what fields exist** and **what types they have**. Every node receives the full state and returns a partial dict of only the fields it changed.

```python
class MyState(TypedDict):
    name: str
    items: List[str]
    status: str

# A node that only changes status:
def my_node(state: MyState) -> dict:
    return {"status": "done"}  # Only return what changed
```

### 3. Reducers — how fields merge

By default, returning `{"items": ["new"]}` **overwrites** the `items` field. If you want to **append** instead, you annotate the field with a reducer:

```python
from typing import Annotated
from operator import add

class MyState(TypedDict):
    items: Annotated[List[str], add]  # add = list concatenation
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
| `KeyError: 'field_name'` at invoke time | Initial state dict is missing a required field | Pass all fields in the `graph.invoke({...})` call |
| Node return value ignored | Returned a field not in the TypedDict | Only return fields that are declared in the state schema |
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

from typing import Annotated, Any, Dict, List, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

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
    MAX_EVENT_WINDOW = 50   # Keep the last 50 events per cluster agent
    combined = existing + new
    return combined[-MAX_EVENT_WINDOW:]  # Trim from the front (oldest first)


# ── Finding model ─────────────────────────────────────────────────────────────

class AnomalyFinding(TypedDict):
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
    finding_id: str
    cluster_id: str
    anomaly_type: str
    affected_sensors: List[str]
    confidence: float
    summary: str
    raw_context: Dict[str, Any]


# ── Cluster agent state ───────────────────────────────────────────────────────

class ClusterAgentState(TypedDict):
    """
    The internal working state for a single cluster agent execution.

    This state lives inside the LangGraph subgraph.
    It is NOT shared directly with the supervisor — the supervisor
    invokes the subgraph and receives only the output mapping.
    """

    # ── Identity ──────────────────────────────────────────────────────
    cluster_id: str
    # Which workflow execution this state belongs to.
    # Matches the workflow_id in WorkflowRunner.
    workflow_id: str

    # ── Incoming sensor data ──────────────────────────────────────────
    # Annotated with append_events reducer so new events accumulate.
    # ingest_events node writes here; classify node reads here.
    sensor_events: Annotated[List[SensorEvent], append_events]

    # The single most-recent event that triggered this invocation.
    # Separate from sensor_events so classify can easily find the trigger.
    trigger_event: Optional[SensorEvent]

    # ── LLM tool loop ─────────────────────────────────────────────────
    # add_messages reducer appends new messages rather than overwriting.
    # classify node reads and writes here via the ToolNode loop.
    messages: Annotated[List[BaseMessage], add_messages]

    # ── Findings output ───────────────────────────────────────────────
    # Populated by classify when anomalies are detected.
    # Read by report_findings to package for the supervisor.
    anomalies: List[AnomalyFinding]

    # ── Control ───────────────────────────────────────────────────────
    # idle       : Waiting for a new trigger event
    # processing : Currently running the classify loop
    # complete   : Finished this invocation, findings are ready
    # error      : Something went wrong — details in error_message
    status: Literal["idle", "processing", "complete", "error"]

    error_message: Optional[str]

```

**What to understand here:**

- `ClusterAgentState` is a TypedDict — a plain dict with type hints. LangGraph uses it to validate node return values.
- `sensor_events` uses `Annotated[..., append_events]` — this tells LangGraph to call `append_events(existing, new)` when merging updates instead of overwriting. Same pattern for `messages` with LangChain's built-in `add_messages` reducer.
- Every node receives the full state and returns only the fields it changed. LangGraph merges the partial update into the current state.

---

## File 2: `src/agents/cluster/graph.py`

This file defines the graph — three nodes connected by edges, plus a builder function.

Create `src/agents/cluster/graph.py`:

```python
"""
ogar.agents.cluster.graph

Cluster agent LangGraph subgraph — supports both stub and LLM modes.

Topology (stub mode — no LLM):
  START → ingest_events → classify_stub → route_after_classify
        → report_findings → END

Topology (LLM mode — with tools):
  START → ingest_events → classify_llm → route_after_classify
        → [tool_calls] → tool_node → classify_llm
        → [done]       → report_findings → END

Usage:
  # Stub mode (default — no API key needed):
  graph = build_cluster_agent_graph()

  # LLM mode:
  from langchain_openai import ChatOpenAI
  llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
  graph = build_cluster_agent_graph(llm=llm)

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

from __future__ import annotations

import json
import logging
from typing import Literal, Optional
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore

from agents.cluster.state import AnomalyFinding, ClusterAgentState
from tools.sensor_tools import SENSOR_TOOLS, clear_tool_state, set_tool_state

logger = logging.getLogger(__name__)


# ── System prompt for classify LLM ───────────────────────────────────────────

CLASSIFY_SYSTEM_PROMPT = """You are a wildfire monitoring analyst for sensor cluster "{cluster_id}".

You have been given a batch of sensor readings from your cluster.
Your job is to determine whether the readings indicate a real anomaly
(fire, sensor fault, sudden weather change) or normal conditions.

Use the available tools to inspect the data:
  - get_recent_readings: see the raw sensor events
  - get_sensor_summary: get aggregate stats per sensor type
  - check_threshold: test specific readings against thresholds
  - get_cluster_status: see cluster metadata

After your analysis, respond with a JSON object (and nothing else):
{{
  "anomaly_detected": true/false,
  "anomaly_type": "threshold_breach" | "sensor_fault" | "correlated_event" | "none",
  "affected_sensors": ["sensor-id-1", ...],
  "confidence": 0.0 to 1.0,
  "summary": "Brief explanation of what you found"
}}
"""


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
    trigger = state.get("trigger_event")
    logger.info(
        "ClusterAgent[%s] ingesting event from source=%s",
        state.get("cluster_id"),
        trigger.source_id if trigger else "unknown",
    )

    # Return only the fields we're changing.
    # LangGraph merges this with the existing state.
    return {
        "status": "processing",
        "error_message": None,   # Clear any previous error
    }


def classify(state: ClusterAgentState) -> dict:
    """
    Stub classify node — used when no LLM is provided.

    Produces a placeholder finding so the rest of the pipeline
    has something to work with end-to-end.
    """
    cluster_id = state.get("cluster_id", "unknown")
    trigger = state.get("trigger_event")

    logger.info(
        "ClusterAgent[%s] classify — STUB (no LLM)",
        cluster_id,
    )

    stub_finding: AnomalyFinding = {
        "finding_id": str(uuid4()),
        "cluster_id": cluster_id,
        "anomaly_type": "stub_placeholder",
        "affected_sensors": [trigger.source_id] if trigger else [],
        "confidence": 0.5,
        "summary": f"[STUB] classify node not yet implemented for cluster {cluster_id}",
        "raw_context": {
            "trigger_event_id": trigger.event_id if trigger else None,
            "event_count_in_window": len(state.get("sensor_events", [])),
        },
    }

    return {
        "anomalies": [stub_finding],
        "status": "complete",
    }


def _make_classify_llm_node(llm_with_tools: BaseChatModel):
    """
    Factory that returns a classify node backed by an LLM with bound tools.

    The returned function:
      1. Sets the tool state so tools can access sensor events.
      2. Builds a system prompt + user message from the state.
      3. Invokes the LLM (which may produce tool_calls or a final answer).
      4. Returns the AIMessage so LangGraph can route to ToolNode or report.
    """

    def classify_llm(state: ClusterAgentState) -> dict:
        cluster_id = state.get("cluster_id", "unknown")
        events = state.get("sensor_events", [])
        trigger = state.get("trigger_event")
        messages = state.get("messages", [])

        # Load tool state so tools can read the sensor events.
        set_tool_state(events, cluster_id)

        logger.info(
            "ClusterAgent[%s] classify — LLM mode (%d events, %d messages)",
            cluster_id,
            len(events),
            len(messages),
        )

        # Build initial messages if this is the first classify call.
        if not messages:
            sys_msg = SystemMessage(
                content=CLASSIFY_SYSTEM_PROMPT.format(cluster_id=cluster_id)
            )
            # Summarize the sensor data for the LLM.
            event_summaries = []
            for e in events[-20:]:
                event_summaries.append(
                    f"  [{e.source_type}] {e.source_id} tick={e.sim_tick} "
                    f"conf={e.confidence:.2f} payload={e.payload}"
                )
            user_content = (
                f"Cluster: {cluster_id}\n"
                f"Events in window: {len(events)}\n"
                f"Trigger event: {trigger.source_id if trigger else 'none'}\n"
                f"Recent readings:\n" + "\n".join(event_summaries)
            )
            user_msg = HumanMessage(content=user_content)
            messages = [sys_msg, user_msg]

        response = llm_with_tools.invoke(messages)

        return {
            "messages": [response],
            "status": "processing",
        }

    return classify_llm


def _parse_llm_findings(state: ClusterAgentState) -> dict:
    """
    Parse the LLM's final text response into an AnomalyFinding.

    This node runs after classify_llm when the LLM is done (no more tool calls).
    It extracts the JSON from the last AI message and converts it to a finding.
    """
    cluster_id = state.get("cluster_id", "unknown")
    messages = state.get("messages", [])
    trigger = state.get("trigger_event")

    # Clean up tool state.
    clear_tool_state()

    # Find the last AI message.
    last_ai = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            last_ai = msg
            break

    if last_ai is None:
        logger.warning("ClusterAgent[%s] no AI message found", cluster_id)
        return {"status": "complete", "anomalies": []}

    # Try to parse JSON from the LLM response.
    try:
        content = last_ai.content.strip()
        # Handle markdown code fences.
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        parsed = json.loads(content)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning(
            "ClusterAgent[%s] failed to parse LLM response: %s",
            cluster_id, exc,
        )
        # Fall back to a finding based on the raw text.
        parsed = {
            "anomaly_detected": True,
            "anomaly_type": "llm_parse_fallback",
            "affected_sensors": [trigger.source_id] if trigger else [],
            "confidence": 0.3,
            "summary": last_ai.content[:200],
        }

    findings: list[AnomalyFinding] = []
    if parsed.get("anomaly_detected", False):
        findings.append({
            "finding_id": str(uuid4()),
            "cluster_id": cluster_id,
            "anomaly_type": parsed.get("anomaly_type", "unknown"),
            "affected_sensors": parsed.get("affected_sensors", []),
            "confidence": float(parsed.get("confidence", 0.5)),
            "summary": parsed.get("summary", "LLM detected anomaly"),
            "raw_context": {
                "trigger_event_id": trigger.event_id if trigger else None,
                "event_count_in_window": len(state.get("sensor_events", [])),
                "llm_response": last_ai.content[:500],
            },
        })

    return {
        "anomalies": findings,
        "status": "complete",
    }


def report_findings(state: ClusterAgentState, store: Optional[BaseStore] = None) -> dict:
    """
    Final node — packages anomalies for the supervisor and writes them to
    the cross-agent Store so the supervisor can recall past incidents.

    Store write (when store is provided):
      namespace : ("incidents", cluster_id)
      key       : finding_id  (UUID — stable across restarts with pgvector)
      value     : the full AnomalyFinding dict

    The supervisor reads from ("incidents", cluster_id) in assess_situation
    to build context before making a decision.  This is the primary mechanism
    for cross-agent memory — cluster agents write, supervisor reads.

    Deduplication is handled by key: writing the same finding_id twice is a
    no-op (last write wins, same value).
    """
    anomalies = state.get("anomalies", [])
    cluster_id = state.get("cluster_id", "unknown")

    logger.info(
        "ClusterAgent[%s] reporting %d finding(s) to supervisor",
        cluster_id,
        len(anomalies),
    )

    if store is not None and anomalies:
        for finding in anomalies:
            store.put(
                ("incidents", cluster_id),
                finding["finding_id"],
                finding,
            )
        logger.info(
            "ClusterAgent[%s] wrote %d finding(s) to store namespace ('incidents', '%s')",
            cluster_id,
            len(anomalies),
            cluster_id,
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
    if state.get("status") == "error":
        logger.warning(
            "ClusterAgent[%s] exiting due to error: %s",
            state.get("cluster_id"),
            state.get("error_message"),
        )
        return "__end__"

    return "report_findings"


def route_after_classify_llm(
    state: ClusterAgentState,
) -> Literal["tool_node", "parse_findings", "__end__"]:
    """
    Router for LLM mode — checks if the LLM wants to call tools.

    If the last AI message has tool_calls → route to tool_node.
    Otherwise → route to parse_findings to extract the answer.
    On error → exit.
    """
    if state.get("status") == "error":
        return "__end__"

    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tool_node"

    return "parse_findings"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_cluster_agent_graph(
    llm: Optional[BaseChatModel] = None,
    store: Optional[BaseStore] = None,
):
    """
    Compile and return the cluster agent subgraph.

    Parameters
    ──────────
    llm   : Optional LangChain chat model.  When provided, the classify
            node uses LLM + ToolNode in a ReAct loop.  When None (default),
            a deterministic stub classify is used instead.
    store : Optional LangGraph Store.  When provided, report_findings writes
            each AnomalyFinding to ("incidents", cluster_id) so the supervisor
            can recall past incidents across runs.
            Pass InMemoryStore for dev, AsyncPostgresStore for production.

    Returns a compiled LangGraph graph ready for .invoke() or .stream().

    To test the cluster agent in isolation:
      graph = build_cluster_agent_graph()
      result = graph.invoke({
          "cluster_id": "cluster-north",
          "workflow_id": "test-run-1",
          "sensor_events": [],
          "trigger_event": some_sensor_event,
          "messages": [],
          "anomalies": [],
          "status": "idle",
          "error_message": None,
      })
    """

    builder = StateGraph(ClusterAgentState)

    builder.add_node("ingest_events", ingest_events)
    builder.add_node("report_findings", report_findings)

    builder.add_edge(START, "ingest_events")

    if llm is not None:
        # ── LLM mode: classify_llm → tool_node loop → parse_findings ──
        llm_with_tools = llm.bind_tools(SENSOR_TOOLS)
        classify_llm_node = _make_classify_llm_node(llm_with_tools)

        builder.add_node("classify", classify_llm_node)
        builder.add_node("tool_node", ToolNode(SENSOR_TOOLS))
        builder.add_node("parse_findings", _parse_llm_findings)

        builder.add_edge("ingest_events", "classify")
        builder.add_conditional_edges("classify", route_after_classify_llm)
        builder.add_edge("tool_node", "classify")
        builder.add_edge("parse_findings", "report_findings")

        logger.info("ClusterAgent subgraph compiled (LLM mode)")
    else:
        # ── Stub mode: deterministic classify ──────────────────────────
        builder.add_node("classify", classify)
        builder.add_edge("ingest_events", "classify")
        builder.add_conditional_edges("classify", route_after_classify)

        logger.info("ClusterAgent subgraph compiled (stub mode)")

    builder.add_edge("report_findings", END)

    # Passing store=store makes LangGraph inject it into any node whose
    # signature includes `store: Optional[BaseStore]`.
    # store=None is safe — nodes receive None and guard against it.
    compiled = builder.compile(store=store)
    return compiled


# Module-level compiled graph (stub mode).
# Import this in the supervisor and in tests:
#   from ogar.agents.cluster.graph import cluster_agent_graph
# The graph is compiled once when the module is first imported.
cluster_agent_graph = build_cluster_agent_graph()
```

---

*Next: Session 3 replaces the stub `classify` node with an LLM-powered ReAct loop. The LLM calls tools to inspect sensor data, reasons about anomalies, and produces findings based on actual analysis. The graph topology adds a cycle — the ReAct loop — but the state schema and the other two nodes stay exactly the same.*

---

<!--
## TALKING POINTS — not yet written into prose

Things we need to communicate to the reader in this session. Rough notes, not wordsmithed.

### On state

- `ClusterAgentState` is a TypedDict — a plain dict with type hints. LangGraph uses it to
  validate node outputs and to know what fields exist. Not a Pydantic model, not a class.
- The *reducer* concept is the key thing to nail. Without a reducer, every node return
  *replaces* the field. With `append_events`, returning `{"sensor_events": [new_event]}`
  *appends*. Same for `add_messages`. This is how state accumulates across nodes and
  across invocations.
- `status` is a Literal — the graph uses it as a lightweight FSM. Nodes write it,
  routers read it. In stub mode: idle → processing → complete. In LLM mode: add a
  possible loop through tool calls.
- The store is NOT in the state TypedDict. It's injected by LangGraph at compile time
  via `builder.compile(store=store)`. Any node with `store: Optional[BaseStore] = None`
  in its signature gets it automatically. If you see it in `report_findings` but not in
  `state.py`, that's why.

### On nodes

Three nodes, three responsibilities:
1. `ingest_events` — bookkeeping. Sets status, clears errors. Nothing interesting yet.
   In a real system: pre-filtering, history loading, schema validation.
2. `classify` (stub) / `classify_llm` (LLM mode) — the brain. This is the only node
   that differs between modes. Stub returns a hardcoded placeholder. LLM mode runs
   a ReAct loop (Session 3).
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

- The graph builder pattern (`build_cluster_agent_graph(llm=None)`) is the tutorial's
  dual-mode pattern. Same function, different topology depending on whether `llm` is provided.
- Why not two separate graph files? Because 90% of the code is identical. The factory
  function `_make_classify_llm_node` captures the LLM in a closure. The stub `classify`
  is a plain function. Both have the same signature (`state → dict`) so they're
  interchangeable as LangGraph nodes.
- The stub exists for testing and for environments without API keys. It produces a real
  `AnomalyFinding` (just with `anomaly_type: "stub_placeholder"`), so everything downstream
  works without knowing the difference.

### On where node logic lives (for readers who ask)

- All node functions are in `graph.py`. In production you'd probably split into `nodes.py`
  and `graph.py` (topology only). For a tutorial, colocation is intentional — you can
  read the whole graph without jumping files.
- The factory function pattern (`_make_classify_llm_node`) is the "injectable" pattern
  for nodes that need external dependencies. The LLM is captured in a closure, not
  passed through state. This is idiomatic LangGraph.

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
- The `from __future__ import annotations` is still in `state.py` (line 113). That's fine
  for state.py — the store injection issue only affects node function signatures in
  `graph.py`. Make sure the tutorial doesn't tell students to add it to graph.py.
- Should we show the test as part of the session? `pytest tests/agents/test_cluster.py -v`
  is already in the checkpoint — but showing what the test *checks* might help readers
  understand what "done" looks like.
-->

