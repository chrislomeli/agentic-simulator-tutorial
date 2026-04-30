# Session 4: The Full Sensor-to-Agent Pipeline

---

## What you're doing and why

Sessions 1–3 built all the pieces in isolation: world engine, sensors, transport, and cluster agent. This session wires them together. No new source files — just connecting the interfaces.

This is important for a reason beyond "getting it to run": until the pieces run together, you don't know if the *interfaces* match. Does the consumer construct the right state dict for the agent? Do findings flow back through the callback? Does the async orchestration deadlock? This session answers those questions.

You also add observability here: LangSmith tracing and LangGraph stream mode. Both are important for debugging agent behavior in later sessions.

---

## Setup

This session builds on Sessions 1–3. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/world/ src/domains/ src/sensors/ src/transport/ src/bridge/ src/resources/ src/config.py tests/
git checkout tutorial/main -- src/agents/ src/tools/
pytest tests/ -q --ignore=tests/agents/test_supervisor.py   # should pass before you start
```

---

## Rubric coverage

| Skill | Level | Where in this session |
|-------|-------|-----------------------|
| Compile + invoke / stream | foundational | `graph.stream(state, stream_mode="updates")` |
| stream_mode — values vs updates | mid-level | Comparing `stream_mode="updates"` output to `invoke()` |
| LangSmith tracing | mid-level | `LANGCHAIN_TRACING_V2` environment variables |

---

## What you're building

No new source files. This session runs the pipeline you already built.

The key task is writing and running the integration script that connects all components.

---

## Why end-to-end matters

You've built:
- **Sessions 01–02:** A simulation that runs fire physics and produces ground truth
- **Sessions 03–04:** Sensors that sample the simulation and emit noisy observations
- **Session 05:** A bridge consumer that batches events and invokes agents
- **Sessions 06–07:** A cluster agent graph that classifies events into findings

Each piece works in isolation. But until you wire them together, you don't know if the *interfaces* work. Does the consumer construct the state dict correctly? Does the agent handle batched events? Do findings flow back through the callback? Does the async orchestration actually run without deadlocks?

This session answers those questions. You'll run the full pipeline and see:
- World ticks → sensor readings change as fire spreads
- Publisher → events accumulate in the queue
- Consumer → batches events and invokes the agent
- Agent → produces findings based on sensor data
- Findings → collected via callback for inspection

This is the first time the system runs as a *system* instead of a collection of components.

---

## The pipeline stages

Here's the data flow:

```
GenericWorldEngine.tick()
  ↓
Sensors.emit() → SensorEvent objects
  ↓
SensorPublisher.run() → queue.put(event)
  ↓
SensorEventQueue (async buffer)
  ↓
EventBridgeConsumer.run() → queue.get(event)
  ↓
Consumer batches by cluster_id
  ↓
Consumer invokes cluster_agent_graph.invoke(state)
  ↓
ClusterAgent produces AnomalyFinding objects
  ↓
Consumer calls on_finding(finding) callback
  ↓
Findings collected in a list
```

Each stage is async. The publisher and consumer run as separate async tasks. The queue provides back-pressure: if the consumer is slow, the publisher blocks on `queue.put()`. If the publisher is slow, the consumer blocks on `queue.get()`. This is how async pipelines naturally balance load.

---

## Building the pipeline

Here's the complete setup:

```python
import asyncio
from domains.wildfire import create_basic_wildfire
from domains.wildfire.sensors import TemperatureSensor, SmokeSensor
from world.sensor_inventory import SensorInventory
from sensors import SensorPublisher
from transport import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph

async def main():
    # ── Stage 1: World + Sensors ────────────────────────────────
    engine = create_basic_wildfire()
    queue = SensorEventQueue()
    inventory = SensorInventory(grid_rows=10, grid_cols=10)
    
    # Add temperature sensors at 5 positions
    for row, col in [(2, 2), (2, 7), (5, 5), (7, 2), (7, 7)]:
        sensor = TemperatureSensor(
            source_id=f"temp-{row}-{col}",
            cluster_id="cluster-north",
            engine=engine,
            grid_row=row,
            grid_col=col,
        )
        inventory.register(sensor, row=row, col=col)
    
    # Add smoke sensors at 3 positions
    for row, col in [(3, 3), (5, 5), (7, 7)]:
        sensor = SmokeSensor(
            source_id=f"smoke-{row}-{col}",
            cluster_id="cluster-north",
            engine=engine,
            grid_row=row,
            grid_col=col,
        )
        inventory.register(sensor, row=row, col=col)
    
    print(f"Inventory: {inventory.size} sensors, coverage={inventory.coverage_ratio():.0%}")
    
    # ── Stage 2: Publisher ──────────────────────────────────────
    publisher = SensorPublisher(
        inventory=inventory,
        queue=queue,
        engine=engine,
        tick_interval_seconds=0.1,  # Fast for demo
    )
    
    # ── Stage 3: Consumer + Agent ───────────────────────────────
    # Use stub mode for fast testing, or pass llm=ChatOpenAI(...) for LLM mode
    cluster_graph = build_cluster_agent_graph()
    
    findings = []
    consumer = EventBridgeConsumer(
        queue=queue,
        agent_graph=cluster_graph,
        batch_size=5,  # Invoke agent every 5 events
        on_finding=lambda f: findings.append(f),
    )
    
    # ── Stage 4: Run the pipeline ───────────────────────────────
    print("\n=== Running pipeline for 20 ticks ===\n")
    
    await publisher.run(ticks=20)
    print(f"Publisher done: {queue.total_enqueued} events enqueued")
    
    await consumer.run(max_events=queue.total_enqueued)
    print(f"Consumer done: {consumer.events_consumed} events consumed")
    print(f"Agent invocations: {consumer.invocations}")
    print(f"Findings: {len(findings)}")
    
    # ── Stage 5: Inspect findings ───────────────────────────────
    print("\n=== Findings ===\n")
    for i, f in enumerate(findings, 1):
        print(f"{i}. [{f['anomaly_type']}] conf={f['confidence']:.2f}")
        print(f"   Cluster: {f['cluster_id']}")
        print(f"   Affected sensors: {f['affected_sensors']}")
        print(f"   Summary: {f['summary'][:80]}")
        print()

asyncio.run(main())
```

**Expected output (stub mode):**

```
Inventory: 8 sensors, coverage=8%

=== Running pipeline for 20 ticks ===

Publisher done: 160 events enqueued
Consumer done: 160 events consumed
Agent invocations: 32
Findings: 32

=== Findings ===

1. [stub_placeholder] conf=0.50
   Cluster: cluster-north
   Affected sensors: ['smoke-7-7']
   Summary: [STUB] classify node not yet implemented for cluster cluster-north

2. [stub_placeholder] conf=0.50
   Cluster: cluster-north
   Affected sensors: ['temp-7-7']
   Summary: [STUB] classify node not yet implemented for cluster cluster-north

...
```

8 sensors × 20 ticks = 160 events. Batch size 5 → 32 invocations (160 / 5). Each invocation produces one stub finding.

---

## Running with LLM mode

To use the LLM-powered agent instead of the stub:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
cluster_graph = build_cluster_agent_graph(llm=llm)
```

Now the findings will come from actual LLM reasoning:

```
1. [threshold_breach] conf=0.85
   Cluster: cluster-north
   Affected sensors: ['temp-7-2', 'smoke-7-7']
   Summary: Temperature spike at (7,2) correlated with smoke detection at (7,7), indicating...

2. [correlated_event] conf=0.75
   Cluster: cluster-north
   Affected sensors: ['temp-2-2', 'temp-5-5', 'smoke-5-5']
   Summary: Multiple temperature sensors showing elevated readings with smoke confirmation...
```

The LLM calls tools to inspect the data, reasons about correlations, and produces findings with meaningful classifications and confidence scores.

---

## Observability: LangSmith tracing

LangSmith is LangChain's observability platform. It traces every LLM call, tool call, and graph invocation. To enable it:

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=your_langsmith_api_key
export LANGCHAIN_PROJECT=wildfire-agent-demo
```

Run the pipeline. Then open https://smith.langchain.com and navigate to your project. You'll see:

- **Traces** — one per agent invocation
- **Runs** — nested view showing LLM calls, tool calls, node executions
- **Latency** — how long each step took
- **Token usage** — input/output tokens per LLM call
- **Errors** — any exceptions that occurred

Click into a trace to see the full conversation:
1. System message (classify prompt)
2. User message (sensor data summary)
3. AI message with tool_calls
4. Tool messages with results
5. AI message with final JSON response

This is invaluable for debugging. If the agent produces a bad finding, you can see exactly what tools it called, what data it saw, and what it reasoned.

---

## Observability: Stream mode

LangGraph supports multiple stream modes. The default is `stream_mode="values"`, which yields the full state after each node. For debugging, use `stream_mode="updates"`:

```python
# Instead of:
result = graph.invoke(state)

