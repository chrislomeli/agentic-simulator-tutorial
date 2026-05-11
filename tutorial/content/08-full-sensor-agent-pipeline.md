# Session 8: ReAct Tool Loop and Cross-tick History

---

## What you're doing and why

Session 7 made the first LLM call. It works — but the LLM is doing three things simultaneously from raw event JSON: extracting structure from noisy readings, applying domain rules, and committing to a confidence score. With 30+ events in context, that's a lot to ask in one shot.

Session 8 fixes this by adding two things:

**1. The ReAct tool loop** — the LLM can now call tools before deciding. It calls `get_sensor_summary()` to get structured features, `check_threshold()` to test specific readings, and `get_recent_readings()` when it wants to inspect a specific sensor type. When satisfied, it produces a JSON response. The loop only makes as many tool calls as the case requires — one for simple detections, several for ambiguous ones.

**2. Cross-tick history** — `ingest_events` now loads the previous event window from the store and merges it with the current tick's events before `classify` runs. Without this, the LLM only sees single-tick data and cannot detect trends (e.g., temperature rising over 5 ticks). `report_findings` writes the merged window back so the next invocation picks up where this one left off.

By the end, `python main.py` runs a multi-turn tool loop with per-tick history, producing findings grounded in both current readings and recent trends.

---

## What's already in place

From session 7, the cluster graph topology is:

```
START → ingest_events → classify → route_after_classify → report_findings → END
```

`state.messages` is already in the schema with `add_messages` reducer. `store` is already plumbed into `make_report_findings`. This session adds the cycle and activates the store reads.

---

## What you're building

| File | Change | What it contains |
|------|--------|-----------------|
| `src/agents/cluster/tools.py` | **New** | `get_sensor_summary`, `check_threshold`, `get_recent_readings` |
| `src/agents/cluster/nodes.py` | **Modify** | Update `make_classify_node` for tool loop; update `ingest_events` for store read; update `make_report_findings` for store write; add `route_after_classify_llm`, `tool_node` |
| `src/agents/cluster/graph.py` | **Modify** | Accept `tools` parameter; add cycle topology |
| `src/prompts/templates/classify/v1/prompt.j2` | **Modify** | Restore tools section with real tool names |
| `main.py` | **Modify** | Demo that shows tool loop in action |

---

## Step 1 — Add the tools

Create `src/agents/cluster/tools.py`. These tools give the LLM structured access to data it already has in `state.sensor_events` — they don't fetch anything new.

