# Tutorial Part 3: AI Agents and Anomaly Detection

## What Are AI Agents?

AI agents are **autonomous decision-makers** that analyze sensor data and detect anomalies (fires, sensor faults, unusual patterns). They use LangGraph to orchestrate LLM reasoning with tool calls.

### The Two-Tier Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Supervisor Agent (top level)                           │
│  • Receives findings from all cluster agents            │
│  • Correlates patterns across clusters                  │
│  • Decides what actions to take (alert, notify, etc.)   │
└─────────────────────────────────────────────────────────┘
                        ↑
        ┌───────────────┼───────────────┐
        │               │               │
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ Cluster Agent │ │ Cluster Agent │ │ Cluster Agent │
│ (cluster-N)   │ │ (cluster-S)   │ │ (cluster-E)   │
│               │ │               │ │               │
│ • Analyzes    │ │ • Analyzes    │ │ • Analyzes    │
│   sensor      │ │   sensor      │ │   sensor      │
│   events      │ │   events      │ │   events      │
│ • Detects     │ │ • Detects     │ │ • Detects     │
│   anomalies   │ │   anomalies   │ │   anomalies   │
│ • Reports     │ │ • Reports     │ │ • Reports     │
│   findings    │ │   findings    │ │   findings    │
└───────────────┘ └───────────────┘ └───────────────┘
        ↑               ↑               ↑
    SensorEvents    SensorEvents    SensorEvents
```

**Why two tiers?**
- **Cluster agents** are specialists — they know their local sensors intimately
- **Supervisor agent** is a generalist — it sees the big picture across all clusters
- This mirrors real incident command structures (local teams + central coordinator)

---

## Cluster Agents: Local Anomaly Detection

### What They Do

Each cluster agent:
1. **Ingests** sensor events from its cluster
2. **Analyzes** the events using an LLM + tools
3. **Detects** anomalies (fires, sensor faults, correlated events)
4. **Reports** findings upward to the supervisor

### The LangGraph Topology

**Stub mode** (no LLM — deterministic):
```
START → ingest_events → classify_stub → report_findings → END
```

**LLM mode** (with ReAct tool loop):
```
START → ingest_events → classify_llm ──→ report_findings → END
                              ↓    ↑
                         tool_node ┘
                         (ReAct loop)
```

The LLM can call tools to inspect sensor data before deciding whether there's an anomaly.

---

### Cluster Agent State

The `ClusterAgentState` tracks everything the agent needs:

```python
class ClusterAgentState(TypedDict):
    cluster_id: str                        # "cluster-north"
    trigger_event: Optional[SensorEvent]   # The event that triggered this run
    sensor_events: List[SensorEvent]       # Rolling window (last 50 events)
    messages: List[BaseMessage]            # LLM conversation history
    anomalies: List[AnomalyFinding]        # Detected anomalies
    status: Literal["idle", "processing", "complete", "error"]
```

**Key fields:**
- **`sensor_events`**: Accumulates events using a custom reducer (append-only, capped at 50)
- **`messages`**: LLM tool loop conversation (uses `add_messages` reducer)
- **`anomalies`**: Structured findings to report to the supervisor

---

### The Four Tools

Cluster agents have access to 4 tools (defined in `sensor_tools.py`):

#### 1. **`get_recent_readings`** — View raw sensor events
```python
get_recent_readings(limit=10, source_type="temperature")
# Returns the last 10 temperature readings
```

#### 2. **`get_sensor_summary`** — Aggregate stats per sensor type
```python
get_sensor_summary(source_type="temperature")
# Returns: {
#   "count": 15,
#   "avg_celsius": 38.4,
#   "min_celsius": 34.2,
#   "max_celsius": 45.1
# }
```

#### 3. **`check_threshold`** — Test readings against thresholds
```python
check_threshold(source_type="temperature", field="celsius", threshold=40.0)
# Returns: {
#   "breaches": [
#     {"source_id": "temp-001", "value": 43.2, "tick": 15},
#     {"source_id": "temp-002", "value": 45.1, "tick": 16}
#   ],
#   "breach_count": 2
# }
```

#### 4. **`get_cluster_status`** — Cluster metadata
```python
get_cluster_status()
# Returns: {
#   "cluster_id": "cluster-north",
#   "event_count": 48,
#   "sensor_types": ["temperature", "smoke", "wind"]
# }
```

**How the LLM uses these:**
```
User: Analyze the sensor events for anomalies.

