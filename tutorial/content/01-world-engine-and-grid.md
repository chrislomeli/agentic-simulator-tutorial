# Session 1: The Infrastructure

---

## What you're doing and why

Before you can build an agent, you need something for it to work with: a world that generates events, sensors that observe it, a transport layer that delivers observations, and resources that the agent can reason about.

**You will not write any of this code.** This session copies the infrastructure in, verifies it works, and walks you through what each component produces. You need to understand the data shapes and the flow — not the internals.

By the end of this session you will have:
- All infrastructure code in place and passing tests
- A clear picture of the data pipeline: world → sensors → transport → agent
- An understanding of what your agent will see, and what it won't

---

## Get the code

**If you're starting from a fresh clone**, run these setup steps first. If you already have a working `.venv` and the `tutorial` remote configured, skip ahead to "Copy everything."

```bash
# Create and activate virtual environment
uv venv
source .venv/bin/activate   # macOS/Linux

# Install dependencies
uv pip install -e ".[llm]" --group dev

# Add the tutorial repo as a remote (if not already added)
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
```

**Fetch the latest from the tutorial repo:**

```bash
git fetch tutorial
```

**Copy everything:**

```bash
git checkout tutorial/main -- src/world/
git checkout tutorial/main -- src/domains/
git checkout tutorial/main -- src/sensors/
git checkout tutorial/main -- src/transport/
git checkout tutorial/main -- src/bridge/
git checkout tutorial/main -- src/resources/
git checkout tutorial/main -- src/tools/
git checkout tutorial/main -- src/config.py
git checkout tutorial/main -- tests/
```

Install and verify:

```bash
uv pip install -e ".[llm]" --group dev
pytest tests/world/ tests/domains/ tests/sensors/ tests/transport/ -v
```

All these tests should pass. If anything fails, check that your virtual environment is active and dependencies are installed.

> **Note:** The `tests/bridge/` and `tests/resources/` directories contain tests that depend on agent and tool code you'll build in later sessions. They won't pass yet — that's expected. The tests above cover all the infrastructure you just copied.

---

## The data pipeline

Here's how data flows through the system. Your agent sits at the right end — it only sees what arrives through this pipeline:

```
World Engine          Sensors              Transport           Agent
(ground truth)   →   (noisy observations) →  (queue + routing) →  (your code)
                                                                     ↑
Resources ──────────────────────────────────────────────────────────┘
(queryable assets)
```

The agent never sees the world directly. It sees sensor events and can query resources. That gap between ground truth and observation is the whole point — it's what makes the agent's job interesting and testable.

---

## The World Engine: what it produces

The world engine simulates a wildfire spreading across a 10x10 grid, tick by tick. Each tick it advances weather, runs fire physics, and records a snapshot.

**What comes out each tick:**

```python
snapshot = engine.tick()

snapshot.tick              # 5 (which tick this is)
snapshot.grid_summary      # {'UNBURNED': 94, 'BURNING': 5, 'BURNED': 1}
snapshot.domain_summary    # fire behavior metrics (see below)
snapshot.environment       # {'temperature_c': 38.2, 'humidity_pct': 11.5, ...}
```

**The fire behavior metrics** are the operationally meaningful numbers:

| Field | What it tells you |
|-------|-------------------|
| `avg_ros_ft_min` | How fast the fire is moving (ft/min) |
| `max_fireline_intensity` | Energy output (BTU/ft/s) — determines what can stop it |
| `avg_flame_length_ft` | How tall the flames are |
| `danger_rating` | Low / Moderate / High / Very High / Extreme |
| `estimated_acres_hr` | How fast the fire is growing |

These numbers come from the Rothermel (1972) fire spread model. They're grounded in real-world wildfire science — the intensity ranges correspond to actual suppression categories (hand crews < 100 BTU/ft/s, engines 100-500, aircraft only above 2000).

**Try it:**

