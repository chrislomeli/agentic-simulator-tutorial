# Tutorial Part 5: Resources and Preparedness

## What Are Resources?

Resources are **preparedness assets** that exist on the world grid — firetrucks, ambulances, hospitals, helicopters. They represent what you have available to respond to an incident.

### How Resources Differ from Sensors and Actuators

```
┌─────────────────────────────────────────────────────────────────┐
│  Component       │  Direction      │  Behavior                  │
├──────────────────┼─────────────────┼────────────────────────────┤
│  Sensors         │  World → Agent  │  Emit noisy readings       │
│  Resources       │  Agent queries  │  Static queryable state    │
│  Actuators       │  Agent → World  │  Execute commands          │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight:** Resources don't tick, don't emit events, and don't execute commands. They are **data** — things that exist on the grid that help agents answer:

> *"Are we prepared for what is happening?"*

---

## The Resource Model

### ResourceBase — A Pydantic BaseModel

Unlike sensors (which are ABCs with a `read()` method), resources are plain data. A firetruck and a hospital have the same interface — they differ in field values, not behavior.

```python
from resources.base import ResourceBase, ResourceStatus

firetruck = ResourceBase(
    resource_id="firetruck-7",
    resource_type="firetruck",
    cluster_id="cluster-south",
    grid_row=8,
    grid_col=3,
    capacity=500.0,        # gallons of water
    available=500.0,        # full tank
    mobile=True,            # can move to incidents
    metadata={"unit": "gallons", "crew_size": 4},
)
```

**Fields:**
- **`resource_id`** — Stable identifier (e.g. `"firetruck-7"`, `"hospital-central"`)
- **`resource_type`** — Opaque tag (e.g. `"firetruck"`, `"hospital"`, `"helicopter"`)
- **`cluster_id`** — Which cluster this resource belongs to (same concept as sensors)
- **`status`** — Current operational state (`ResourceStatus` enum)
- **`grid_row`** / **`grid_col`** — Position on the world grid
- **`capacity`** — Maximum capability (500 gallons, 50 beds, 4 flight hours)
- **`available`** — Current remaining capability
- **`mobile`** — Whether the resource can change grid position
- **`metadata`** — Domain-specific extras

---

### ResourceStatus — The State Machine

Resources have four states:

```
    ┌──────────┐     deploy()     ┌──────────┐
    │ AVAILABLE │ ───────────────→ │ DEPLOYED │
    │           │ ←─────────────── │          │
    └──────────┘     release()    └──────────┘
         │                              │
         │  send_en_route()             │
         ↓                              │
    ┌──────────┐                        │
    │ EN_ROUTE │ ───────────────────────┘
    │ (mobile  │     deploy()
    │  only)   │
    └──────────┘
         │
         │  disable()  (from any state)
         ↓
    ┌──────────────┐
    │ OUT_OF_SERVICE │
    └──────────────┘
```

```python
from resources.base import ResourceStatus

# All four states
ResourceStatus.AVAILABLE       # Ready to deploy
ResourceStatus.DEPLOYED        # Currently in use at an incident
ResourceStatus.EN_ROUTE        # Moving to a new location (mobile only)
ResourceStatus.OUT_OF_SERVICE  # Broken, refueling, offline
```

---

### Status Transitions

```python
# Deploy a firetruck to the fire
firetruck.deploy(row=5, col=3)
# → status = DEPLOYED, position updated to (5, 3)

# Send it en route first (mobile resources only)
firetruck.send_en_route(row=5, col=3)
# → status = EN_ROUTE, position set to destination

# Release it back to available
firetruck.release()
# → status = AVAILABLE

# Take it out of service
firetruck.disable()
# → status = OUT_OF_SERVICE

# Can't deploy an out-of-service resource
firetruck.deploy()  # → raises ValueError
```

**Fixed resources** (hospitals) can be deployed but their location doesn't change:
```python
hospital = ResourceBase(
    resource_id="hospital-central",
    resource_type="hospital",
    cluster_id="cluster-south",
    grid_row=8, grid_col=8,
    capacity=50.0,         # beds
    available=50.0,
    mobile=False,           # can't move
)

hospital.deploy()  # status changes, position stays at (8, 8)
```

---

### Capacity Management

Resources track consumable capacity separately from status:

```python
# Firetruck starts full
print(firetruck.available)  # 500.0

