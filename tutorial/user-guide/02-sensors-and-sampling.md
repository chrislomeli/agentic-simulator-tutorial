# Tutorial Part 2: Sensors and Sampling

## What Are Sensors?

Sensors are the **eyes and ears** of your AI agents. They sample the World Engine (the ground truth) and produce **noisy, incomplete readings** that the agents use to figure out what's happening.

### The Key Insight

```
┌─────────────────────────────────────────────────────────┐
│  World Engine (ground truth)                            │
│  Cell (5,5): BURNING, intensity=0.8, temp=45°C          │
└─────────────────────────────────────────────────────────┘
                        ↓
            ┌───────────────────────┐
            │  TemperatureSensor    │  ← Samples nearby
            │  at position (5,6)    │    Adds noise
            └───────────────────────┘
                        ↓
            ┌───────────────────────┐
            │  SensorEvent          │
            │  payload: {           │
            │    "celsius": 43.2    │  ← Not exactly 45°C!
            │  }                    │
            │  confidence: 0.95     │
            └───────────────────────┘
                        ↓
            ┌───────────────────────┐
            │  AI Agent             │  ← Only sees this
            │  "Hmm, 43.2°C is      │
            │   higher than normal" │
            └───────────────────────┘
```

**The agent never sees the ground truth.** It only sees sensor readings, which are:
- **Noisy**: A thermometer reading 43.2°C when the actual temperature is 45°C
- **Incomplete**: Only 6 sensors covering a 10×10 grid
- **Delayed**: Readings might be from 1-2 ticks ago
- **Faulty**: Sensors can get stuck, drift, or drop out entirely

This gap between reality and perception is where the AI's reasoning happens.

---

## The Sensor Architecture

### 1. **SensorBase** — The Abstract Foundation

All sensors inherit from `SensorBase`, which handles:
- **Identity**: `source_id`, `source_type`, `cluster_id`
- **Envelope creation**: Wrapping readings in `SensorEvent` envelopes
- **Failure modes**: Simulating stuck sensors, dropouts, drift, spikes
- **Health tracking**: Reporting a confidence score (0.0–1.0)

**What subclasses must implement:**

```python
from sensors.base import SensorBase


class MyCustomSensor(SensorBase):
    source_type = "my_sensor_type"

    def read(self) -> dict:
        # Return domain-specific payload
        return {"my_reading": 42.0}
```

That's it! The base class handles everything else.

---

### 2. **Concrete Sensor Types**

Six sensor types are implemented in `ogar.domains.wildfire.sensors`:

#### **TemperatureSensor**
Reads ambient temperature + heat from nearby fires.

```python
from domains.wildfire.sensors import TemperatureSensor

sensor = TemperatureSensor(
    source_id="temp-001",
    cluster_id="cluster-north",
    engine=engine,  # Reference to GenericWorldEngine
    grid_row=5,  # Sensor position on grid
    grid_col=6,
    noise_std=0.5  # Gaussian noise (°C)
)

event = sensor.emit()
# → SensorEvent with payload: {"celsius": 43.2, "unit": "C"}
```

**How it works:**
1. Reads base temperature from `engine.environment.temperature_c`
2. Checks nearby cells for burning fires
3. Adds heat boost based on fire intensity and distance
4. Adds Gaussian noise (`noise_std`)
5. Returns `{"celsius": final_temp, "unit": "C"}`

#### **HumiditySensor**
Reads relative humidity from the environment.

```python
from domains.wildfire.sensors import HumiditySensor

sensor = HumiditySensor(
    source_id="humid-001",
    cluster_id="cluster-north",
    engine=engine,
    noise_std=2.0  # % points
)

event = sensor.emit()
# → payload: {"relative_humidity_pct": 18.3}
```

#### **WindSensor**
Reads wind speed and direction.

```python
from domains.wildfire.sensors import WindSensor

sensor = WindSensor(
    source_id="wind-001",
    cluster_id="cluster-north",
    engine=engine,
    speed_noise_std=0.3,  # m/s
    direction_noise_std=5.0  # degrees
)

event = sensor.emit()
# → payload: {"speed_mps": 7.8, "direction_deg": 228}
```

#### **SmokeSensor**
Detects smoke based on nearby fire intensity.

```python
from domains.wildfire.sensors import SmokeSensor

sensor = SmokeSensor(
    source_id="smoke-001",
    cluster_id="cluster-north",
    engine=engine,
    grid_row=5,
    grid_col=6,
    noise_std=10.0  # µg/m³
)

event = sensor.emit()
# → payload: {"pm25_ugm3": 245.0}
```

**How it works:**
- Checks nearby burning cells
- Higher fire intensity → more smoke
- Returns particulate density in µg/m³ (PM2.5)

#### **BarometricSensor**
Reads atmospheric pressure.

```python
from domains.wildfire.sensors import BarometricSensor

sensor = BarometricSensor(
    source_id="baro-001",
    cluster_id="cluster-north",
    engine=engine,
    noise_std=0.5  # hPa
)

event = sensor.emit()
# → payload: {"pressure_hpa": 1012.3}
```