LLM: Let me check the temperature readings first.
     [calls get_sensor_summary(source_type="temperature")]
     
     The average is 38.4°C, max is 45.1°C. That's unusually high.
     Let me check for threshold breaches.
     [calls check_threshold(source_type="temperature", field="celsius", threshold=40.0)]
     
     Two sensors breached 40°C. Let me see the raw events.
     [calls get_recent_readings(limit=5, source_type="temperature")]
     
     Sensors temp-001 and temp-002 are both spiking. They're adjacent on the grid.
     This looks like a fire.
     
     Response: {
       "anomaly_detected": true,
       "anomaly_type": "threshold_breach",
       "affected_sensors": ["temp-001", "temp-002"],
       "confidence": 0.85,
       "summary": "Two adjacent temperature sensors spiking above 40°C. Likely fire."
     }
```

---

### The System Prompt

The cluster agent LLM is given this system prompt:

```
You are a wildfire monitoring analyst for sensor cluster "cluster-north".

You have been given a batch of sensor readings from your cluster.
Your job is to determine whether the readings indicate a real anomaly
(fire, sensor fault, sudden weather change) or normal conditions.

Use the available tools to inspect the data:
  - get_recent_readings: see the raw sensor events
  - get_sensor_summary: get aggregate stats per sensor type
  - check_threshold: test specific readings against thresholds
  - get_cluster_status: see cluster metadata

After your analysis, respond with a JSON object (and nothing else):
{
  "anomaly_detected": true/false,
  "anomaly_type": "threshold_breach" | "sensor_fault" | "correlated_event" | "none",
  "affected_sensors": ["sensor-id-1", ...],
  "confidence": 0.0 to 1.0,
  "summary": "Brief explanation of what you found"
}
```

This prompt guides the LLM to:
1. Use tools to gather evidence
2. Reason about what the data means
3. Return structured JSON (not prose)

---

### AnomalyFinding: The Output Format

When the cluster agent detects an anomaly, it creates an `AnomalyFinding`:

```python
class AnomalyFinding(TypedDict):
    finding_id: str              # UUID
    cluster_id: str              # "cluster-north"
    anomaly_type: str            # "threshold_breach", "sensor_fault", etc.
    affected_sensors: List[str]  # ["temp-001", "temp-002"]
    confidence: float            # 0.0–1.0
    summary: str                 # Human-readable explanation
    raw_context: dict            # Supporting data (readings, thresholds, etc.)
```

**Example:**
```python
{
    "finding_id": "f123e456-...",
    "cluster_id": "cluster-north",
    "anomaly_type": "threshold_breach",
    "affected_sensors": ["temp-001", "temp-002"],
    "confidence": 0.85,
    "summary": "Two adjacent temperature sensors spiking above 40°C. Likely fire.",
    "raw_context": {
        "max_temp": 45.1,
        "breach_count": 2,
        "tick": 15
    }
}
```

This structured format lets the supervisor agent aggregate and correlate findings across clusters.

---

### Example: Running a Cluster Agent

```python
from agents.cluster.graph import build_cluster_agent_graph
from transport import SensorEvent
from datetime import datetime, timezone

# Build the graph (stub mode)
graph = build_cluster_agent_graph()

# Create a fake sensor event
event = SensorEvent(
    event_id="evt-001",
    source_id="temp-001",
    source_type="temperature",
    cluster_id="cluster-north",
    timestamp=datetime.now(timezone.utc),
    sim_tick=15,
    confidence=0.95,
    payload={"celsius": 43.2},
    metadata={}
)

# Invoke the graph
result = graph.invoke({
    "cluster_id": "cluster-north",
    "trigger_event": event,
    "sensor_events": [event],
    "messages": [],
    "anomalies": [],
    "status": "idle"
})

