# Session 8: Full Pipeline — Everything Wired

---

## What you're doing and why

Sessions 1–7 built every component: world engine, sensors, transport, cluster agents, supervisor, resources. Each piece works in isolation. This session wires them all together and runs the complete system for the first time.

This is the integration test for the whole tutorial. It proves the interfaces work end-to-end and gives you a baseline you can break in Session 9.

You also add full LangSmith observability here so you can see exactly what the LLM did during each supervisor invocation — which tools it called, what data it saw, why it made the decisions it made.

---

## Setup

This session builds on Sessions 1–7. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/ tests/
pytest tests/ -q   # everything should pass before you start
```

---

## Rubric coverage

| Skill | Level | Where in this session |
|-------|-------|-----------------------|
| Compile + invoke / stream | foundational | Both `.invoke()` (supervisor) and `async .run()` (publisher/consumer) |
| LangSmith tracing | mid-level | `LANGCHAIN_TRACING_V2` enables full pipeline traces |

---

## What you're building

No new source files. This session is integration: running all components together and adding observability configuration.

---

## Why end-to-end integration matters

You've built:
- **World engine** (Sessions 01–02) — simulates fire spread
- **Sensors** (Sessions 03–04) — emit noisy readings
- **Queue and bridge** (Session 05) — route events to agents
- **Cluster agents** (Sessions 06–07) — detect anomalies
- **Full sensor pipeline** (Session 08) — wire sensors to cluster agents
- **Supervisor** (Sessions 09–10) — coordinate across clusters
- **Resources** (Sessions 11–12) — assess preparedness

But you haven't run them all together. This session is the integration test. It proves:
- The interfaces work (sensor events → cluster agents → supervisor)
- The data flows correctly (findings accumulate, resources are queried)
- The system produces useful output (situation summary, commands)
- Observability works (LangSmith traces show what happened)

This is the "it actually works" session.

---

## The complete pipeline

Here's the full data flow:

```
1. World Engine
   ↓ (tick → update grid state)
2. Sensors
   ↓ (emit readings with noise)
3. SensorPublisher
   ↓ (enqueue events)
4. SensorEventQueue
   ↓ (batch events)
5. EventBridgeConsumer
   ↓ (route to cluster agents)
6. Cluster Agents (×N parallel)
   ↓ (detect anomalies → findings)
7. Supervisor Agent
   ↓ (correlate findings, query resources)
8. ActuatorCommands
   ↓ (alerts, escalations, notifications)
9. Ground Truth Snapshots
   (engine.history — what actually happened)
```

Each stage is async-compatible. The sensor pipeline (1-6) runs asynchronously. The supervisor (7-8) runs synchronously after the pipeline completes. Ground truth (9) is captured at every tick for evaluation.

---

## Building the pipeline

Here's the complete setup:

### 1. Create the world and resources

```python
import random
from domains.wildfire import create_full_wildfire_scenario

random.seed(42)  # Reproducible results
engine, resources = create_full_wildfire_scenario()

print(f"Grid: {engine.grid_rows}×{engine.grid_cols}")
print(f"Resources: {resources.size}")
print(f"Initial fire cells: {sum(1 for cell in engine.grid.flatten() if cell.fire_state != FireState.NONE)}")
```

The scenario gives you:
- A 10×10 grid with fire physics
- 8 NWCG-aligned resources across 2 clusters
- Initial fire ignition points

### 2. Create sensors and publisher

```python
from domains.wildfire.sensors import TemperatureSensor, SmokeSensor, HumiditySensor, WindSensor
from sensors import SensorPublisher
from transport import SensorEventQueue

queue = SensorEventQueue()

sensors = [
    # Cluster-north sensors
    TemperatureSensor(
        source_id="temp-n1", cluster_id="cluster-north",
        engine=engine, grid_row=3, grid_col=3,
    ),
    HumiditySensor(
        source_id="humid-n1", cluster_id="cluster-north",
        engine=engine, grid_row=2, grid_col=2,
    ),
    
    # Cluster-south sensors
    SmokeSensor(
        source_id="smoke-s1", cluster_id="cluster-south",
        engine=engine, grid_row=7, grid_col=5,
    ),
    WindSensor(
        source_id="wind-s1", cluster_id="cluster-south",
        engine=engine, grid_row=8, grid_col=8,
    ),
]

publisher = SensorPublisher(sensors=sensors, queue=queue, engine=engine)