# Use 200 gallons fighting a fire
actual = firetruck.consume(200)
print(actual)                # 200.0
print(firetruck.available)   # 300.0

# Try to use more than available
actual = firetruck.consume(400)
print(actual)                # 300.0 (only what was left)
print(firetruck.available)   # 0.0

# Refill
firetruck.restore(500)
print(firetruck.available)   # 500.0 (capped at capacity)

# Check utilization
print(firetruck.utilization)  # 0.0 (fully available)
firetruck.consume(250)
print(firetruck.utilization)  # 0.5 (50% used)
```

**Important:** A hospital with 0 beds available is still `AVAILABLE` (operational). The agent distinguishes "overloaded" from "closed" by checking both status and capacity.

---

## ResourceInventory — Managing All Resources

The `ResourceInventory` manages resource placement on the grid, queries, and scenario knobs. It mirrors the `SensorInventory` pattern.

### Creating and Registering

```python
from resources.inventory import ResourceInventory
from resources.base import ResourceBase

inventory = ResourceInventory(grid_rows=10, grid_cols=10)

# Register resources
inventory.register(ResourceBase(
    resource_id="firetruck-1",
    resource_type="firetruck",
    cluster_id="cluster-south",
    grid_row=7, grid_col=1,
    capacity=500.0, available=500.0,
    mobile=True,
))

inventory.register(ResourceBase(
    resource_id="hospital-central",
    resource_type="hospital",
    cluster_id="cluster-south",
    grid_row=8, grid_col=8,
    capacity=50.0, available=50.0,
    mobile=False,
))

print(inventory.size)  # 2
```

### Querying Resources

```python
# By ID
truck = inventory.get_resource("firetruck-1")

# By type
trucks = inventory.by_type("firetruck")

# By cluster
south_resources = inventory.by_cluster("cluster-south")

# By status
available = inventory.by_status(ResourceStatus.AVAILABLE)

# At a grid position
resources_here = inventory.get_resources_at(row=7, col=1)

# All resources
all_resources = inventory.all_resources()
```

### Status Transitions via Inventory

```python
# Deploy through the inventory (validates grid bounds)
inventory.deploy("firetruck-1", row=5, col=3)

# Release back to available
inventory.release("firetruck-1")
```

### Readiness Summary

The most powerful query — gives a complete preparedness picture:

```python
summary = inventory.readiness_summary()
print(summary)
# {
#   "total_resources": 5,
#   "by_type": {
#     "firetruck": {
#       "total": 2,
#       "available": 2,
#       "deployed": 0,
#       "out_of_service": 0,
#       "total_capacity": 1000.0,
#       "available_capacity": 1000.0,
#     },
#     "hospital": { ... },
#     "helicopter": { ... },
#   },
#   "by_cluster": {
#     "cluster-south": {"total": 4, "available": 4, "types": ["ambulance", "firetruck", "hospital"]},
#     "cluster-north": {"total": 1, "available": 1, "types": ["helicopter"]},
#   },
#   "by_status": {"AVAILABLE": 5}
# }
```

### Coverage Analysis

```python
# Which clusters have what resource types?
coverage = inventory.coverage_by_cluster()
# {"cluster-south": ["ambulance", "firetruck", "hospital"], "cluster-north": ["helicopter"]}
```

---

## Scenario Knobs — Testing Agent Resilience

The inventory provides experimental knobs for testing how agents handle degraded preparedness:

### Reduce Resources (Budget Constraints)

```python
# Remove half of all firetrucks
removed = inventory.reduce_resources("firetruck", keep_fraction=0.5)
print(f"Removed: {removed}")
# → Removed: ['firetruck-2']
```

### Disable Resources (Equipment Failure)

```python
# Set 50% of ambulances to OUT_OF_SERVICE
disabled = inventory.disable_resources("ambulance", fraction=0.5)
print(f"Disabled: {disabled}")
```

### Reset Everything

```python
# Restore all resources to AVAILABLE with full capacity
inventory.reset_all()
```

**Why these matter:** Run the same fire scenario with full resources vs. degraded resources. Does the agent's decision quality change? Does it recognize when it's under-prepared?

---

## Pre-Built Wildfire Resources

Instead of building resources from scratch, use the scenario helpers:

```python
from domains.wildfire import create_wildfire_resources, create_full_wildfire_scenario

