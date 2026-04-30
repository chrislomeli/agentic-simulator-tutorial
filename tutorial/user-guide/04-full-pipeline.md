# Tutorial Part 4: The Full Pipeline

## The Complete Data Flow

Now we'll wire everything together: **World Engine → Sensors → Queue → Agents → Actuators**.

```
┌─────────────────────────────────────────────────────────────────┐
│  1. WORLD ENGINE                                                │
│  Simulates wildfire spread, weather, terrain                   │
│  • Ticks every N seconds                                        │
│  • Updates fire state, weather conditions                       │
│  • Records ground truth snapshots                               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. SENSORS                                                     │
│  Sample the world and produce noisy readings                    │
│  • TemperatureSensor, SmokeSensor, WindSensor, etc.             │
│  • Add Gaussian noise to readings                               │
│  • Emit SensorEvent envelopes                                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. SENSOR PUBLISHER                                            │
│  Async loop that ticks all sensors                              │
│  • Calls sensor.emit() for each sensor                          │
│  • Puts SensorEvents onto the queue                             │
│  • Optionally auto-ticks the world engine                       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. SENSOR EVENT QUEUE                                          │
│  Async FIFO queue (asyncio.Queue wrapper)                       │
│  • Buffers events between publisher and consumer                │
│  • In production: replace with Kafka topics                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. EVENT BRIDGE CONSUMER                                       │
│  Routes events to cluster agents                                │
│  • Reads events from queue                                      │
│  • Groups by cluster_id                                         │
│  • Invokes cluster agent graph per batch                        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  6. CLUSTER AGENTS (parallel)                                   │
│  Analyze sensor data, detect anomalies                          │
│  • LLM + tools (or deterministic stub)                          │
│  • Produce AnomalyFindings                                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  7. SUPERVISOR AGENT                                            │
│  Correlates findings across clusters                            │
│  • Assesses the overall situation                               │
│  • Queries resource readiness (if ResourceInventory provided)   │
│  • Decides what actions to take                                 │
│  • Issues ActuatorCommands                                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  8. ACTUATORS (future)                                          │
│  Execute commands (alerts, notifications, drone tasks, etc.)    │
│  • Send Slack/PagerDuty notifications                           │
│  • Dispatch emergency responders                                │
│  • Deploy drones for closer inspection                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Building the Pipeline: Step by Step

### Step 1: Create the World

```python
import random
from domains.wildfire import create_basic_wildfire

# Set seed for reproducibility
random.seed(42)

# Create a pre-configured world with fire ignition
engine = create_basic_wildfire()

print(f"World: {engine.grid.rows}×{engine.grid.cols} grid")
print(f"Fire ignition at (7, 2)")
print(f"Weather: {engine.environment.temperature_c}°C, {engine.environment.humidity_pct}% humidity")
```

**Output:**
```
World: 10×10 grid
Fire ignition at (7, 2)
Weather: 38°C, 12% humidity
```

---

### Step 2: Create Sensors

```python
from domains.wildfire.sensors import (
   TemperatureSensor,
   SmokeSensor,
   WindSensor,
   HumiditySensor,
)

CLUSTER_ID = "cluster-north"

sensors = [
   # Temperature sensors at different grid positions
   TemperatureSensor(
      source_id="temp-A1",
      cluster_id=CLUSTER_ID,
      engine=engine,
      grid_row=3,
      grid_col=3,
      noise_std=0.5,
   ),
   TemperatureSensor(
      source_id="temp-B2",
      cluster_id=CLUSTER_ID,
      engine=engine,
      grid_row=7,
      grid_col=2,
      noise_std=0.5,
   ),

   # Smoke sensor near expected fire path
   SmokeSensor(
      source_id="smoke-A1",
      cluster_id=CLUSTER_ID,
      engine=engine,
      grid_row=5,
      grid_col=3,
      noise_std=1.0,
   ),

   # Weather sensors (no grid position — global readings)
   HumiditySensor(
      source_id="hum-A1",
      cluster_id=CLUSTER_ID,
      engine=engine,
      noise_std=0.5,
   ),
   WindSensor(
      source_id="wind-A1",
      cluster_id=CLUSTER_ID,
      engine=engine,
   ),
]

