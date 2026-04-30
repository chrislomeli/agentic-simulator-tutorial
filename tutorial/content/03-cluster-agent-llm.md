# Session 3: The Cluster Agent (LLM Mode)

---

## What you're doing and why

Session 2 proved the graph structure works: state flows through nodes, reducers accumulate events, the stub classify node produces `AnomalyFinding` objects. Now you add the LLM.

The graph topology changes in one place: the stub `classify` node is replaced by an LLM + ToolNode ReAct loop. Everything else — `ingest_events`, `report_findings`, the state schema, the reducers — stays exactly the same. That's the point: once you have a working graph structure, swapping the reasoning engine is just swapping one node.

The LLM doesn't receive raw sensor events as text. Instead it calls tools to query the data. This session introduces that pattern.

---

## Setup

This session builds on Session 2. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/world/ src/domains/ src/sensors/ src/transport/ src/bridge/ src/resources/ src/config.py tests/
git checkout tutorial/main -- src/agents/cluster/state.py src/agents/cluster/graph.py
pytest tests/agents/test_cluster.py -q   # should pass before you start
```

---

## Rubric coverage

| Skill | Level | Where in this session |
|-------|-------|-----------------------|
| Tool definition — @tool decorator | foundational | `sensor_tools.py` — 4 tools with docstrings + type hints |
| ToolNode + bind_tools | foundational | `llm.bind_tools(SENSOR_TOOLS)`, `ToolNode(SENSOR_TOOLS)` in `graph.py` |
| Cycles / loops | mid-level | `tool_node → classify` back-edge creates the ReAct loop |
| Dynamic branching | mid-level | `route_after_classify_llm` — checks `tool_calls` to decide loop or exit |

---

## What you're building

| File | Change | What it contains |
|------|--------|-----------------|
| `src/tools/sensor_tools.py` | **Create** | 4 `@tool` functions the LLM calls to inspect sensor data; module-level state holder |
| `src/agents/cluster/graph.py` | **Modify** | Add LLM mode branch: `_make_classify_llm_node`, `_parse_llm_findings`, `route_after_classify_llm`, `tool_node` |

When you're done:

```bash
pytest tests/agents/test_cluster.py tests/tools/ -v
```

---

## Concept Box: What are ToolNode and ReAct?

> **Read this before the code.** These are the two new LangGraph primitives this session introduces. If you understand the mechanical contract here, the code will make sense on first read.

### ToolNode — the mechanical contract

A `ToolNode` is a LangGraph node that **executes tool calls from an AIMessage and returns ToolMessages**. That's all it does. The contract is:

1. **Input:** The ToolNode reads the `messages` field from state. It looks at the **last message**. That message must be an `AIMessage` with a `tool_calls` attribute.
2. **Execution:** For each tool call, the ToolNode calls the matching Python function with the provided arguments.
3. **Output:** The ToolNode wraps each result in a `ToolMessage` and returns `{"messages": [tool_msg_1, tool_msg_2, ...]}`. The `add_messages` reducer appends these to the conversation.

You create one by passing your list of tools:

```python
from langgraph.prebuilt import ToolNode
builder.add_node("tool_node", ToolNode(SENSOR_TOOLS))
```

The ToolNode **never calls the LLM**. It only calls Python functions. The LLM decides *which* tools to call; the ToolNode *executes* them.

### ReAct loop — the pattern

ReAct (**Re**asoning + **Act**ing) is a cycle between an LLM node and a ToolNode:

```
LLM node → produces AIMessage
  ├── AIMessage has tool_calls? → ToolNode executes them → back to LLM node
  └── AIMessage has text content? → exit the loop (LLM is done)
```

A **conditional edge** after the LLM node checks `last_message.tool_calls`:
- **Has tool calls** → route to ToolNode (loop continues)
- **No tool calls** → route to the next node (loop exits)

The LLM controls how many iterations happen. It calls tools until it has enough information, then produces a final text answer. Typical iteration count: 2–4 tool calls before the LLM is satisfied.

### What can go wrong

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ToolNode` raises "no tool calls found" | Router sent a non-tool-call message to ToolNode | Check your conditional edge — only route to ToolNode when `tool_calls` is present |
| LLM never calls tools | Tools aren't bound | Verify you called `llm.bind_tools(SENSOR_TOOLS)` before creating the node |
| LLM loops forever | No exit condition | The conditional edge must have a path that exits when there are no tool_calls |
| Tool returns empty/error | State holder not set | Verify `set_tool_state()` is called before the LLM invocation |

---

## Why tools matter

An LLM without tools can only reason about what you put in the prompt. For the cluster agent, that would mean dumping all sensor events into the prompt as text and asking the LLM to classify them. That works for small batches, but it doesn't scale:

- **Context limits** — 50 sensors × 20 ticks = 1000 events. That's too much text for a prompt.
- **No structure** — the LLM sees raw JSON blobs, not queryable data.
- **No computation** — the LLM can't compute aggregates (min, max, mean) or test thresholds. It has to eyeball the data.

Tools solve this. Instead of dumping all the data into the prompt, you give the LLM functions it can call:

- `get_recent_readings(source_type="temperature", limit=10)` — fetch the last 10 temperature readings
- `get_sensor_summary()` — get aggregate stats (count, min, max, mean) per sensor type
- `check_threshold(source_type="temperature", payload_key="celsius", threshold=40.0, direction="above")` — test if any reading exceeds a threshold
- `get_cluster_status()` — get metadata (cluster_id, event count, unique sensors)

The LLM calls these tools to inspect the data, gets structured results back, and reasons about what it found. This is the ReAct pattern: **Re**asoning + **Act**ing in a loop.

---

## The four sensor tools

Tools are defined with the `@tool` decorator from LangChain. Here's the structure:

```python
from langchain_core.tools import tool

@tool
def get_recent_readings(
    source_type: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return the most recent sensor readings from this cluster.

    Args:
        source_type: Filter by sensor type (e.g. "temperature", "smoke").
                     If None, return all types.
        limit: Maximum number of readings to return (default 10).

    Returns:
        List of dicts with source_id, source_type, sim_tick, confidence,
        and payload for each reading.
    """
    events = _state.events
    if source_type:
        events = [e for e in events if e.source_type == source_type]
    events = events[-limit:]
    return [
        {
            "source_id": e.source_id,
            "source_type": e.source_type,
            "sim_tick": e.sim_tick,
            "confidence": e.confidence,
            "payload": e.payload,
        }
        for e in events
    ]
```

**What the LLM sees:**
- **Function name** — `get_recent_readings`
- **Docstring** — the full description, including the Args and Returns sections
- **Type hints** — `source_type: Optional[str]`, `limit: int` → JSON schema with types and optionality

The LLM uses this information to decide when to call the tool and what arguments to pass. If the LLM wants to see the last 5 temperature readings, it produces:

```json
{
  "tool_calls": [
    {
      "name": "get_recent_readings",
      "args": {"source_type": "temperature", "limit": 5}
    }
  ]
}
```

LangGraph's `ToolNode` executes the call and returns the result as a `ToolMessage`. The LLM sees the result and can call more tools or produce a final answer.

**Module-level state holder:** Tools need access to the sensor events. We use a simple module-level holder:

```python
class _SensorToolState:
    events: List[SensorEvent] = []
    cluster_id: str = ""

_state = _SensorToolState()

def set_tool_state(events: List[SensorEvent], cluster_id: str) -> None:
    _state.events = list(events)
    _state.cluster_id = cluster_id
```

The classify_llm node calls `set_tool_state(events, cluster_id)` before invoking the LLM. Tools read from `_state.events`. After the loop, `clear_tool_state()` cleans up.

This avoids passing the full LangGraph state into each tool function. Tools are simple: they accept primitive arguments (strings, numbers) and return JSON-serializable dicts.

---

## The LLM node: classify_llm

The classify_llm node is built by a factory function that binds tools to the LLM:

```python
def _make_classify_llm_node(llm_with_tools: BaseChatModel):
    def classify_llm(state: ClusterAgentState) -> dict:
        cluster_id = state.get("cluster_id", "unknown")
        events = state.get("sensor_events", [])
        trigger = state.get("trigger_event")
        messages = state.get("messages", [])
        
        # Load tool state so tools can read the sensor events
        set_tool_state(events, cluster_id)
        
        # Build initial messages if this is the first call
        if not messages:
            sys_msg = SystemMessage(
                content=CLASSIFY_SYSTEM_PROMPT.format(cluster_id=cluster_id)
            )
            # Summarize sensor data for the LLM
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
```

**System prompt:** The LLM is told it's a wildfire monitoring analyst for this cluster. It's given a list of tools and instructed to analyze the sensor data and respond with a JSON object:

```json
{
  "anomaly_detected": true/false,
  "anomaly_type": "threshold_breach" | "sensor_fault" | "correlated_event" | "none",
  "affected_sensors": ["sensor-id-1", ...],
  "confidence": 0.0 to 1.0,
  "summary": "Brief explanation of what you found"
}
```

**Initial messages:** The first time the node runs, it builds a system message and a user message with a summary of the sensor data (last 20 events). On subsequent calls (during the ReAct loop), `messages` already contains the conversation history, so it just invokes the LLM with the existing messages.

