# Session 7: LLM Classify Node

---

## What you're doing and why

Sessions 2–6 built the complete graph skeleton: state schemas, routing helpers, prompt registry, LLM registry, and a pre-wired ReAct topology — all without making a single LLM call. Session 7 makes the first call.

The only change is to the `classify` node. The graph topology, the state schema, the reducers, and the routing logic all stay exactly the same. You are swapping one node implementation for another.

By the end, `python main.py` will invoke a real LLM to classify sensor data and produce an `AnomalyFinding` based on actual reasoning.

---

## What's already in place

From session 6, the cluster graph topology looks like this:

```
START → ingest_events → classify → route_after_classify_llm
                             ↑              ↓ (tool_calls present)
                        tool_node ←─────────
                             ↓ (no tool_calls)
                        report_findings → END
```

`tool_node` is a placeholder stub. `route_after_classify_llm` checks `state.messages[-1]` for `tool_calls` — if there are none, it routes to `report_findings`. In this session the LLM uses `with_structured_output`, which never produces `tool_calls` on the messages list, so the ToolNode branch stays inert. Session 8 activates it.

---

## What you're building

| File | Change | What it contains |
|------|--------|-----------------|
| `src/agents/cluster/nodes.py` | **Add** | `ClassifyOutput` schema; `make_classify_node(registry)` factory |
| `src/agents/cluster/graph.py` | **Modify** | Accept `registry` parameter; use the factory when provided |
| `src/prompts/templates/classify/v1/prompt.j2` | **Modify** | Remove the tools section (the LLM has no tools yet) |
| `main.py` | **Modify** | Wire registry into `build_cluster_agent_graph` for the demo |

---

## Step 1 — Update the prompt

Open `src/prompts/templates/classify/v1/prompt.j2`. Remove the tools section (the four bullet points listing `get_recent_readings` etc.) and replace the schema instruction at the bottom. The LLM has all the data it needs in the prompt text; it doesn't need tools this session.

The updated prompt:

```jinja
You are a wildfire monitoring analyst for sensor cluster "{{ cluster_id }}".

You have been given a batch of sensor readings from your cluster.
Your job is to determine whether the readings indicate a real anomaly
(fire, sensor fault, sudden weather change) or normal conditions.

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
{% if events %}

Recent readings (last {{ [events | length, 20] | min }}):
{% for e in events[-20:] %}
  [{{ e.source_type }}] {{ e.source_id }} tick={{ e.sim_tick }} conf={{ "%.2f" | format(e.confidence) }} payload={{ e.payload | tojson }}
{% endfor %}
{% endif %}

Respond with a JSON object and nothing else:
{
  "anomaly_detected": true or false,
  "anomaly_type": "threshold_breach" | "sensor_fault" | "correlated_event" | "none",
  "affected_sensors": ["source_id_1", ...],
  "confidence": 0.0 to 1.0,
  "summary": "brief explanation of what you found"
}
```

The key difference from the old version: no tools mention, and the output spec is written plainly rather than via the `{{ schema }}` filter. `with_structured_output` will enforce the schema on the LangChain side — the prompt text just helps the LLM understand the intent.

---

## Step 2 — Add `ClassifyOutput` and `make_classify_node`

In `src/agents/cluster/nodes.py`, add two things after the existing imports.

### `ClassifyOutput` — what the LLM fills in

```python
from pydantic import BaseModel as PydanticBaseModel

class ClassifyOutput(PydanticBaseModel):
    """Structured output schema for the LLM classify call.

    Deliberately separate from AnomalyFinding: the LLM fills in only the
    fields it can reason about. cluster_id, finding_id, and raw_context
    are set programmatically after the call.
    """
    anomaly_detected: bool
    anomaly_type: str
    affected_sensors: List[str] = Field(default_factory=list)
    confidence: float
    summary: str
```

This schema is what you pass to `with_structured_output`. The LLM sees its field names and docstring and knows exactly what to produce. Fields the LLM shouldn't decide (`cluster_id`, `finding_id`, `raw_context`) are intentionally absent.

### `make_classify_node` — the factory

```python
def make_classify_node(registry):
    @node_trace("classify")
    def classify(state: ClusterAgentState) -> dict:
        llm = registry.get("classifier")

        prompt = registry.render("classify", {
            "cluster_id": state.cluster_id,
            "events": state.sensor_events,
            "trigger_id": state.trigger_event.source_id if state.trigger_event else "none",
        })

        result: ClassifyOutput = (
            llm.with_structured_output(ClassifyOutput)
               .invoke(prompt)
        )

        findings = []
        if result.anomaly_detected:
            findings.append(AnomalyFinding(
                cluster_id=state.cluster_id,
                anomaly_type=result.anomaly_type,
                affected_sensors=result.affected_sensors,
                confidence=result.confidence,
                summary=result.summary,
                raw_context={
                    "trigger_event_id": state.trigger_event.event_id if state.trigger_event else None,
                    "event_count_in_window": len(state.sensor_events),
                },
            ))

        return {
            "anomalies": findings,
            "status": StatusValue.PROCESSING,
        }
    return classify
```