```python
from domains.wildfire.scenarios import create_basic_wildfire

engine = create_basic_wildfire()
for tick in range(10):
    snapshot = engine.tick()
    fb = snapshot.domain_summary
    print(f"Tick {snapshot.tick}: "
          f"{snapshot.grid_summary.get('BURNING', 0)} burning, "
          f"intensity={fb.get('max_fireline_intensity', 0):.0f} BTU/ft/s, "
          f"danger={fb.get('danger_rating', 'N/A')}")
```

**Your agent will never call this directly.** The world engine is ground truth. The agent only sees what sensors report.

---

## Sensors: what the agent actually sees

Sensors sit on the grid and sample the world each tick. They produce `SensorEvent` objects — noisy, incomplete observations of ground truth.

**What a sensor event looks like:**

```python
{
    "event_id": "a1b2c3...",          # unique per reading
    "source_id": "temp-sensor-A1",     # which sensor
    "source_type": "temperature",      # what kind of reading
    "cluster_id": "cluster-north",     # routing key — which agent gets this
    "sim_tick": 5,                     # when
    "confidence": 1.0,                 # sensor health (1.0 = healthy, 0.3 = stuck)
    "payload": {"celsius": 52.4},      # the actual reading — domain-specific
}
```

**Key properties:**
- **Noisy** — readings include Gaussian noise. Two sensors at the same spot won't report identical values.
- **Incomplete** — sensors only cover some grid cells. The agent has blind spots.
- **Sometimes wrong** — sensors can be stuck (frozen reading), in dropout (silent), or drifting (gradual offset). The `confidence` field reflects this.

**Sensor types in the wildfire domain:**

| Type | What it reads | Payload |
|------|--------------|---------|
| Temperature | Ambient temp + radiant heat from nearby fire | `{"celsius": 52.4}` |
| Smoke | PM2.5 based on fire intensity, distance, and wind | `{"pm25_ugm3": 145.2}` |
| Humidity | Relative humidity from the environment | `{"humidity_pct": 11.5}` |
| Wind | Speed and direction | `{"speed_mps": 8.1, "direction_deg": 225}` |
| Barometric | Air pressure | `{"pressure_hpa": 1008.3}` |
| Thermal Camera | Heat grid over a rectangular region | `{"grid": [[0.0, 0.8, ...], ...]}` |

**The gap between truth and observation is the testbed.** You can measure exactly how much information is lost by comparing sensor readings to the actual grid state. Later, you'll inject sensor failures and see whether the agent still makes good decisions.

---

## Transport: how events reach the agent

The transport layer moves sensor events from sensors to agents:

1. **SensorPublisher** — ticks the world engine each step, calls `emit()` on every sensor, and puts events onto a queue
2. **SensorEventQueue** — an async queue that decouples the producer (sensors) from the consumer (agents)
3. **EventBridgeConsumer** — reads events off the queue, batches them by `cluster_id`, and invokes the agent graph

**What the agent receives** (constructed by the bridge consumer):

```python
state = {
    "cluster_id": "cluster-north",
    "sensor_events": [event1, event2, event3],   # batch of events for this cluster
    "trigger_event": event3,                      # most recent event
    "messages": [],                               # LangGraph message list
    "anomalies": [],                              # findings accumulate here
    "status": "idle",
}
```

**Why batching matters:** The consumer doesn't invoke the agent for every single event. It collects a batch (default 3-5 events), then invokes once. This lets the agent correlate across readings — temperature spiked *and* smoke increased *and* wind shifted — all in one invocation. Better context, fewer LLM calls.

**Why per-cluster routing matters:** Each `cluster_id` gets its own agent instance. Events from `cluster-north` go to one agent, events from `cluster-south` go to another. Later (Session 3), a supervisor agent will aggregate findings across all clusters.

---

## Resources: what the agent can query

Resources are preparedness assets — firetrucks, crews, hospitals, helicopters. Unlike sensors, resources don't produce events. They're queryable state that helps the agent answer: "Are we prepared for this situation?"

**What a resource looks like:**