**Response:** The LLM returns an `AIMessage`. If it wants to call tools, the message will have a `tool_calls` attribute. If it's done, the message will have text content (the JSON response).

The node returns `{"messages": [response]}`. The `add_messages` reducer appends this to the conversation history.

---

## The ReAct loop: classify_llm ↔ tool_node

Here's the graph topology in LLM mode:

```
START → ingest_events → classify_llm ──→ parse_findings → report_findings → END
                            ↓    ↑
                        tool_node
```

**The cycle:**
1. `classify_llm` invokes the LLM
2. If the LLM produces `tool_calls`, the router sends it to `tool_node`
3. `tool_node` executes the tool calls and returns `ToolMessage` results
4. Edge from `tool_node` goes **back** to `classify_llm` (this is the loop)
5. `classify_llm` invokes the LLM again with the tool results in the message history
6. LLM sees the results, reasons, and either calls more tools or produces a final answer
7. When the LLM produces a final answer (no `tool_calls`), the router sends it to `parse_findings`

**Router logic:**

```python
def route_after_classify_llm(
    state: ClusterAgentState,
) -> Literal["tool_node", "parse_findings", "__end__"]:
    if state.get("status") == "error":
        return "__end__"
    
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tool_node"  # LLM wants to call tools
    
    return "parse_findings"  # LLM is done, parse the answer
```

The router checks the last message. If it's an `AIMessage` with `tool_calls`, route to `tool_node`. Otherwise, route to `parse_findings`.

**ToolNode:** LangGraph's `ToolNode` is a built-in node that executes tool calls. You pass it the list of tools:

```python
builder.add_node("tool_node", ToolNode(SENSOR_TOOLS))
```

When the node runs, it:
1. Reads `tool_calls` from the last `AIMessage`
2. Executes each tool call (calls the actual Python function)
3. Wraps the results in `ToolMessage` objects
4. Returns `{"messages": [tool_message1, tool_message2, ...]}`

The `add_messages` reducer appends these to the conversation. The next time `classify_llm` runs, the LLM sees the tool results and can reason about them.

---

## Parsing the final answer

When the LLM is done (no more tool calls), the router sends it to `parse_findings`:

```python
def _parse_llm_findings(state: ClusterAgentState) -> dict:
    cluster_id = state.get("cluster_id", "unknown")
    messages = state.get("messages", [])
    trigger = state.get("trigger_event")
    
    clear_tool_state()  # Clean up
    
    # Find the last AI message
    last_ai = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            last_ai = msg
            break
    
    if last_ai is None:
        return {"status": "complete", "anomalies": []}
    
    # Try to parse JSON from the LLM response
    try:
        content = last_ai.content.strip()
        # Handle markdown code fences
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        parsed = json.loads(content)
    except (json.JSONDecodeError, Exception) as exc:
        # Fall back to a finding based on the raw text
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
```

This node:
1. Finds the last `AIMessage` with content
2. Tries to parse it as JSON
3. Handles markdown code fences (LLMs sometimes wrap JSON in ` ```json ... ``` `)
4. Falls back to a degraded finding if parsing fails
5. Converts the parsed JSON into an `AnomalyFinding` dict
6. Returns `{"anomalies": [finding], "status": "complete"}`

The finding structure is the same as in stub mode. The only difference is the values come from LLM reasoning instead of hardcoded stubs.

---

## Building the LLM graph

The `build_cluster_agent_graph()` function has two branches:

```python
if llm is not None:
    # LLM mode
    llm_with_tools = llm.bind_tools(SENSOR_TOOLS)
    classify_llm_node = _make_classify_llm_node(llm_with_tools)
    
    builder.add_node("classify", classify_llm_node)
    builder.add_node("tool_node", ToolNode(SENSOR_TOOLS))
    builder.add_node("parse_findings", _parse_llm_findings)
    
    builder.add_edge("ingest_events", "classify")
    builder.add_conditional_edges("classify", route_after_classify_llm)
    builder.add_edge("tool_node", "classify")  # ← THE CYCLE
    builder.add_edge("parse_findings", "report_findings")
else:
    # Stub mode (Session 06)
    builder.add_node("classify", classify)
    builder.add_edge("ingest_events", "classify")
    builder.add_conditional_edges("classify", route_after_classify)
```

**bind_tools():** This is the LangChain method that attaches tool schemas to the LLM. After binding, when you invoke the LLM, it knows it can produce `tool_calls` in its response.

**The cycle edge:** `builder.add_edge("tool_node", "classify")` creates the loop. After the tool node runs, control goes **back** to classify_llm, not forward to the next node. This is how the ReAct loop works.