```python
"""
Tools available to the evaluate LLM during the ReAct loop.

Each tool receives sensor event raw injected at call time via closure.
The LLM calls these to structure raw raw before reasoning.
"""

from typing import Any, Dict, List
from langchain_core.tools import tool


def make_classify_tools(events: list):
    """
    Return tool functions with the current event list bound via closure.

    Called at the start of each evaluate node invocation so the tools
    always operate on the current state's sensor_events.
    """

    @tool
    def get_sensor_summary() -> Dict[str, Any]:
        """
        Aggregate all sensor events by type.

        Returns a dict with max, min, mean, and count per sensor type.
        Use this first to get a structured view of what the sensors are reporting.
        """
        from collections import defaultdict
        buckets: Dict[str, list] = defaultdict(list)
        for e in events:
            val = None
            p = e.payload if hasattr(e, "payload") else {}
            for v in p.values():
                if isinstance(v, (int, float)):
                    val = v
                    break
            if val is not None:
                buckets[e.source_type].append(val)

        summary = {}
        for stype, vals in buckets.items():
            summary[stype] = {
                "count": len(vals),
                "max": round(max(vals), 2),
                "min": round(min(vals), 2),
                "mean": round(sum(vals) / len(vals), 2),
            }
        return summary

    @tool
    def check_threshold(source_type: str, value: float) -> Dict[str, Any]:
        """
        Check whether a sensor reading crosses a fire-danger threshold.

        Args:
            source_type: One of "temperature", "humidity", "wind", "fuel_moisture", "smoke"
            value: The reading to check

        Returns a dict with 'breached' (bool) and 'rule' (description of the threshold).
        """
        thresholds = {
            "temperature":   (lambda v: v > 38,   "temperature > 38°C"),
            "humidity":      (lambda v: v < 15,   "humidity < 15%"),
            "wind":          (lambda v: v > 10,   "wind > 10 m/s"),
            "fuel_moisture": (lambda v: v < 8,    "fuel moisture < 8%"),
            "smoke":         (lambda v: v > 0,    "smoke detected"),
        }
        if source_type not in thresholds:
            return {"breached": False, "rule": f"no threshold defined for {source_type}"}
        fn, description = thresholds[source_type]
        return {"breached": fn(value), "rule": description, "value": value}

    @tool
    def get_recent_readings(source_type: str, n: int = 5) -> List[Dict[str, Any]]:
        """
        Return the last N events for a specific sensor type.

        Args:
            source_type: Filter to this sensor type (e.g. "temperature")
            n: How many recent readings to return (default 5)

        Useful for spotting trends — is temperature rising across ticks,
        or was it a single spike?
        """
        matching = [e for e in events if e.source_type == source_type]
        recent = matching[-n:]
        return [
            {
                "source_id": e.source_id,
                "sim_tick": e.sim_tick,
                "confidence": e.confidence,
                "payload": e.payload,
            }
            for e in recent
        ]

    return [get_sensor_summary, check_threshold, get_recent_readings]
```