#### **ThermalCameraSensor**
Reads a heat grid from a rectangular region.

```python
from domains.wildfire.sensors import ThermalCameraSensor

sensor = ThermalCameraSensor(
    source_id="thermal-001",
    cluster_id="cluster-north",
    engine=engine,
    top_row=3,
    left_col=3,
    view_rows=4,  # 4×4 grid view
    view_cols=4,
    noise_std=1.0
)

event = sensor.emit()
# → payload: {
#     "grid_celsius": [
#       [35.2, 36.1, 38.4, 37.9],
#       [34.8, 42.3, 51.2, 45.6],  ← Hot spot detected
#       [35.1, 39.8, 48.7, 43.2],
#       [34.9, 35.7, 36.4, 36.1]
#     ],
#     "top_row": 3,
#     "left_col": 3
#   }
```

**Use case:** Wide-area fire detection. The agent can analyze the heat grid to find hotspots.

---

## The SensorEvent Envelope

Every sensor reading is wrapped in a **SensorEvent** — a standardized envelope that crosses the wire.

```python
@dataclass
class SensorEvent:
    event_id: str           # UUID for deduplication
    source_id: str          # "temp-001"
    source_type: str        # "temperature"
    cluster_id: str         # "cluster-north" (routing key)
    timestamp: datetime     # Wall-clock time (UTC)
    sim_tick: int           # Simulation tick counter
    confidence: float       # 0.0–1.0 (sensor health)
    payload: dict           # Domain-specific reading
    metadata: dict          # Optional extras
```

**Why this design?**
- **Domain-agnostic**: The envelope doesn't know about wildfires, temperature, or smoke
- **Extensible**: Add new sensor types without changing the envelope
- **Routable**: `cluster_id` tells the system which agent gets the event
- **Trustworthy**: `confidence` lets agents weight readings

**Example:**
```python
SensorEvent(
    event_id="550e8400-e29b-41d4-a716-446655440000",
    source_id="temp-001",
    source_type="temperature",
    cluster_id="cluster-north",
    timestamp=datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc),
    sim_tick=42,
    confidence=0.95,
    payload={"celsius": 43.2, "unit": "C"},
    metadata={"firmware_version": "2.1.3"}
)
```

---

## Failure Modes: Simulating Real Sensor Behavior

Real sensors fail in predictable ways. The `FailureMode` enum lets you inject failures:

```python
from sensors.base import FailureMode

sensor.set_failure_mode(FailureMode.STUCK)
# → sensor.emit() returns the same reading every time

sensor.set_failure_mode(FailureMode.DROPOUT)
# → sensor.emit() returns None (sensor goes silent)

sensor.set_failure_mode(FailureMode.DRIFT)
# → readings slowly drift away from true value

sensor.set_failure_mode(FailureMode.SPIKE)
# → occasional large outliers injected

sensor.set_failure_mode(FailureMode.NORMAL)
# → sensor works correctly (default)
```

**Why this matters:**
Your AI agents need to handle faulty sensors gracefully. Testing with failure modes ensures they don't panic when a sensor goes offline or starts reporting garbage.

---

## The SensorPublisher: Ticking All Sensors

The **SensorPublisher** is an async loop that:
1. Calls `emit()` on each sensor
2. Puts the resulting `SensorEvent` onto a queue
3. Waits for `tick_interval_seconds`
4. Repeats

```python
from sensors import SensorPublisher
from transport import SensorEventQueue

# Create sensors
temp_sensor = TemperatureSensor(...)
smoke_sensor = SmokeSensor(...)

# Create a queue
queue = SensorEventQueue()

# Create the publisher
publisher = SensorPublisher(
    sensors=[temp_sensor, smoke_sensor],
    queue=queue,
    tick_interval_seconds=1.0,  # Tick every second
    engine=engine  # Optional: auto-tick the world
)

# Run forever
await publisher.run()

# Or run for N ticks
await publisher.run(ticks=60)
```

**Optional: Auto-tick the world**

If you pass `engine=engine` to the publisher, it will call `engine.tick()` before each sensor pass. This keeps the world and sensors synchronized:

```python
publisher = SensorPublisher(
    sensors=[...],
    queue=queue,
    engine=engine  # ← World ticks automatically
)

await publisher.run(ticks=60)
# → World ticks 60 times, sensors sample after each tick
```

---

## Noise Model: Gaussian Noise

Each sensor adds **Gaussian (normal) noise** to its readings.

```python
sensor = TemperatureSensor(
    ...,
    noise_std=0.5  # Standard deviation in °C
)
```

**What this means:**
- 68% of readings are within ±0.5°C of true value
- 95% of readings are within ±1.0°C of true value
- Occasional outliers beyond ±1.5°C

**Debugging tip:** Set `noise_std=0.0` for perfect readings when testing agent logic.

---

## Example: Full Sensor Setup