# Check for anomalies
print(result["anomalies"])
# → [AnomalyFinding(...)]
```

**With an LLM:**
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
graph = build_cluster_agent_graph(llm=llm)

# Same invocation as above
result = graph.invoke({...})

# The LLM will use tools to analyze the event
# and return a structured finding
```

---

## Supervisor Agent: Cross-Cluster Correlation

### What It Does

The supervisor agent:
1. **Receives findings** from all cluster agents (via Send API fan-out)
2. **Assesses the situation** — correlates patterns across clusters
3. **Decides actions** — what commands to issue (alert, notify, escalate, etc.)
4. **Dispatches commands** to actuators

### The LangGraph Topology

**Stub mode:**
```
START → fan_out_to_clusters → run_cluster_agent (×N clusters)
      → assess_situation → decide_actions → dispatch_commands → END
```

**LLM mode:**
```
START → fan_out_to_clusters → run_cluster_agent (×N clusters)
      → assess_situation_llm ──→ parse_assessment
              ↓    ↑                    ↓
         assess_tool_node         decide_actions_llm ──→ parse_commands
                                       ↓    ↑                  ↓
                                  decide_tool_node      dispatch_commands → END
```

Two separate ReAct loops:
1. **Assess loop** — correlate findings, query resource readiness, produce situation summary
2. **Decide loop** — choose actuator commands based on assessment and available resources

---

### Supervisor State

```python
class SupervisorState(TypedDict):
    active_cluster_ids: List[str]              # ["cluster-north", "cluster-south"]
    cluster_findings: List[AnomalyFinding]     # Aggregated from cluster agents
    messages: List[BaseMessage]                # LLM conversation
    pending_commands: List[ActuatorCommand]    # Commands to dispatch
    situation_summary: Optional[str]           # Human-readable assessment
    status: Literal["idle", "aggregating", "assessing", "deciding", "dispatching", "complete", "error"]
```

**Key pattern:** The `cluster_findings` field uses a custom reducer that **appends** findings from cluster agents without overwriting.

---

### Supervisor Tools

Supervisor agents have access to 4 core tools (defined in `supervisor_tools.py`), plus 4 resource tools when a `ResourceInventory` is provided:

#### 1. **`get_all_findings`** — View all findings
```python
get_all_findings(limit=20)
# Returns up to 20 findings from all clusters
```

#### 2. **`get_findings_by_cluster`** — Filter by cluster
```python
get_findings_by_cluster(cluster_id="cluster-north")
# Returns only findings from cluster-north
```

#### 3. **`get_finding_summary`** — Aggregate stats
```python
get_finding_summary()
# Returns: {
#   "total_findings": 3,
#   "by_cluster": {"cluster-north": 2, "cluster-south": 1},
#   "by_type": {"threshold_breach": 2, "sensor_fault": 1}
# }
```

#### 4. **`check_cross_cluster`** — Detect correlations
```python
check_cross_cluster(anomaly_type="threshold_breach")
# Returns: {
#   "correlated": true,
#   "clusters": ["cluster-north", "cluster-south"],
#   "finding_count": 2,
#   "summary": "Same anomaly type detected in 2 clusters"
# }
```

### Resource Tools (when ResourceInventory is provided)

These tools are defined in `resource_tools.py` and added to the supervisor's tool set when `build_supervisor_graph(resource_inventory=inventory)` is called.

#### 5. **`get_resource_summary`** — Overall readiness
```python
get_resource_summary()
# Returns: {
#   "total_resources": 5,
#   "by_type": {"firetruck": {"total": 2, "available": 2, ...}, ...},
#   "by_cluster": {"cluster-south": 4, "cluster-north": 1},
#   "by_status": {"AVAILABLE": 5}
# }
```

#### 6. **`get_resources_by_cluster`** — What's available near a cluster
```python
get_resources_by_cluster(cluster_id="cluster-south")
# Returns list of resource summaries for that cluster
```