# Use:
for chunk in graph.stream(state, stream_mode="updates"):
    node_name = list(chunk.keys())[0]
    state_update = chunk[node_name]
    print(f"Node: {node_name}")
    print(f"  Updated fields: {list(state_update.keys())}")
    print(f"  Status: {state_update.get('status', 'N/A')}")
    print()
```

This shows you which node ran and what fields it changed:

```
Node: ingest_events
  Updated fields: ['status', 'error_message']
  Status: processing

Node: classify
  Updated fields: ['messages']
  Status: processing

Node: tool_node
  Updated fields: ['messages']
  Status: processing

Node: classify
  Updated fields: ['messages']
  Status: processing

Node: parse_findings
  Updated fields: ['anomalies', 'status']
  Status: complete

Node: report_findings
  Updated fields: []
  Status: complete
```

You can see the ReAct loop: classify → tool_node → classify → parse_findings. Each iteration adds messages to the state.

---

## Async orchestration patterns

The publisher and consumer run as separate async tasks. You can run them in parallel:

```python
async def main():
    # Setup (engine, sensors, queue, publisher, consumer)
    ...
    
    # Run publisher and consumer in parallel
    publisher_task = asyncio.create_task(publisher.run(ticks=20))
    consumer_task = asyncio.create_task(consumer.run())
    
    # Wait for publisher to finish
    await publisher_task
    
    # Stop consumer after all events are processed
    await queue.join()  # Wait for queue to be empty
    consumer.stop()
    await consumer_task
```

This is more realistic: the publisher produces events continuously, and the consumer processes them as they arrive. The queue buffers events between them.

**Back-pressure:** If you set `queue = SensorEventQueue(maxsize=50)`, the queue will block the publisher when it's full. This prevents unbounded memory growth if the consumer can't keep up.

---

## What you learned: Pipeline integration

This session introduced the end-to-end integration patterns:

**1. Async orchestration** — publisher and consumer run as separate async tasks, coordinated by the queue.

**2. State construction** — the consumer builds the initial LangGraph state from batched events. The agent never sees raw `SensorEvent` objects — it only sees the state dict.

**3. Callback pattern** — the consumer calls `on_finding(finding)` for each finding. This is how findings flow out of the agent layer back to the application layer.

**4. LangSmith tracing** — environment variables enable automatic tracing of all LLM calls and graph invocations.

**5. Stream mode** — `graph.stream(state, stream_mode="updates")` shows intermediate state changes for debugging.

**6. Batching trade-offs** — batch size controls latency vs. context. Small batches (1–3) give fast response but less correlation. Large batches (10–20) give better correlation but higher latency.

The pipeline is complete. World physics → sensor observations → async transport → agent reasoning → findings. Every piece works together.

---

## Checkpoint

Run the pipeline script and verify the output matches the expected output above.

For stub mode (no API key needed):
```bash
python -c "
import asyncio
from domains.wildfire.scenarios import create_basic_wildfire
from sensors.publisher import SensorPublisher
from transport.queue import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph
# ... (the full pipeline script from this session)
"
```

You should see events enqueued, agent invocations, and findings collected. If anything errors, check that your virtual environment is active and `pytest tests/ -q` passes first.

---

## Key files

- `src/sensors/publisher.py` — `SensorPublisher`: async tick loop, drives sensors, enqueues events
- `src/bridge/consumer.py` — `EventBridgeConsumer`: async read loop, batches events, invokes agent, collects findings
- `src/agents/cluster/graph.py` — `build_cluster_agent_graph()`: compiles the cluster agent (stub or LLM mode)

---

*Next: Session 5 adds the supervisor agent. Until now, each cluster agent works independently. The supervisor correlates findings across all clusters, assesses the overall situation, and decides on actions. This is where the multi-agent architecture comes together — cluster agents report upward, the supervisor aggregates and reasons globally.*