**Why a factory?** The `registry` is not in the graph state schema — it's infrastructure. The factory captures it at graph-build time so the node function itself has no dependencies beyond the state it receives. This is the same pattern used by `make_report_findings(store=...)` and `make_dispatch_commands(store=...)` you already have.

**Why `with_structured_output`?** It tells LangChain: invoke the LLM and parse the response directly into a `ClassifyOutput` instance. You get back a Pydantic object, not a string. No JSON parsing, no error-prone `json.loads()`. If the LLM returns malformed output, LangChain retries automatically.

**Why `ClassifyOutput` instead of `AnomalyFinding` directly?** `AnomalyFinding` has `cluster_id` and `raw_context` fields the LLM shouldn't reason about. A narrow schema is safer and produces more reliable structured output.

---

## Step 3 — Update `graph.py`

Add a `registry` parameter to `build_cluster_agent_graph`. Everything else in the function stays the same.

```python
from config import LLMRegistry  # add this import

def build_cluster_agent_graph(
    registry: Optional[LLMRegistry] = None,
    store: Optional[BaseStore] = None,
):
    ...
    classify_node = make_classify_node(registry) if registry else classify
    builder.add_node("classify", classify_node)
    ...
```

Also update the import at the top of `graph.py` to include `make_classify_node`:

```python
from agents.cluster.nodes import (
    classify,
    ingest_events,
    make_classify_node,
    make_report_findings,
    route_after_classify_llm,
    tool_node,
)
```

The module-level `cluster_agent_graph = build_cluster_agent_graph()` at the bottom of the file stays as-is — no registry means stub mode, which is what the supervisor uses until session 9.

---

## Step 4 — Wire it in `main.py`

Add a demo function that builds the graph with a real registry:

```python
from config import get_settings, build_llm_registry, models, LLM_ROLE_CONFIG

def demo_classify_llm() -> None:
    print("=== Cluster agent demo (LLM mode) ===")

    settings = get_settings()
    settings.apply_langsmith()
    registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)

    event = SensorEvent.create(
        source_id="temp-n1",
        source_type="temperature",
        cluster_id="cluster-north",
        payload={"celsius": 52.4},
    )

    graph = build_cluster_agent_graph(registry=registry)

    result = graph.invoke(ClusterAgentState(
        cluster_id="cluster-north",
        workflow_id="demo-llm-1",
        trigger_event=event,
        sensor_events=[event],
        error_message=None,
    ))

    print(f"Status:   {result['status']}")
    print(f"Findings: {len(result['anomalies'])}")
    for f in result["anomalies"]:
        print(f"  [{f.anomaly_type}] confidence={f.confidence:.2f}")
        print(f"  {f.summary}")
        print(f"  Sensors: {f.affected_sensors}")
```

Call it from `main()`:

```python
def main() -> None:
    demo_classify_llm()
```

---

## Verify it works

```bash
python main.py
```

Expected output (exact wording varies — the LLM reasons independently):

```
=== Cluster agent demo (LLM mode) ===
Status:   processing
Findings: 1
  [threshold_breach] confidence=0.82
  Temperature reading of 52.4°C from temp-n1 significantly exceeds the 38°C danger threshold, indicating elevated fire risk.
  Sensors: ['temp-n1']
```

Two things to check:
1. `status` is `processing` not `completed` — `report_findings` sets COMPLETED, but `make_classify_node` returns `PROCESSING`. That's correct.
2. `Findings: 1` — the LLM detected an anomaly from a single 52.4°C reading. With one sensor and no corroboration, confidence should be in the 0.2–0.4 range. If it's higher, the prompt's confidence calibration section is not getting through — check that the prompt rendered correctly.

If you see `Findings: 0` the LLM decided the single reading wasn't enough evidence. That's also a valid outcome. Try adding a smoke reading alongside the temperature event and re-run.

---

## What changed vs. what didn't

| | Session 6 | Session 7 |
|---|---|---|
| Graph topology | ✓ | unchanged |
| State schema | ✓ | unchanged |
| Routers | ✓ | unchanged |
| `classify` node | stub function | `make_classify_node(registry)` factory |
| `tool_node` | stub placeholder | still placeholder (session 8) |
| `route_after_classify_llm` | checks `tool_calls` | unchanged — never sees tool_calls this session |
| Prompt template | has tools mention | tools mention removed |

The `ToolNode` stub and the `classify → tool_node → classify` cycle edge stay in the graph. `route_after_classify_llm` never routes to `tool_node` because `with_structured_output` doesn't add messages to `state.messages`. The code is already in the right shape for session 8.

---

*Next: Session 8 activates the ReAct loop — real tools bound to the LLM, `ToolNode` replaces the stub, and `route_after_classify_llm` starts routing to `tool_node` when the LLM wants to inspect sensor data before deciding.*