print(f"Created {len(sensors)} sensors: {[s.source_id for s in sensors]}")
```

**Output:**
```
Created 5 sensors: ['temp-A1', 'temp-B2', 'smoke-A1', 'hum-A1', 'wind-A1']
```

---

### Step 3: Create the Event Queue

```python
from transport import SensorEventQueue

# Create an async queue with max size 200
queue = SensorEventQueue(maxsize=200)

print(f"Queue created: max size {queue.maxsize}")
```

---

### Step 4: Create the Sensor Publisher

```python
from sensors import SensorPublisher

publisher = SensorPublisher(
   sensors=sensors,
   queue=queue,
   tick_interval_seconds=0.1,  # Tick every 100ms (fast for demo)
   engine=engine,  # Auto-tick the world
)

print("Publisher created (will auto-tick the world)")
```

**Key parameter:** `engine=engine` means the publisher will call `engine.tick()` before each sensor pass. This keeps the world and sensors synchronized.

---

### Step 5: Create the Cluster Agent Graph

```python
from agents.cluster.graph import build_cluster_agent_graph

# Stub mode (no LLM)
cluster_graph = build_cluster_agent_graph()

print("Cluster agent graph built (stub mode)")
```

**For LLM mode:**
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
cluster_graph = build_cluster_agent_graph(llm=llm)

print("Cluster agent graph built (LLM mode)")
```

---

### Step 6: Create the Event Bridge Consumer

```python
from bridge.consumer import EventBridgeConsumer

# Track findings
findings_log = []


def on_finding(finding):
   """Callback invoked for each AnomalyFinding."""
   findings_log.append(finding)
   print(f"🔥 FINDING: {finding['summary'][:80]}")


consumer = EventBridgeConsumer(
   queue=queue,
   agent_graph=cluster_graph,
   on_finding=on_finding,
   batch_size=5,  # Invoke agent every 5 events per cluster
)

print("Consumer created (batch_size=5)")
```

**What `batch_size` does:**
- `batch_size=1`: Invoke the agent for every single event (real-time)
- `batch_size=5`: Accumulate 5 events, then invoke the agent (more efficient)
- `batch_size=10`: Wait for 10 events before invoking

---

### Step 7: Run the Pipeline

```python
import asyncio

async def run_pipeline():
    NUM_TICKS = 15
    
    print("=" * 60)
    print(f"Starting pipeline: {NUM_TICKS} ticks")
    print("=" * 60)
    
    # 1. Run the publisher (produces events)
    await publisher.run(ticks=NUM_TICKS)
    print(f"Publisher done: {publisher.ticks_completed} ticks, {queue.total_enqueued} events")
    
    # 2. Consume all queued events
    await consumer.run(max_events=queue.total_enqueued)
    
    # 3. Print summary
    print("=" * 60)
    print("Pipeline complete")
    print(f"  Engine ticks:    {engine.current_tick}")
    print(f"  Events produced: {queue.total_enqueued}")
    print(f"  Events consumed: {consumer.events_consumed}")
    print(f"  Agent calls:     {consumer.invocations}")
    print(f"  Findings:        {len(findings_log)}")
    print("=" * 60)
    
    # 4. Print findings
    for f in findings_log:
        print(f"  - {f['anomaly_type']}: {f['summary']}")

# Run it
asyncio.run(run_pipeline())
```

**Output:**
```
============================================================
Starting pipeline: 15 ticks
============================================================
Publisher done: 15 ticks, 75 events
🔥 FINDING: Two temperature sensors spiking above 40°C. Likely fire.
🔥 FINDING: Smoke density increased to 245 ppm near fire location.
============================================================
Pipeline complete
  Engine ticks:    15
  Events produced: 75
  Events consumed: 75
  Agent calls:     15
  Findings:        2
============================================================
  - threshold_breach: Two temperature sensors spiking above 40°C. Likely fire.
  - correlated_event: Smoke density increased to 245 ppm near fire location.
```

---

## Complete Example: Full Pipeline Script

Here's the full script you can run:

```python
#!/usr/bin/env python3
"""
Full pipeline demo: World → Sensors → Queue → Agents → Findings
"""

import asyncio
import random
from world import create_basic_wildfire
from sensors import (
   TemperatureSensor,
   SmokeSensor,
   WindSensor,
   HumiditySensor,
)
from sensors import SensorPublisher
from transport import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph


async def main():
   # Set seed for reproducibility
   random.seed(42)

   # 1. Create the world
   engine = create_basic_wildfire()
   print(f"World: {engine.grid.rows}×{engine.grid.cols} grid, fire at (7,2)")
   print(f"Weather: {engine.environment.temperature_c}°C, {engine.environment.humidity_pct}% humidity")

   # 2. Create sensors
   CLUSTER_ID = "cluster-north"
   sensors = [
      TemperatureSensor(
         source_id="temp-A1",
         cluster_id=CLUSTER_ID,
         engine=engine,
         grid_row=3, grid_col=3,
         noise_std=0.5,
      ),
      TemperatureSensor(
         source_id="temp-B2",
         cluster_id=CLUSTER_ID,
         engine=engine,
         grid_row=7, grid_col=2,
         noise_std=0.5,
      ),
      SmokeSensor(
         source_id="smoke-A1",
         cluster_id=CLUSTER_ID,
         engine=engine,
         grid_row=5, grid_col=3,
         noise_std=1.0,
      ),
      HumiditySensor(
         source_id="hum-A1",
         cluster_id=CLUSTER_ID,
         engine=engine,
         noise_std=0.5,
      ),
      WindSensor(
         source_id="wind-A1",
         cluster_id=CLUSTER_ID,
         engine=engine,
      ),
   ]
   print(f"Sensors: {[s.source_id for s in sensors]}")

   # 3. Create queue
   queue = SensorEventQueue(maxsize=200)

   # 4. Create publisher (auto-ticks the world)
   publisher = SensorPublisher(
      sensors=sensors,
      queue=queue,
      tick_interval_seconds=0.0,  # As fast as possible
      engine=engine,
   )

   # 5. Create cluster agent graph
   cluster_graph = build_cluster_agent_graph()

   # 6. Create consumer
   findings_log = []

   def on_finding(finding):
      findings_log.append(finding)
      print(f"🔥 {finding['anomaly_type']}: {finding['summary'][:60]}")

   consumer = EventBridgeConsumer(
      queue=queue,
      agent_graph=cluster_graph,
      on_finding=on_finding,
      batch_size=5,
   )

   # 7. Run the pipeline
   NUM_TICKS = 15
   print("=" * 60)
   print(f"Running pipeline: {NUM_TICKS} ticks")
   print("=" * 60)

   await publisher.run(ticks=NUM_TICKS)
   await consumer.run(max_events=queue.total_enqueued)

   # 8. Summary
   print("=" * 60)
   print("Pipeline complete")
   print(f"  Ticks:    {engine.current_tick}")
   print(f"  Events:   {queue.total_enqueued}")
   print(f"  Findings: {len(findings_log)}")
   print("=" * 60)

   # 9. Ground truth vs findings
   snap = engine.history[-1]
   print(f"\nGround truth: {snap.domain_summary['burning_cells']} cells burning")
   print(f"Agent detected: {len(findings_log)} anomalies")


if __name__ == "__main__":
   asyncio.run(main())
```

**Save as `my_pipeline.py` and run:**
```bash
python my_pipeline.py
```

---

## Adding the Supervisor Agent

To add cross-cluster correlation, wire in the supervisor:

```python
from agents.supervisor.graph import build_supervisor_graph

# Build supervisor graph (stub mode)
supervisor_graph = build_supervisor_graph()

# After cluster agents finish, invoke supervisor
supervisor_result = supervisor_graph.invoke({
   "active_cluster_ids": ["cluster-north", "cluster-south"],
   "cluster_findings": findings_log,  # All findings from cluster agents
   "messages": [],
   "pending_commands": [],
   "situation_summary": None,
   "status": "idle",
})

# Check what commands the supervisor issued
commands = supervisor_result["pending_commands"]
print(f"\nSupervisor issued {len(commands)} commands:")
for cmd in commands:
   print(f"  - {cmd.command_type}: {cmd.payload}")
```

**Example output:**
```
Supervisor issued 2 commands:
  - notify: {'channel': 'slack', 'message': 'Fire detected in cluster-north', 'urgency': 'high'}
  - alert: {'message': 'Two clusters reporting correlated fire events', 'recipients': ['ops-team']}
```