print(f"Sensors: {len(sensors)}")
print(f"Clusters: {set(s.cluster_id for s in sensors)}")
```

### 3. Create cluster agent graph

```python
from agents.cluster.graph import build_cluster_agent_graph
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()  # Shared memory for incidents
cluster_graph = build_cluster_agent_graph(store=store)

print(f"Cluster graph compiled: {cluster_graph is not None}")
```

The cluster graph can run in stub or LLM mode. For this example, we'll use stub mode (no API key needed).

### 4. Create consumer with findings callback

```python
from bridge.consumer import EventBridgeConsumer

findings = []  # Accumulator for all findings

def on_finding(finding):
    findings.append(finding)
    print(f"  Finding: [{finding['anomaly_type']}] {finding['cluster_id']} conf={finding['confidence']:.2f}")

consumer = EventBridgeConsumer(
    queue=queue,
    agent_graph=cluster_graph,
    batch_size=5,  # Process 5 events per cluster agent invocation
    on_finding=on_finding,
)

print(f"Consumer ready with batch_size={consumer.batch_size}")
```

### 5. Create supervisor graph with resources

```python
from agents.supervisor.graph import build_supervisor_graph

supervisor_graph = build_supervisor_graph(
    store=store,  # Same store as cluster agents
    resource_inventory=resources,  # Adds resource tools
)

print(f"Supervisor graph compiled with resource tools")
```

---

## Running the pipeline

Here's the complete async main function:

```python
import asyncio

async def main():
    # 1. Run the world engine for 20 ticks
    print("\n=== Running world engine ===")
    await publisher.run(ticks=20)
    
    print(f"\nEngine ran {len(engine.history)} ticks")
    print(f"Events enqueued: {queue.total_enqueued}")
    print(f"Final fire cells: {sum(1 for cell in engine.grid.flatten() if cell.fire_state != FireState.NONE)}")
    
    # 2. Consume all sensor events through cluster agents
    print("\n=== Running cluster agents ===")
    await consumer.run(max_events=queue.total_enqueued)
    
    print(f"\nEvents consumed: {consumer.events_consumed}")
    print(f"Findings produced: {len(findings)}")
    
    # 3. Run supervisor to correlate findings and assess preparedness
    print("\n=== Running supervisor ===")
    result = supervisor_graph.invoke({
        "active_cluster_ids": ["cluster-north", "cluster-south"],
        "cluster_findings": findings,
        "messages": [],
        "pending_commands": [],
        "situation_summary": None,
        "status": "idle",
        "error_message": None,
    })
    
    print(f"\nSupervisor status: {result['status']}")
    print(f"Situation summary:\n  {result['situation_summary']}")
    print(f"Commands issued: {len(result['pending_commands'])}")
    for i, cmd in enumerate(result['pending_commands'], 1):
        print(f"  {i}. [{cmd.command_type}] → {cmd.cluster_id} (priority={cmd.priority})")
    
    # 4. Compare to ground truth
    print("\n=== Ground truth comparison ===")
    final_snapshot = engine.history[-1]
    print(f"Final tick: {final_snapshot.tick}")
    print(f"Fire cells: {final_snapshot.fire_cell_count}")
    print(f"Max intensity: {final_snapshot.max_fire_intensity:.1f}")
    
    # 5. Resource readiness
    print("\n=== Resource readiness ===")
    readiness = resources.readiness_summary()
    for rtype, info in readiness["by_type"].items():
        print(f"  {rtype}: {info['available']}/{info['total']} available, "
              f"{info['available_capacity']:.0f}/{info['total_capacity']:.0f} capacity")

asyncio.run(main())
```

---

## Expected output

**Stub mode (no LLM):**

```
=== Running world engine ===
Engine ran 20 ticks
Events enqueued: 80
Final fire cells: 12

=== Running cluster agents ===
  Finding: [stub_placeholder] cluster-north conf=0.50
  Finding: [stub_placeholder] cluster-south conf=0.50

Events consumed: 80
Findings produced: 2

=== Running supervisor ===
Supervisor status: complete
Situation summary:
  [STUB] Received 2 finding(s) from 2 cluster(s). Store contains 0 past incident(s) across all clusters.
Commands issued: 0

=== Ground truth comparison ===
Final tick: 20
Fire cells: 12
Max intensity: 450.3

=== Resource readiness ===
  crew: 2/2 available, 23/23 capacity
  engine: 2/2 available, 1000/1000 capacity
  dozer: 1/1 available, 60/60 capacity
  ambulance: 1/1 available, 2/2 capacity
  hospital: 1/1 available, 42/50 capacity
  helicopter: 1/1 available, 700/700 capacity