# Just resources (for an existing engine)
resources = create_wildfire_resources(grid_rows=10, grid_cols=10)

# Engine + resources together
engine, resources = create_full_wildfire_scenario()
```

**What's included:**

| Resource | Type | Cluster | Location | Capacity | Mobile |
|----------|------|---------|----------|----------|--------|
| firetruck-sw-1 | firetruck | cluster-south | (7, 1) | 500 gal | Yes |
| firetruck-se-1 | firetruck | cluster-south | (8, 7) | 500 gal | Yes |
| ambulance-1 | ambulance | cluster-south | (9, 4) | 2 patients | Yes |
| hospital-central | hospital | cluster-south | (8, 8) | 50 beds | No |
| helicopter-1 | helicopter | cluster-north | (1, 5) | 4 flight hrs | Yes |

---

## Agent Integration — Resource Tools

When you pass a `ResourceInventory` to `build_supervisor_graph()`, the supervisor LLM gains access to 4 additional tools:

### Wiring Resources into the Supervisor

```python
from langchain_openai import ChatOpenAI
from agents.supervisor.graph import build_supervisor_graph
from domains.wildfire import create_full_wildfire_scenario

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
engine, resources = create_full_wildfire_scenario()

# Supervisor now has resource tools in addition to finding tools
supervisor_graph = build_supervisor_graph(
    llm=llm,
    resource_inventory=resources,
)
```

### The Four Resource Tools

#### 1. `get_resource_summary()` — Overall readiness
```python
get_resource_summary()
# Returns the full readiness summary (same as inventory.readiness_summary())
```

#### 2. `get_resources_by_cluster(cluster_id)` — What's near a cluster
```python
get_resources_by_cluster(cluster_id="cluster-south")
# Returns list of resource summaries for that cluster
```

#### 3. `get_resources_by_type(resource_type)` — All of a type
```python
get_resources_by_type(resource_type="firetruck")
# Returns list of all firetruck summaries with status and capacity
```

#### 4. `check_preparedness(cluster_id)` — Gap analysis
```python
check_preparedness(cluster_id="cluster-south")
# Returns:
# {
#   "cluster_id": "cluster-south",
#   "total_resources": 4,
#   "available_resources": 4,
#   "resource_types_present": ["ambulance", "firetruck", "hospital"],
#   "total_capacity": 1052.0,
#   "available_capacity": 1052.0,
#   "utilization_pct": 0.0,
#   "gaps": []
# }
```

### How the LLM Uses These

```
LLM: I see a fire detected in cluster-south. Let me check our preparedness.
     [calls check_preparedness(cluster_id="cluster-south")]
     
     We have 4 resources: 2 firetrucks, 1 ambulance, 1 hospital.
     All are available. Good coverage.
     
     [calls get_resources_by_type(resource_type="firetruck")]
     
     Firetruck firetruck-sw-1 is closest to the fire at (7,1).
     It has a full 500 gallon tank.
     
     Recommendation: Deploy firetruck-sw-1 to the fire location.
     Alert hospital-central for potential casualties.
```

---

## Ground Truth Snapshots

The `GenericGroundTruthSnapshot` includes an optional `resource_summary` field. Scenario scripts can populate it after each tick:

```python
engine, resources = create_full_wildfire_scenario()

for _ in range(60):
    snapshot = engine.tick()
    # Optionally attach resource state to the snapshot
    snapshot.resource_summary = resources.readiness_summary()
```

This lets evaluators compare:
- What resources were actually available at each tick
- What the agent thought was available (via tool queries)
- Whether the agent made good deployment decisions given the resources

---

## Example: Full Pipeline with Resources

```python
import asyncio
import random
from domains.wildfire import create_full_wildfire_scenario
from domains.wildfire.sensors import TemperatureSensor, SmokeSensor
from sensors import SensorPublisher
from transport import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph
from agents.supervisor.graph import build_supervisor_graph