---

## Running it

Here's a complete script that invokes the LLM graph:

```python
from langchain_openai import ChatOpenAI
from agents.cluster.graph import build_cluster_agent_graph
from transport.schemas import SensorEvent

# Build the graph (LLM mode)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
graph = build_cluster_agent_graph(llm=llm)

# Create sensor events (temperature spike scenario)
events = [
    SensorEvent.create(
        source_id="temp-1",
        source_type="temperature",
        cluster_id="cluster-north",
        payload={"celsius": 45.0, "unit": "C"},
        confidence=0.9,
        sim_tick=5,
    ),
    SensorEvent.create(
        source_id="temp-2",
        source_type="temperature",
        cluster_id="cluster-north",
        payload={"celsius": 48.0, "unit": "C"},
        confidence=0.85,
        sim_tick=6,
    ),
    SensorEvent.create(
        source_id="smoke-1",
        source_type="smoke",
        cluster_id="cluster-north",
        payload={"pm25_ugm3": 120.0, "unit": "µg/m³"},
        confidence=0.95,
        sim_tick=6,
    ),
]

# Invoke the graph
result = graph.invoke({
    "cluster_id": "cluster-north",
    "workflow_id": "test-llm-1",
    "sensor_events": events,
    "trigger_event": events[-1],
    "messages": [],
    "anomalies": [],
    "status": "idle",
    "error_message": None,
})

# Inspect the result
print(f"Status: {result['status']}")
print(f"Messages exchanged: {len(result['messages'])}")
print(f"Findings: {len(result['anomalies'])}")
for f in result["anomalies"]:
    print(f"\n  [{f['anomaly_type']}] conf={f['confidence']:.2f}")
    print(f"  Summary: {f['summary']}")
    print(f"  Affected sensors: {f['affected_sensors']}")
```

You should see output like:

```
Status: complete
Messages exchanged: 6
Findings: 1

  [threshold_breach] conf=0.85
  Summary: Temperature readings from temp-1 and temp-2 exceed 40°C threshold, correlated with elevated PM2.5 from smoke-1, indicating possible fire activity
  Affected sensors: ['temp-1', 'temp-2', 'smoke-1']
```

The LLM:
1. Called `get_recent_readings()` to see the data
2. Called `check_threshold(source_type="temperature", payload_key="celsius", threshold=40.0, direction="above")` to test the temperature spike
3. Called `get_sensor_summary()` to see aggregate stats
4. Produced a final JSON response classifying this as a `threshold_breach` with confidence 0.85

The message count (6) includes: system message, user message, AI message with tool calls, 3 tool messages, final AI message with JSON.

---

## What you learned: LLM + Tools in LangGraph

This session introduced the LLM integration patterns:

**1. Tool definition** — `@tool` decorator + docstring + type hints = complete tool schema the LLM can see and call.

**2. bind_tools()** — attaches tool schemas to the LLM so it knows it can produce `tool_calls` in its response.

**3. ToolNode** — built-in LangGraph node that executes tool calls from `AIMessage` and returns `ToolMessage` results.

**4. ReAct loop** — cycle between LLM node and tool node. LLM calls tools, sees results, calls more tools or produces final answer.

**5. Conditional routing** — router checks for `tool_calls` to decide whether to loop or exit.

**6. Module-level state holder** — tools read from a shared state holder set before the LLM call, avoiding the need to pass full LangGraph state into each tool.

The graph structure from Session 06 (state schema, node signatures, partial updates, reducers) stays the same. The only change is swapping the stub classify node for an LLM + ToolNode ReAct loop. That's the power of the abstraction — you can swap implementations without changing the interface.

---

## Checkpoint

```bash
pytest tests/agents/test_cluster.py tests/tools/ -v
```

All tests should pass. Key ones to look for:
- `test_invoke_stub_mode` — graph runs without LLM
- `test_invoke_llm_mode` — graph runs with a mock LLM
- `test_sensor_tools` — tools return correct data shapes

---

## Key files

- `src/tools/sensor_tools.py` — 4 `@tool` functions: `get_recent_readings`, `get_sensor_summary`, `check_threshold`, `get_cluster_status`; module-level state holder
- `src/agents/cluster/graph.py` — `_make_classify_llm_node`, `route_after_classify_llm`, `_parse_llm_findings`, LLM mode branch in `build_cluster_agent_graph()`

---

*Next: Session 4 wires the full sensor → agent pipeline end-to-end. The world ticks, sensors emit events, the publisher puts them on a queue, the consumer batches them and invokes the cluster agent (LLM mode), and findings flow out. First complete loop from simulation to AI reasoning.*