```python
import random
from domains.wildfire import create_basic_wildfire
from domains.wildfire.sensors import (
    TemperatureSensor,
    SmokeSensor,
    WindSensor,
)
from sensors import SensorPublisher
from transport import SensorEventQueue

# 1. Create the world
random.seed(42)
engine = create_basic_wildfire()

# 2. Create sensors
sensors = [
    TemperatureSensor(
        source_id="temp-north-1",
        cluster_id="cluster-north",
        engine=engine,
        grid_row=2,
        grid_col=3,
        noise_std=0.5,
    ),
    TemperatureSensor(
        source_id="temp-north-2",
        cluster_id="cluster-north",
        engine=engine,
        grid_row=3,
        grid_col=5,
        noise_std=0.5,
    ),
    SmokeSensor(
        source_id="smoke-north-1",
        cluster_id="cluster-north",
        engine=engine,
        grid_row=2,
        grid_col=4,
        noise_std=10.0,
    ),
    WindSensor(
        source_id="wind-north-1",
        cluster_id="cluster-north",
        engine=engine,
    ),
]

# 3. Create the event queue
queue = SensorEventQueue()

# 4. Create the publisher (auto-ticks the world)
publisher = SensorPublisher(
    sensors=sensors,
    queue=queue,
    tick_interval_seconds=0.1,  # Fast for testing
    engine=engine,
)

# 5. Run for 60 ticks
await publisher.run(ticks=60)

# 6. Drain the queue
while not queue.empty():
    event = await queue.get()
    print(f"Tick {event.sim_tick}: {event.source_id} → {event.payload}")
    queue.task_done()
```

**Output:**
```
Tick 0: temp-north-1 → {'celsius': 34.8, 'unit': 'C'}
Tick 0: temp-north-2 → {'celsius': 35.2, 'unit': 'C'}
Tick 0: smoke-north-1 → {'pm25_ugm3': 0.0}
Tick 0: wind-north-1 → {'speed_mps': 8.1, 'direction_deg': 227}
Tick 1: temp-north-1 → {'celsius': 35.1, 'unit': 'C'}
...
Tick 15: temp-north-1 → {'celsius': 42.3, 'unit': 'C'}  ← Fire detected!
Tick 15: smoke-north-1 → {'pm25_ugm3': 245.0}
```

---

## Sensor Coverage and Blind Spots

Sensors only cover **part** of the grid. This creates blind spots where fires can grow undetected.

**Example: 10×10 grid with 6 sensors**
```
  0 1 2 3 4 5 6 7 8 9
0 . . . . . . . . . .
1 . . T . . . . . . .  ← T = TemperatureSensor
2 . . . . S . . . . .  ← S = SmokeSensor
3 . . . . . . T . . .
4 . . . . . . . . . .
5 . . . . . . . . . .
6 . . . S . . . . . .
7 . . . . . . . . . .
8 . . . . . . . T . .
9 . . . . . . . . . .
```

**Blind spots:** Rows 0, 4-5, 7, 9 have no sensors. A fire starting there might not be detected until it spreads into sensor range.

**Agent challenge:** The AI must infer what's happening in blind spots based on:
- Nearby sensor readings
- Wind direction (smoke drifts downwind)
- Correlated signals (multiple sensors spiking)

---

## Next Steps

Now that you understand sensors, the next tutorial will cover:
- **Part 3: AI Agents** — How cluster agents analyze sensor events and detect anomalies
- **Part 4: The Full Pipeline** — Wiring world → sensors → queue → agents → supervisor
- **Part 5: Resources** — Preparedness assets (firetrucks, hospitals) and how agents query them

---

## Quick Reference

### Create a sensor

```python
from domains.wildfire.sensors import TemperatureSensor

sensor = TemperatureSensor(
    source_id="temp-001",
    cluster_id="cluster-north",
    engine=engine,
    grid_row=5,
    grid_col=6,
    noise_std=0.5
)
```

### Emit a reading
```python
event = sensor.emit()
# → SensorEvent or None (if in DROPOUT mode)
```

### Set a failure mode

```python
from sensors.base import FailureMode

sensor.set_failure_mode(FailureMode.STUCK)
sensor.set_failure_mode(FailureMode.DROPOUT)
sensor.set_failure_mode(FailureMode.NORMAL)
```

### Run the publisher

```python
from sensors import SensorPublisher
from transport import SensorEventQueue

queue = SensorEventQueue()
publisher = SensorPublisher(
    sensors=[sensor1, sensor2],
    queue=queue,
    tick_interval_seconds=1.0,
    engine=engine  # Optional: auto-tick
)

await publisher.run(ticks=60)
```

### Available sensor types (from `ogar.domains.wildfire.sensors`)
- `TemperatureSensor` — ambient temp + fire heat → `{"celsius": ..., "unit": "C"}`
- `HumiditySensor` — relative humidity → `{"relative_humidity_pct": ...}`
- `WindSensor` — speed + direction → `{"speed_mps": ..., "direction_deg": ...}`
- `SmokeSensor` — particulate density → `{"pm25_ugm3": ...}`
- `BarometricSensor` — atmospheric pressure → `{"pressure_hpa": ...}`
- `ThermalCameraSensor` — heat grid → `{"grid_celsius": [[...]], "top_row": ..., "left_col": ...}`