---

## Multi-Cluster Setup

To simulate multiple clusters, create sensors for each cluster:

```python
# Cluster North sensors
sensors_north = [
    TemperatureSensor(
        source_id="temp-north-1",
        cluster_id="cluster-north",
        engine=engine,
        grid_row=2, grid_col=3,
    ),
    # ... more sensors
]

# Cluster South sensors
sensors_south = [
    TemperatureSensor(
        source_id="temp-south-1",
        cluster_id="cluster-south",
        engine=engine,
        grid_row=8, grid_col=7,
    ),
    # ... more sensors
]

# Combine all sensors
all_sensors = sensors_north + sensors_south

# Publisher handles all sensors
publisher = SensorPublisher(
    sensors=all_sensors,
    queue=queue,
    engine=engine,
)

# Consumer routes events by cluster_id
consumer = EventBridgeConsumer(
    queue=queue,
    agent_graph=cluster_graph,
    on_finding=on_finding,
)
```

**What happens:**
1. Publisher emits events from all sensors
2. Consumer groups events by `cluster_id`
3. Each cluster agent runs independently
4. Supervisor correlates findings across clusters

---

## Async Execution Model

The pipeline uses **asyncio** for concurrency:

```python
async def run_pipeline():
    # Start consumer in background
    consumer_task = asyncio.create_task(consumer.run())
    
    # Run publisher in foreground
    await publisher.run(ticks=60)
    
    # Stop consumer
    consumer.stop()
    await consumer_task
```

**Why async?**
- **Publisher** can tick sensors without blocking
- **Consumer** can invoke agents while publisher is still running
- **Agents** can make LLM calls (I/O-bound) without blocking other agents

In production, replace `SensorEventQueue` with Kafka for true distributed processing.

---

## Comparing Ground Truth vs. Agent Findings

After the pipeline runs, compare what the agent detected vs. what actually happened:

```python
# Ground truth
from domains.wildfire import FireState

snapshot = engine.history[-1]  # Last tick
burning_cells = [
   (r, c) for r in range(engine.grid.rows)
   for c in range(engine.grid.cols)
   if engine.grid.get_cell(r, c).cell_state.fire_state == FireState.BURNING
]

print(f"Ground truth: {len(burning_cells)} cells burning")
print(f"Burning cells: {burning_cells}")

# Agent findings
print(f"\nAgent detected: {len(findings_log)} anomalies")
for f in findings_log:
   print(f"  - {f['cluster_id']}: {f['summary']}")
   print(f"    Affected sensors: {f['affected_sensors']}")
   print(f"    Confidence: {f['confidence']}")
```

**Example output:**
```
Ground truth: 4 cells burning
Burning cells: [(6, 2), (7, 2), (7, 3), (8, 2)]

Agent detected: 2 anomalies
  - cluster-north: Two temperature sensors spiking above 40°C. Likely fire.
    Affected sensors: ['temp-A1', 'temp-B2']
    Confidence: 0.85
  - cluster-north: Smoke density increased to 245 ppm near fire location.
    Affected sensors: ['smoke-A1']
    Confidence: 0.78
```

**Analysis:**
- Ground truth: 4 cells burning
- Agent detected: 2 anomalies (temperature spike + smoke)
- The agent correctly identified the fire, but didn't know the exact cell count (it only sees sensor readings, not the grid)

---

## Production Considerations

### 1. Replace Queue with Kafka

```python
# Instead of SensorEventQueue
from kafka import KafkaProducer, KafkaConsumer

producer = KafkaProducer(bootstrap_servers=['localhost:9092'])
consumer = KafkaConsumer('sensor.events', bootstrap_servers=['localhost:9092'])
```

### 2. Add Checkpointing

```python
from langgraph.checkpoint.memory import MemorySaver

# Add memory to cluster agent
memory = MemorySaver()
cluster_graph = build_cluster_agent_graph(checkpointer=memory)

# Invoke with thread_id for persistence
result = cluster_graph.invoke(
    state,
    config={"configurable": {"thread_id": "cluster-north"}}
)
```

### 3. Add Observability

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s  %(message)s",
)

# LangSmith tracing
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "your-key"
```

### 4. Add Error Handling

```python
try:
    result = cluster_graph.invoke(state)