#### 7. **`get_resources_by_type`** — All resources of a specific type
```python
get_resources_by_type(resource_type="firetruck")
# Returns list of all firetruck summaries with status and capacity
```

#### 8. **`check_preparedness`** — Is a cluster adequately covered?
```python
check_preparedness(cluster_id="cluster-south")
# Returns: {
#   "cluster_id": "cluster-south",
#   "total_resources": 4,
#   "available_resources": 4,
#   "resource_types_present": ["firetruck", "ambulance", "hospital"],
#   "total_capacity": 1052.0,
#   "gaps": []
# }
```

---

### Actuator Commands: The Output

The supervisor decides what actions to take by issuing **ActuatorCommands**:

```python
class ActuatorCommand:
    command_id: str          # UUID
    command_type: str        # "alert", "notify", "escalate", "suppress", "drone_task"
    source_agent: str        # "supervisor"
    cluster_id: str          # Target cluster
    priority: int            # 1–5 (5 = highest)
    payload: dict            # Command-specific data
    timestamp: datetime
```

**Available command types:**
- **`alert`** — Send alerts to operators (payload: `{"message": "...", "recipients": [...]}`)
- **`notify`** — Async notification via Slack/PagerDuty (payload: `{"channel": "slack", "message": "...", "urgency": "high"}`)
- **`escalate`** — Escalate to higher authority (payload: `{"reason": "...", "urgency": "high"}`)
- **`suppress`** — Suppress a known false positive (payload: `{"finding_ids": [...], "reason": "..."}`)
- **`drone_task`** — Deploy a drone for inspection (payload: `{"target_cluster": "...", "task": "inspect"}`)

**Example:**
```python
ActuatorCommand.create(
    command_type="notify",
    source_agent="supervisor",
    cluster_id="cluster-north",
    priority=4,
    payload={
        "channel": "slack",
        "message": "Fire detected in cluster-north. Two sensors spiking.",
        "urgency": "high"
    }
)
```

---

### The Fan-Out Pattern: Send API

The supervisor uses LangGraph's **Send API** to invoke cluster agents in parallel:

```python
def fan_out_to_clusters(state: SupervisorState) -> list:
    """
    Return a list of Send() objects — one per cluster.
    LangGraph runs them all in parallel.
    """
    cluster_ids = state.get("active_cluster_ids", [])
    
    sends = []
    for cluster_id in cluster_ids:
        # Create initial state for this cluster agent
        cluster_state = {
            "cluster_id": cluster_id,
            "trigger_event": None,
            "sensor_events": [],
            "messages": [],
            "anomalies": [],
            "status": "idle"
        }
        sends.append(Send("run_cluster_agent", cluster_state))
    
    return sends
```

**What happens:**
1. Supervisor creates a `Send()` for each cluster
2. LangGraph invokes all cluster agents **in parallel**
3. Each cluster agent runs independently with its own state
4. Results (findings) are merged back into `SupervisorState.cluster_findings`

This is how the supervisor scales to N clusters without blocking.

---

## Example: Full Agent Pipeline

```python
import asyncio
from domains.wildfire import create_basic_wildfire
from domains.wildfire.sensors import TemperatureSensor, SmokeSensor
from sensors import SensorPublisher
from transport import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph

# 1. Create the world
engine = create_basic_wildfire()

# 2. Create sensors
sensors = [
    TemperatureSensor(
        source_id="temp-north-1",
        cluster_id="cluster-north",
        engine=engine,
        grid_row=2,
        grid_col=3,
    ),
    SmokeSensor(
        source_id="smoke-north-1",
        cluster_id="cluster-north",
        engine=engine,
        grid_row=2,
        grid_col=4,
    ),
]

# 3. Create the queue
queue = SensorEventQueue()

# 4. Create the publisher
publisher = SensorPublisher(
    sensors=sensors,
    queue=queue,
    tick_interval_seconds=0.1,
    engine=engine,
)

# 5. Create the cluster agent graph
cluster_graph = build_cluster_agent_graph()

# 6. Create the bridge consumer
findings = []


def on_finding(finding):
    findings.append(finding)
    print(f"Finding: {finding['summary']}")


consumer = EventBridgeConsumer(
    queue=queue,
    agent_graph=cluster_graph,
    on_finding=on_finding,
)


# 7. Run everything
async def run_pipeline():
    # Start the consumer
    consumer_task = asyncio.create_task(consumer.run())

    # Run the publisher for 60 ticks
    await publisher.run(ticks=60)

    # Stop the consumer
    consumer.stop()
    await consumer_task

    # Print results
    print(f"\nTotal findings: {len(findings)}")
    for f in findings:
        print(f"  - {f['cluster_id']}: {f['summary']}")


asyncio.run(run_pipeline())
```