```

The pipeline:
1. Ran 20 ticks → fire spread to 12 cells
2. Emitted 80 sensor events (4 sensors × 20 ticks)
3. Cluster agents produced 2 stub findings (1 per cluster)
4. Supervisor assessed the situation (stub summary)
5. No commands issued (stub findings aren't actionable)
6. All resources remain available

**LLM mode (with ChatOpenAI):**

To run with an LLM, add:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
cluster_graph = build_cluster_agent_graph(llm=llm, store=store)
supervisor_graph = build_supervisor_graph(llm=llm, store=store, resource_inventory=resources)
```

Expected output changes:

```
=== Running cluster agents ===
  Finding: [temperature_threshold_breach] cluster-south conf=0.85
  Finding: [smoke_detection] cluster-south conf=0.90

Findings produced: 2

=== Running supervisor ===
Situation summary:
  Temperature threshold breaches detected in cluster-south (2 sensors, avg confidence 0.85). Smoke also detected in same cluster (confidence 0.90). Resource assessment: cluster-south has adequate fire response capacity (2 engines, 1 dozer, 2 crews all available). Recommend monitoring closely but no immediate action required.

Commands issued: 1
  1. [alert] → cluster-south (priority=3)
     Payload: {'message': 'Fire activity detected, monitor closely', 'recipients': ['ops-team']}
```

The LLM:
1. Detected real anomalies (not stubs)
2. Correlated temperature and smoke in the same cluster
3. Queried resources to assess preparedness
4. Concluded resources are adequate
5. Issued a monitoring alert (conservative, appropriate)

---

## LangSmith observability

To enable LangSmith tracing:

```python
import os

os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "your-api-key"
os.environ["LANGCHAIN_PROJECT"] = "wildfire-pipeline"
```

Then run the pipeline. LangSmith will capture:
- **Cluster agent traces** — one trace per cluster agent invocation (batch of 5 events)
- **Supervisor trace** — one trace for the full assess + decide flow
- **Tool calls** — every `get_resource_summary()`, `check_preparedness()`, etc.
- **LLM calls** — prompts, responses, token counts

In the LangSmith UI, you'll see:

```
Run: supervisor-execution-abc123
  ├─ assess_situation_llm
  │  ├─ LLM call (gpt-4o-mini)
  │  ├─ Tool: get_finding_summary
  │  ├─ Tool: check_cross_cluster
  │  ├─ Tool: get_resource_summary
  │  └─ LLM call (final answer)
  ├─ decide_actions_llm
  │  ├─ LLM call (gpt-4o-mini)
  │  ├─ Tool: check_preparedness (cluster-south)
  │  └─ LLM call (final answer)
  └─ dispatch_commands
```

This is invaluable for debugging: "Why did the supervisor issue this command? What did it see in the findings? What did the resource tools return?"

---

## What you learned: Full pipeline patterns

This session demonstrated end-to-end integration:

**1. Async pipeline stages** — world engine, sensors, publisher, queue, consumer all run asynchronously with proper back-pressure.

**2. Sync supervisor** — the supervisor runs synchronously after the pipeline completes, operating on accumulated findings.

**3. Shared Store** — cluster agents and supervisor share the same `InMemoryStore` for incident history.

**4. Findings accumulation** — the `on_finding` callback collects findings from all cluster agent invocations.

**5. Resource integration** — the supervisor queries `ResourceInventory` during assessment to factor preparedness into decisions.

**6. Ground truth capture** — `engine.history` provides the actual world state for comparison.

**7. LangSmith observability** — full trace visibility into LLM calls, tool usage, and decision flow.

The pipeline is complete. All systems work together. The next sessions will stress-test it.

---

## Checkpoint

Run the complete pipeline script from this session and verify the output matches the expected output above (stub mode).

Key things to verify:
- Events enqueued equals `sensors × ticks`
- Findings are produced (at least 1 per cluster)
- Supervisor status reaches `complete`
- Resource readiness shows all resources available

---

## Key files

- `src/sensors/publisher.py` — `SensorPublisher.run()` async loop
- `src/bridge/consumer.py` — `EventBridgeConsumer.run()` async loop
- `src/agents/cluster/graph.py` — cluster agent graph
- `src/agents/supervisor/graph.py` — supervisor graph

---

*Next: Session 9 uses scenario knobs to degrade sensors and resources, testing how the supervisor's preparedness assessment changes under stress. The question isn't "did it predict correctly?" but "did it identify the right gaps and recommend appropriate responses?"*