async def main():
    random.seed(42)

    # 1. World + Resources
    engine, resources = create_full_wildfire_scenario()
    print(f"World: {engine.grid.rows}×{engine.grid.cols}")
    print(f"Resources: {resources.size} assets")
    print(f"Coverage: {resources.coverage_by_cluster()}")

    # 2. Sensors
    sensors = [
        TemperatureSensor(
            source_id="temp-1", cluster_id="cluster-north",
            engine=engine, grid_row=3, grid_col=3,
        ),
        SmokeSensor(
            source_id="smoke-1", cluster_id="cluster-north",
            engine=engine, grid_row=5, grid_col=3,
        ),
    ]

    # 3. Queue + Publisher
    queue = SensorEventQueue()
    publisher = SensorPublisher(sensors=sensors, queue=queue, engine=engine)

    # 4. Cluster agent (stub)
    cluster_graph = build_cluster_agent_graph()

    # 5. Consumer
    findings = []
    consumer = EventBridgeConsumer(
        queue=queue,
        agent_graph=cluster_graph,
        on_finding=lambda f: findings.append(f),
    )

    # 6. Run sensor pipeline
    await publisher.run(ticks=15)
    await consumer.run(max_events=queue.total_enqueued)

    # 7. Supervisor with resource awareness (stub mode shown; pass llm= for LLM mode)
    supervisor_graph = build_supervisor_graph()
    supervisor_result = supervisor_graph.invoke({
        "active_cluster_ids": ["cluster-north", "cluster-south"],
        "cluster_findings": findings,
        "messages": [],
        "pending_commands": [],
        "situation_summary": None,
        "status": "idle",
    })

    # 8. Results
    print(f"\nFindings: {len(findings)}")
    print(f"Commands: {len(supervisor_result['pending_commands'])}")
    print(f"\nResource readiness:")
    for rtype, info in resources.readiness_summary()["by_type"].items():
        print(f"  {rtype}: {info['available']}/{info['total']} available, "
              f"{info['available_capacity']:.0f}/{info['total_capacity']:.0f} capacity")


asyncio.run(main())
```

---

## Testing Resilience with Scenario Knobs

```python
# Scenario 1: Full resources — baseline
engine, resources = create_full_wildfire_scenario()
# ... run pipeline, measure agent performance

# Scenario 2: Half the firetrucks removed
engine, resources = create_full_wildfire_scenario()
resources.reduce_resources("firetruck", keep_fraction=0.5)
# ... run same pipeline, compare decisions

# Scenario 3: Hospital out of service
engine, resources = create_full_wildfire_scenario()
resources.disable_resources("hospital", fraction=1.0)
# ... does the agent recommend evacuation instead?

# Scenario 4: Everything degraded
engine, resources = create_full_wildfire_scenario()
resources.disable_resources("firetruck", fraction=0.5)
resources.disable_resources("ambulance", fraction=1.0)
# ... how does the agent handle severe under-preparedness?
```

---

## What Resources Do NOT Do

Resources are deliberately limited in scope:

- **No ticking** — Resources don't evolve automatically. Fire doesn't consume water from a firetruck by itself.
- **No event emission** — Resources are queried, not pushed. Agents ask about them; resources don't announce themselves.
- **No dispatch actuators** — There's no built-in actuator that moves a firetruck. That's a future addition (additive, not breaking).
- **No persistence** — Resources live in memory for the scenario duration. No database.

These boundaries are explicit design decisions, not "fix later" stubs. Each can be extended additively when needed.

---

## Quick Reference

### Create a resource
```python
from resources.base import ResourceBase, ResourceStatus

truck = ResourceBase(
    resource_id="firetruck-1",
    resource_type="firetruck",
    cluster_id="cluster-south",
    grid_row=7, grid_col=1,
    capacity=500.0, available=500.0,
    mobile=True,
)
```

### Create an inventory
```python
from resources.inventory import ResourceInventory

inventory = ResourceInventory(grid_rows=10, grid_cols=10)
inventory.register(truck)
```

### Use pre-built scenario
```python
from domains.wildfire import create_full_wildfire_scenario

engine, resources = create_full_wildfire_scenario()
```

### Query readiness
```python
summary = resources.readiness_summary()
coverage = resources.coverage_by_cluster()
```

### Wire into supervisor
```python
from agents.supervisor.graph import build_supervisor_graph

graph = build_supervisor_graph(llm=llm, resource_inventory=resources)
```

### Test resilience
```python
resources.reduce_resources("firetruck", keep_fraction=0.5)
resources.disable_resources("hospital", fraction=1.0)
resources.reset_all()  # restore everything
```