except Exception as e:
    logger.error(f"Agent invocation failed: {e}")
    # Send to dead-letter queue, retry, or alert
```

---

## Next Steps

You now have a complete understanding of the pipeline! Here's what to explore next:

1. **Run the examples:**
   - `examples/pipeline_demo.py` — Full pipeline with stub agents
   - Try modifying sensor positions, noise levels, failure modes

2. **Add LLM mode:**
   - Get an OpenAI API key
   - Replace `build_cluster_agent_graph()` with `build_cluster_agent_graph(llm=llm)`
   - Compare stub vs. LLM performance

3. **Add resources for preparedness assessment:**
   - Use `create_full_wildfire_scenario()` to get engine + resources
   - Pass `resource_inventory=resources` to `build_supervisor_graph()`
   - The supervisor LLM can now query firetrucks, ambulances, hospitals, and helicopters
   - Use `resources.reduce_resources()` or `resources.disable_resources()` to test resilience

4. **Build evaluation scenarios:**
   - Create multiple fire scenarios
   - Run agents on each scenario
   - Measure detection accuracy, false positives, latency

5. **Implement actuators:**
   - Build Slack/PagerDuty integrations
   - Create drone task dispatcher
   - Add alert routing logic

6. **Scale to multiple clusters:**
   - Create 3-5 clusters with different sensor coverage
   - Test cross-cluster correlation
   - Measure supervisor decision quality

---

## Quick Reference

### Full pipeline template

```python
import asyncio
import random
from domains.wildfire import create_basic_wildfire
from domains.wildfire.sensors import TemperatureSensor, SmokeSensor
from sensors import SensorPublisher
from transport import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph


async def main():
   random.seed(42)

   # World
   engine = create_basic_wildfire()

   # Sensors
   sensors = [
      TemperatureSensor(source_id="temp-1", cluster_id="cluster-north", engine=engine, grid_row=3, grid_col=3),
      SmokeSensor(source_id="smoke-1", cluster_id="cluster-north", engine=engine, grid_row=5, grid_col=3),
   ]

   # Queue
   queue = SensorEventQueue()

   # Publisher
   publisher = SensorPublisher(sensors=sensors, queue=queue, engine=engine)

   # Agent
   cluster_graph = build_cluster_agent_graph()

   # Consumer
   findings = []
   consumer = EventBridgeConsumer(
      queue=queue,
      agent_graph=cluster_graph,
      on_finding=lambda f: findings.append(f),
   )

   # Run
   await publisher.run(ticks=15)
   await consumer.run(max_events=queue.total_enqueued)

   print(f"Findings: {len(findings)}")


asyncio.run(main())
```

### Run the demo
```bash
python examples/pipeline_demo.py
```

### With LLM
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
cluster_graph = build_cluster_agent_graph(llm=llm)
supervisor_graph = build_supervisor_graph(llm=llm)
```

### With LLM + Resources
```python
from langchain_openai import ChatOpenAI
from domains.wildfire import create_full_wildfire_scenario

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
engine, resources = create_full_wildfire_scenario()

cluster_graph = build_cluster_agent_graph(llm=llm)
supervisor_graph = build_supervisor_graph(llm=llm, resource_inventory=resources)
# Supervisor can now query resource availability during assessment and decision-making
```

### Compare ground truth
```python
# After pipeline runs
ground_truth = engine.history[-1]
agent_findings = findings_log

# Evaluate
print(f"Ground truth: {ground_truth.domain_summary['cell_summary']}")
print(f"Agent detected: {len(agent_findings)} anomalies")
```

---

## Next Tutorial

Now that you understand the full pipeline, the next tutorial covers:
- **Part 5: Resources and Preparedness** — How to add firetrucks, hospitals, and other preparedness assets to your scenarios, and how the supervisor LLM queries them during assessment and decision-making.

---

## Series Summary

You now understand:
- **Part 1:** How the World Engine simulates wildfires
- **Part 2:** How sensors sample the world and produce noisy readings
- **Part 3:** How AI agents analyze sensor data and detect anomalies
- **Part 4:** How to wire everything together into a full pipeline
- **Part 5:** How resources model preparedness and integrate with agent reasoning

**Happy building!** 🔥🤖