**Why a closure?** Each `classify` invocation operates on a different `state.sensor_events` list. The closure binds the current list at call time without needing to pass it as a tool argument (which the LangChain tool interface doesn't support cleanly). `make_classify_tools(state.sensor_events)` returns fresh tool functions for each invocation.

---

## Step 2 — Update the prompt

Open `src/prompts/templates/classify/v1/prompt.j2`. Restore the tools section — now with the real tool names — and update the output instruction to tell the LLM to produce JSON when it's done calling tools.

```jinja
You are a wildfire monitoring analyst for sensor cluster "{{ cluster_id }}".

You have been given a batch of sensor readings from your cluster.
Your job is to determine whether the readings indicate a real anomaly
(fire, sensor fault, sudden weather change) or normal conditions.

Use the available tools to structure your analysis:
  - get_sensor_summary: aggregate readings by sensor type (max, min, mean, count)
  - check_threshold: test whether a specific reading crosses a fire-danger threshold
  - get_recent_readings: inspect the last N readings for a given sensor type

DOMAIN RULES — use these to guide your classification:

  Evidence strength:
  - Convergent evidence is the strongest signal: temperature > 38°C AND
    humidity < 15% AND wind > 10 m/s together indicate extreme fire weather.
    Any single elevated reading alone could be sensor noise.
  - A single spike in one sensor type with no corroboration from other
    types is more likely a sensor fault than a real event.
  - Smoke detection near known burning cells is expected, not anomalous.
    Only flag smoke where no fire is known.

  Dangerous conditions:
  - Temperature > 38°C is elevated fire danger.
  - Humidity < 15% is extreme dryness — fuels ignite easily.
  - Wind > 10 m/s enables rapid fire spread.
  - All three together constitute "critical fire weather."
  - Fuel moisture < 8% is the strongest ignition predictor.

  Confidence calibration:
  - 3+ sensor types corroborating → confidence 0.8–1.0
  - 2 sensor types corroborating  → confidence 0.5–0.8
  - 1 sensor type elevated alone  → confidence 0.2–0.4 (possible fault)

Trigger event: {{ trigger_id }}
Events in window: {{ events | length }}

When you have gathered enough evidence, respond with ONLY a JSON object — no other text:
{
  "anomaly_detected": true or false,
  "anomaly_type": "threshold_breach" | "sensor_fault" | "correlated_event" | "none",
  "affected_sensors": ["source_id_1", ...],
  "confidence": 0.0 to 1.0,
  "summary": "brief explanation of what you found and what evidence you used"
}
```

The key change: the event dump is removed (the LLM calls `get_sensor_summary()` instead), and the output instruction is explicit that JSON comes only after the tool calls are done.

---

## Step 3 — Update `nodes.py`

Four changes in `src/agents/cluster/nodes.py`.

### 3a — Update `make_classify_node` for the tool loop

Replace the existing `make_classify_node` factory. The node now manages a message list and uses `bind_tools` instead of `with_structured_output`.

```python
import json
from langchain_core.messages import HumanMessage

def make_classify_node(registry, tools: list):
    @node_trace("evaluate")
    def classify(state: ClusterAgentState) -> dict:
        llm = registry.get("classifier").bind_tools(tools)
        messages = list(state.messages)

        if not messages:
            prompt = registry.render("evaluate", {
                "cluster_id": state.cluster_id,
                "events": state.sensor_events,
                "trigger_id": state.trigger_event.source_id if state.trigger_event else "none",
            })
            messages = [HumanMessage(content=prompt)]

        response = llm.invoke(messages)

        if response.tool_calls:
            return {
                "messages": [response],
                "status": StatusValue.PROCESSING,
            }

        # No tool_calls — the LLM produced its final JSON answer.
        try:
            data = json.loads(response.content)
            output = ClassifyOutput(**data)
        except Exception as exc:
            logger.warning("evaluate: failed to parse LLM response: %s", exc)
            return {
                "messages": [response],
                "anomalies": [],
                "status": StatusValue.PROCESSING,
            }

        findings = []
        if output.anomaly_detected:
            findings.append(AnomalyFinding(
                cluster_id=state.cluster_id,
                anomaly_type=output.anomaly_type,
                affected_sensors=output.affected_sensors,
                confidence=output.confidence,
                summary=output.summary,
                raw_context={
                    "trigger_event_id": state.trigger_event.event_id if state.trigger_event else None,
                    "event_count_in_window": len(state.sensor_events),
                },
            ))

        return {
            "messages": [response],
            "anomalies": findings,
            "status": StatusValue.PROCESSING,
        }
    return classify
```

**Why `bind_tools` instead of `with_structured_output`?** `with_structured_output` wraps the entire call and returns a Pydantic object directly — it has no mechanism for tool calls. `bind_tools` lets the LLM call tools first, then produce text. The final text is the JSON we parse into `ClassifyOutput`.

**Why not re-build the initial message on subsequent classify calls?** When `state.messages` is non-empty, the loop is already running — tool results are in the message list. Rebuilding the initial prompt would erase the tool context. The check `if not messages` ensures we build the prompt only once.

### 3b — Add `route_after_classify_llm`

```python
def route_after_classify_llm(state: ClusterAgentState) -> str:
    last = state.messages[-1] if state.messages else None
    if last and getattr(last, "tool_calls", None):
        return "tool_node"
    return _route_base(state, next_node="report_findings")
```

This replaces `route_after_classify` for the LLM-mode graph. It checks the last message for `tool_calls`. If present, the LLM wants to call tools — route to `tool_node`. If absent, the LLM is done — hand off to `_route_base` for the normal success/error routing.

### 3c — Add `tool_node`

```python
from langgraph.prebuilt import ToolNode

def make_tool_node(tools: list) -> ToolNode:
    return ToolNode(tools)
```

`ToolNode` is LangGraph's prebuilt node for executing tool calls. It reads `tool_calls` from the last `AIMessage`, executes each tool, and appends `ToolMessage` results to the message list. The classify node sees these results on its next invocation.

### 3d — Update `ingest_events` to load history from the store

The `ingest_events` function needs access to the store. Convert it to a factory matching the pattern already used by `make_report_findings`.

```python
def make_ingest_events(store: Optional[BaseStore] = None):
    @node_trace("ingest_events")
    def ingest_events(state: ClusterAgentState) -> dict:
        history: List[SensorEvent] = []
        if store is not None:
            item = store.get(("events", state.cluster_id), "window")
            if item and item.value:
                history = [SensorEvent(**e) for e in item.value]
                logger.info(
                    "ClusterAgent[%s] loaded %d historical events from store",
                    state.cluster_id,
                    len(history),
                )

        return {
            "status": StatusValue.PROCESSING,
            "error_message": None,
            "sensor_events": history,
        }
    return ingest_events
```

The `append_events` reducer merges `history` with the events already in `state.sensor_events` (the current tick's events, passed in by the supervisor). The result is a rolling window of up to 50 events spanning multiple ticks.

Also update `make_report_findings` to write the event window back to the store:

```python
def make_report_findings(store: Optional[BaseStore] = None):
    @node_trace("report_findings")
    def report_findings(state: ClusterAgentState) -> dict:
        anomalies = state.anomalies or []
        cluster_id = state.cluster_id

        if store is not None:
            # Write findings
            for finding in anomalies:
                store.put(
                    ("incidents", cluster_id),
                    finding.finding_id,
                    finding.model_dump(),
                )
            # Write rolling event window for next invocation
            if state.sensor_events:
                store.put(
                    ("events", cluster_id),
                    "window",
                    [e.model_dump() for e in state.sensor_events],
                )
            logger.info(
                "ClusterAgent[%s] stored %d finding(s), %d events",
                cluster_id,
                len(anomalies),
                len(state.sensor_events),
            )

        return {"status": StatusValue.COMPLETED}
    return report_findings
```

---

## Step 4 — Update `graph.py`

Add `tools` parameter and the cycle topology.

```python
from langgraph.prebuilt import ToolNode
from agents.cluster.nodes import (
    make_classify_node,
    make_ingest_events,
    make_report_findings,
    make_tool_node,
    route_after_classify,
    route_after_classify_llm,
)

def build_cluster_agent_graph(
    registry=None,
    store: Optional[BaseStore] = None,
):
    from agents.cluster.tools import make_classify_tools

    builder = StateGraph(ClusterAgentState)

    if registry is not None:
        # LLM mode: tools bound from a placeholder event list.
        # make_classify_node rebinds tools at call time via closure.
        tools = make_classify_tools([])
        classify_node = make_classify_node(registry, tools)
        tn = make_tool_node(tools)
        route_fn = route_after_classify_llm
    else:
        from agents.cluster.nodes import classify as classify_stub
        classify_node = classify_stub
        tn = None
        route_fn = route_after_classify

    builder.add_node("ingest_events", make_ingest_events(store=store))
    builder.add_node("evaluate", classify_node)
    builder.add_node("report_findings", make_report_findings(store=store))

    builder.add_edge(START, "ingest_events")
    builder.add_edge("ingest_events", "evaluate")
    builder.add_conditional_edges("evaluate", route_fn)

    if tn is not None:
        builder.add_node("tool_node", tn)
        builder.add_edge("tool_node", "evaluate")

    builder.add_edge("report_findings", END)
    return builder.compile()
```

**Wait — the tools closure.** There's a subtlety here: `make_classify_tools([])` creates tools bound to an empty list. But each classify invocation needs tools bound to the *current* `state.sensor_events`.

The fix: inside `make_classify_node`, rebuild the tools from the current state before binding:

```python
def make_classify_node(registry, _tools_unused):
    @node_trace("evaluate")
    def classify(state: ClusterAgentState) -> dict:
        from agents.cluster.tools import make_classify_tools
        tools = make_classify_tools(state.sensor_events)   # bind current events
        llm = registry.get("classifier").bind_tools(tools)
        ...
```

This means `graph.py` doesn't need to pass tools at build time for the classify node — it only passes them for `ToolNode`. Update the graph builder accordingly:

```python
tools = make_classify_tools([])          # for ToolNode (schema only; evaluate rebinds)
classify_node = make_classify_node(registry)
tn = make_tool_node(tools)
```

And `make_classify_node` signature becomes just `make_classify_node(registry)` again.

---

## Step 5 — Wire it in `main.py`

Add a demo that shows the tool loop in action with multiple sensor types:

```python
def demo_classify_react() -> None:
    print("=== Cluster agent demo (ReAct tool loop) ===")

    settings = get_settings()
    settings.apply_langsmith()
    registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)
    store = InMemoryStore()

    trigger = SensorEvent.create(
        source_id="temp-n1",
        source_type="temperature",
        cluster_id="cluster-north",
        payload={"celsius": 52.4},
    )

    events = [
        trigger,
        SensorEvent.create(
            source_id="hum-n1",
            source_type="humidity",
            cluster_id="cluster-north",
            payload={"relative_humidity_pct": 11.0},
        ),
        SensorEvent.create(
            source_id="wind-n1",
            source_type="wind",
            cluster_id="cluster-north",
            payload={"speed_mps": 13.5},
        ),
    ]

    graph = build_cluster_agent_graph(registry=registry, store=store)

    result = graph.invoke(ClusterAgentState(
        cluster_id="cluster-north",
        workflow_id="demo-react-1",
        trigger_event=trigger,
        sensor_events=events,
        error_message=None,
    ))

    print(f"Status:   {result['status']}")
    print(f"Messages: {len(result['messages'])} (tool calls + responses)")
    print(f"Findings: {len(result['anomalies'])}")
    for f in result["anomalies"]:
        print(f"  [{f.anomaly_type}] confidence={f.confidence:.2f}")
        print(f"  {f.summary}")
        print(f"  Sensors: {f.affected_sensors}")
```

Import `InMemoryStore`:
```python
from langgraph.store.memory import InMemoryStore
```

---

## Verify it works

```bash
python main.py
```

Expected output pattern:

```
=== Cluster agent demo (ReAct tool loop) ===
Status:   completed
Messages: 5  (initial prompt, tool_call, tool_result, tool_call, tool_result, final answer — varies)
Findings: 1
  [correlated_event] confidence=0.92
  Temperature 52.4°C, humidity 11%, wind 13.5 m/s — all three thresholds breached simultaneously. Critical fire weather.
  Sensors: ['temp-n1', 'hum-n1', 'wind-n1']
```

Things to verify:
1. `Messages > 1` — the LLM made at least one tool call before deciding.
2. `confidence` is 0.8–1.0 — three corroborating sensor types, the calibration rules should fire.
3. `anomaly_type` is `correlated_event` — not a threshold breach on a single sensor.
4. The `summary` mentions what tools it used as evidence.

If you see `Messages: 1`, the LLM skipped tool calls and went straight to the final answer — check that the prompt's tools section is present and the tools are bound.

If you see a parse error on the final response, the LLM didn't produce clean JSON. Check that the prompt ends with the JSON instruction and no trailing tools mention.

---

## What changed vs. what didn't

| | Session 7 | Session 8 |
|---|---|---|
| Graph topology | linear | cycle added (classify ↔ tool_node) |
| `classify` node | `with_structured_output`, one call | `bind_tools`, multi-turn loop |
| `ingest_events` | sets status only | loads history from store |
| `report_findings` | writes findings | writes findings + event window |
| Router | `route_after_classify` | `route_after_classify_llm` |
| State `messages` | unused | drives the tool loop |
| Prompt | no tools section | tools section restored |
| `ClassifyOutput` | structured output target | parsed from final JSON text |

The classifier contract is unchanged: `classify` still receives `state.sensor_events: List[SensorEvent]`. What changed is how the LLM accesses that list — through tools rather than a raw JSON dump.

---

*Next: Session 9 adds the bridge layer — the tick driver that invokes the supervisor once per simulation tick. Until now, you've been calling `graph.invoke()` directly from `main.py`. Session 9 wires the world engine, sensors, and agent pipeline into a continuous loop.*