```python
{
    "resource_id": "engine-south-1",
    "resource_type": "engine",
    "cluster_id": "cluster-south",
    "status": "AVAILABLE",           # AVAILABLE / DEPLOYED / OUT_OF_SERVICE
    "capacity": 500.0,               # max capability (gallons of water)
    "available": 500.0,              # current remaining capability
    "mobile": True,                  # can it move?
    "metadata": {"nwcg_id": "E-3", "unit": "gallons"},
}
```

**The pre-built scenario includes 8 resources:**

| Resource | Type | What it does | Capacity |
|----------|------|-------------|----------|
| Hotshot Crew | crew | Fireline construction | 15 chains/hr |
| Hand Crew | crew | Fireline construction | 8 chains/hr |
| 2x Wildland Engines | engine | Water suppression | 500 gal each |
| Heavy Dozer | dozer | Firebreak construction | 60 chains/hr |
| Ambulance | ambulance | Medical transport | 2 patients |
| Hospital | hospital | Medical care | 50 beds |
| Heavy Helicopter | helicopter | Aerial suppression | 700 gal |

**Readiness summary** — this is what the agent queries:

```python
summary = resource_inventory.readiness_summary()
# Returns: total by type, how many available, capacity remaining, coverage by cluster
```

**Scenario knobs** let you degrade resources for testing:
- `reduce_resources("engine", keep_fraction=0.5)` — remove half the engines
- `disable_resources("helicopter", fraction=1.0)` — take all helicopters out of service
- `reset_all()` — restore everything

---

## The complete picture

Here's what your agent will work with when you start building it in Session 2:

**Inputs (what the agent sees):**
- Batches of sensor events — noisy temperature, smoke, humidity, wind readings
- Resource inventory queries — what's available, where, how much capacity

**Outputs (what the agent produces):**
- Anomaly findings — "temperature spike detected in cluster-south, severity High"
- Preparedness assessments — "insufficient engine coverage for current fire intensity"
- Recommended actions — "deploy engine-south-1 to grid position (5,3)"

**What the agent does NOT see:**
- The actual grid state (which cells are burning)
- The exact fire intensity or rate of spread
- Which sensors are malfunctioning (it only sees the `confidence` field)

That gap is intentional. It's the same incomplete picture a real incident commander has. Your job in the next sessions is to build an agent that makes good decisions despite that gap.

---

## Key files reference

**World Engine:**
- `src/world/generic_engine.py` — tick loop, snapshots
- `src/domains/wildfire/rothermel_physics.py` — fire spread model
- `src/domains/wildfire/scenarios.py` — pre-built scenarios

**Sensors:**
- `src/sensors/base.py` — `SensorBase`, failure modes
- `src/domains/wildfire/sensors.py` — temperature, smoke, humidity, wind, thermal camera
- `src/transport/schemas.py` — `SensorEvent` envelope

**Transport:**
- `src/sensors/publisher.py` — async tick loop, drives all sensors
- `src/transport/queue.py` — async event queue
- `src/bridge/consumer.py` — batching, routing, agent invocation

**Resources:**
- `src/resources/base.py` — `ResourceBase`, status transitions, capacity
- `src/resources/inventory.py` — registration, queries, readiness summaries
- `src/domains/wildfire/nwcg_resources.py` — NWCG-aligned resource definitions

---

## Checkpoint: what should pass

Run the infrastructure tests:

```bash
pytest tests/world/ tests/domains/ tests/sensors/ tests/transport/ -v
```

All tests should pass. If you want a quick count:

```bash
pytest tests/world/ tests/domains/ tests/sensors/ tests/transport/ -q
```

You should see something like `285 passed` (the exact number may vary as tests are added).

**Tests that will NOT pass yet** (and shouldn't):
- `tests/bridge/` — depends on agent code (Session 2)
- `tests/resources/` — some tests depend on tool code (Session 7)
- `tests/agents/` — you'll build this starting in Session 2
- `tests/tools/` — you'll build this in Sessions 3 and 7

---

*Next: Session 2 — you build your first agent. A LangGraph StateGraph that receives sensor event batches and classifies them into anomaly findings. First as stub logic (no LLM), then with an LLM and tools.*