**Output:**
```
Finding: Two adjacent temperature sensors spiking above 40°C. Likely fire.
Finding: Smoke density increased to 245 ppm near fire location.
Finding: Temperature continues to rise in cluster-north.

Total findings: 3
  - cluster-north: Two adjacent temperature sensors spiking above 40°C. Likely fire.
  - cluster-north: Smoke density increased to 245 ppm near fire location.
  - cluster-north: Temperature continues to rise in cluster-north.
```

---

## Stub vs. LLM Mode

Both cluster and supervisor agents support **dual mode**:

### Stub Mode (Default)
- **No LLM required** — deterministic logic
- **Fast** — no API calls
- **Predictable** — same input → same output
- **Good for:** Unit tests, CI/CD, debugging

```python
graph = build_cluster_agent_graph()  # stub mode
```

### LLM Mode
- **Requires LLM** — OpenAI API key
- **Slower** — network latency + LLM inference
- **Stochastic** — same input → different outputs
- **Good for:** Real reasoning, complex scenarios, demos

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
graph = build_cluster_agent_graph(llm=llm)
```

**When to use which:**
- **Development/testing:** Stub mode
- **Production/demos:** LLM mode
- **Evaluation:** Both (compare stub baseline vs. LLM performance)

---

## Next Steps

Now that you understand agents, the next tutorials will cover:
- **Part 4: The Full Pipeline** — Wiring world → sensors → queue → agents → supervisor → actuators
- **Part 5: Resources** — Preparedness assets (firetrucks, hospitals) and how the supervisor queries them

---

## Quick Reference

### Build a cluster agent graph

```python
from agents.cluster.graph import build_cluster_agent_graph

# Stub mode
graph = build_cluster_agent_graph()

# LLM mode
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
graph = build_cluster_agent_graph(llm=llm)
```

### Invoke a cluster agent
```python
result = graph.invoke({
    "cluster_id": "cluster-north",
    "trigger_event": sensor_event,
    "sensor_events": [sensor_event],
    "messages": [],
    "anomalies": [],
    "status": "idle"
})

findings = result["anomalies"]
```

### Build a supervisor graph

```python
from agents.supervisor.graph import build_supervisor_graph

# Stub mode
graph = build_supervisor_graph()

# LLM mode
graph = build_supervisor_graph(llm=llm)

# LLM mode with resource awareness
from domains.wildfire import create_wildfire_resources
resources = create_wildfire_resources()
graph = build_supervisor_graph(llm=llm, resource_inventory=resources)
```

### Invoke a supervisor
```python
result = graph.invoke({
    "active_cluster_ids": ["cluster-north", "cluster-south"],
    "cluster_findings": [],
    "messages": [],
    "pending_commands": [],
    "situation_summary": None,
    "status": "idle"
})

commands = result["pending_commands"]
```

### Available tools
**Cluster agent tools:**
- `get_recent_readings(limit, source_type)`
- `get_sensor_summary(source_type)`
- `check_threshold(source_type, field, threshold)`
- `get_cluster_status()`

**Supervisor agent tools:**
- `get_all_findings(limit)`
- `get_findings_by_cluster(cluster_id)`
- `get_finding_summary()`
- `check_cross_cluster(anomaly_type)`

**Resource tools (when ResourceInventory provided):**
- `get_resource_summary()`
- `get_resources_by_cluster(cluster_id)`
- `get_resources_by_type(resource_type)`
- `check_preparedness(cluster_id)`
