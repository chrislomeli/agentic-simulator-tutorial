# Tutorial Part 1: Understanding the World Engine

## What is the World Engine?

The **World Engine** is a domain-agnostic simulation framework. For the wildfire scenario it creates a fake world for your AI agents to practice on — but the same framework can be reused for any domain (ocean monitoring, disease tracking, etc.) by plugging in a different physics module.

Think of it like a video game engine: the engine provides the tick loop and grid, while the "game" (wildfire, ocean current, etc.) is a pluggable domain skin.

### The Big Picture

```
┌─────────────────────────────────────────────────────────────┐
│  GenericWorldEngine[FireCellState]                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  Generic     │    │  Fire        │    │  Fire        │  │
│  │  Terrain     │    │  Environment │    │  Physics     │  │
│  │  Grid        │    │  State       │    │  Module      │  │
│  │  (the map)   │    │ (temp, wind) │    │ (spread)     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                              │
│  Every "tick" (like a game frame):                          │
│    1. Environment changes (wind shifts, temp drifts)        │
│    2. Physics runs (fire spreads, cells extinguish)         │
│    3. A "ground truth snapshot" is saved (the answer key)   │
└─────────────────────────────────────────────────────────────┘
                            ↓
                    ┌───────────────┐
                    │   Sensors     │  ← Sample the world
                    │ (thermometer, │    (noisy, incomplete)
                    │  smoke, etc.) │
                    └───────────────┘
                            ↓
                    ┌───────────────┐
                    │  AI Agents    │  ← Try to figure out
                    │               │    what's happening
                    └───────────────┘
```

**Key insight:** The AI agents never see the "ground truth." They only see sensor readings, which are noisy and incomplete. After the simulation, you compare what the agents *thought* was happening to what *actually* happened.

---

## The Three Core Components

### 1. **Terrain Grid** — The Map

A 2D grid of cells, like a chessboard. Each cell is a small patch of land (imagine 100m × 100m). The grid is generic — it holds any `CellState` type, typed via `Generic[C]`.

**For the wildfire domain, each cell (`FireCellState`) tracks:**
- **Terrain type**: Forest, grassland, rock, water, or urban
- **Vegetation**: How much burnable stuff is there (0.0 = bare rock, 1.0 = dense forest)
- **Fuel moisture**: How wet the fuel is (0.0 = bone dry, 1.0 = soaking wet)
- **Slope**: Is it flat, uphill, or downhill?
- **Fire state**: UNBURNED, BURNING, or BURNED
- **Fire intensity**: How hot the fire is (0.0–1.0)

Cell state is **immutable** — instead of mutating a cell, you create a new state and inject it.

**Example:**

```python
from domains.wildfire import FirePhysicsModule
from domains.wildfire import FireCellState, TerrainType
from world.generic_grid import GenericTerrainGrid

# Create a physics module (provides the initial cell state factory)
physics = FirePhysicsModule()

# Create a 10×10 grid
grid = GenericTerrainGrid(rows=10, cols=10, initial_state_factory=physics.initial_cell_state)

# Set cell (5, 5) to be dense, dry forest
forest_state = FireCellState(
    terrain_type=TerrainType.FOREST,
    vegetation=0.8,
    fuel_moisture=0.3,
)
grid.update_cell_state(5, 5, forest_state)

# Start a fire there (returns a new immutable state)
ignited = grid.get_cell(5, 5).cell_state.ignited(tick=0, intensity=0.7)
grid.update_cell_state(5, 5, ignited)
```

**Coordinates:**
- `(row, col)` where `(0, 0)` is the **north-west corner**
- Row 0 = north edge, increasing row = moving south
- Col 0 = west edge, increasing col = moving east

---

### 2. **Environment State** — Environmental Conditions

The environment captures ambient conditions that affect physics. It is a pluggable `EnvironmentState` — for wildfire that's `FireEnvironmentState`.

**What it tracks:**
- **Temperature** (°C)
- **Humidity** (%)
- **Wind speed** (m/s)
- **Wind direction** (compass degrees: 0° = north, 90° = east, 180° = south, 270° = west)
- **Barometric pressure** (hPa)

**Example:**

```python
from domains.wildfire.environment import FireEnvironmentState

# Hot, dry, windy day — perfect for wildfires
env = FireEnvironmentState(
    temperature_c=35,  # Hot
    humidity_pct=15,  # Very dry
    wind_speed_mps=8,  # Strong wind
    wind_direction_deg=225,  # Blowing from the south-west
)
```

**Environment evolves over time:**
Each tick, the environment drifts slightly (temperature goes up/down, wind shifts direction). Controlled by `*_drift` parameters.

---

### 3. **Physics Module** — The Rules

This is the "game engine" that decides how state evolves each tick. For wildfire, `FirePhysicsModule` decides which cells catch fire.

**How it works (simplified):**
1. For each BURNING cell:
   - Has it been burning long enough? → If yes, return a BURNED `StateEvent`
   - For each UNBURNED neighbor:
     - Calculate spread probability based on wind, slope, fuel moisture, vegetation, humidity
     - Roll the dice: if random() < probability → return a BURNING `StateEvent`
2. The engine applies all `StateEvent`s to the grid

**The physics module is pluggable** — you can swap in a different physics implementation (e.g., Rothermel fire spread model) by subclassing `PhysicsModule[FireCellState]`.

---

## Putting It All Together: The World Engine

`GenericWorldEngine[FireCellState]` coordinates everything. Each tick:

1. **Environment evolves** (temperature drifts, wind shifts)
2. **Physics module runs** (computes `StateEvent`s)
3. **State events are applied** to the grid
4. **Ground truth snapshot is saved** (the answer key)

**Example:**

```python
from domains.wildfire import FirePhysicsModule
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire import FireCellState, TerrainType
from world import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid

# 1. Create the physics module and grid
physics = FirePhysicsModule()
grid = GenericTerrainGrid(rows=10, cols=10, initial_state_factory=physics.initial_cell_state)

# 2. Set the environment
env = FireEnvironmentState(temperature_c=35, humidity_pct=15, wind_speed_mps=8)

# 3. Create the engine
engine = GenericWorldEngine(grid=grid, environment=env, physics=physics)

# 4. Ignite cell (5, 5)
ignited = engine.grid.get_cell(5, 5).cell_state.ignited(tick=0, intensity=0.8)
engine.inject_state(5, 5, ignited)

# 5. Run the simulation
for tick in range(60):
    snapshot = engine.tick()
    print(f"Tick {tick}: {snapshot.domain_summary['burning_cells']} cells burning")
```

**Output:**
```
Tick 0: 1 cells burning
Tick 1: 2 cells burning
Tick 2: 4 cells burning
Tick 3: 7 cells burning
...
```

---

## Ground Truth vs. Sensor Readings

**Ground truth** = what's *actually* happening in the simulation.

After each tick, the engine saves a `GenericGroundTruthSnapshot`:
- `tick` — simulation tick number
- `environment` — weather conditions as a dict
- `domain_summary` — physics-specific summary (burning cells, intensity map, cell counts)
- `grid_summary` — cell counts by label (`{"BURNING": 3, "BURNED": 1, "UNBURNED": 96}`)
- `resource_summary` — optional preparedness data (populated by scenario scripts, not the engine)

**The AI agents never see this.** They only see **sensor readings**, which are:
- **Noisy**: A thermometer might read 34°C when it's actually 35°C
- **Incomplete**: Sensors only cover part of the grid
- **Delayed**: Sensors might report readings from 2 ticks ago

**Why this matters:**
After the simulation, you compare:
- What the agent *thought* was happening (based on sensor readings)
- What *actually* happened (ground truth)

This is how you evaluate whether your agent is good at detecting fires.

---

## Pre-Built Scenarios

Instead of building a grid from scratch every time, you can use pre-built scenarios:

```python
from domains.wildfire import create_basic_wildfire

# Get a fully configured engine ready to run
engine = create_basic_wildfire()

# The scenario includes:
#   - A 10×10 grid with forest, grassland, rock ridge, lake, and urban area
#   - Hot, dry, windy weather from the south-west
#   - One fire ignition in the south-west grassland
#   - Fire will spread north-east toward the forest and urban area

# Just tick it
for _ in range(60):
    snapshot = engine.tick()
```

**With resources (preparedness assets):**

```python
from domains.wildfire import create_full_wildfire_scenario

# Returns (engine, resource_inventory) tuple
engine, resources = create_full_wildfire_scenario()

# Resources include:
#   - 2 firetrucks (south-west and south-east stations)
#   - 1 ambulance (central south)
#   - 1 hospital (near urban area, 50 beds)
#   - 1 helicopter (northern airfield)

# Query resource readiness
print(resources.readiness_summary())
```

**What the basic scenario looks like:**
```
Row 0 (north):  WATER  FOREST  FOREST  FOREST  ...
Row 1:          WATER  FOREST  FOREST  FOREST  ...
Row 2:          FOREST FOREST  FOREST  FOREST  ...
Row 3:          FOREST FOREST  FOREST  FOREST  ...
Row 4 (ridge):  ROCK   ROCK    ROCK    ROCK    ...  ← Firebreak
Row 5:          GRASS  GRASS   GRASS   GRASS   ...
Row 6:          GRASS  GRASS   GRASS   GRASS   ...
Row 7:          GRASS  GRASS   🔥     GRASS   ...  ← Fire starts here
Row 8:          GRASS  GRASS   GRASS   GRASS   URBAN URBAN
Row 9 (south):  GRASS  GRASS   GRASS   GRASS   ...

Wind: South-west → North-east (pushes fire toward forest and buildings)
```

---

## Reproducibility: Setting a Random Seed

Fire spread is probabilistic (dice rolls). To get the same results every time:

```python
import random
random.seed(42)

engine = create_basic_wildfire()
engine.run(ticks=60)

# Same fire spread pattern every time
```

**Why this matters:**
- **Debugging**: "Why did the agent miss the fire in cluster-north?" → Re-run with the same seed to see exactly what happened.
- **Comparison**: "Is agent v2 better than v1?" → Run both on the same scenarios.
- **Regression testing**: "Did my code change break anything?" → Run tests with fixed seeds.

---

## What the World Engine Does NOT Do

The engine is **pure simulation**. It does NOT:
- Know about Kafka, LangGraph, or agents
- Publish events to any message bus
- Run sensors automatically
- Make decisions or take actions

**Sensors are separate.** They hold a reference to the engine and sample from it:

```python
from domains.wildfire.sensors import TemperatureSensor

sensor = TemperatureSensor(
    source_id="temp-001",
    cluster_id="cluster-north",
    engine=engine,  # Reference to the world
    grid_row=2,
    grid_col=3,
)

# After each tick, the sensor can sample the world
event = sensor.emit()
# → SensorEvent with temperature reading (possibly noisy)
```

---

## Next Steps

Now that you understand the World Engine, the next tutorial will cover:
- **Part 2: Sensors** — How sensors sample the world and produce events
- **Part 3: Agents** — How AI agents consume sensor events and detect anomalies
- **Part 4: The Full Pipeline** — Wiring everything together
- **Part 5: Resources** — Preparedness assets (firetrucks, hospitals) and how agents query them

---

## Quick Reference

### Create a simple world

```python
from domains.wildfire import FirePhysicsModule
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire import FireCellState
from world import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid

physics = FirePhysicsModule()
grid = GenericTerrainGrid(rows=10, cols=10, initial_state_factory=physics.initial_cell_state)
env = FireEnvironmentState(temperature_c=35, humidity_pct=15, wind_speed_mps=8)
engine = GenericWorldEngine(grid=grid, environment=env, physics=physics)

# Ignite a cell
ignited = engine.grid.get_cell(5, 5).cell_state.ignited(tick=0, intensity=0.8)
engine.inject_state(5, 5, ignited)
```

### Run the simulation
```python
# Tick once
snapshot = engine.tick()

# Run N ticks
snapshots = engine.run(ticks=60)

# Access current state
current_grid = engine.grid
current_env = engine.environment
```

### Use a pre-built scenario

```python
from domains.wildfire import create_basic_wildfire

engine = create_basic_wildfire()
engine.run(ticks=60)
```

### Use a scenario with resources
```python
from domains.wildfire import create_full_wildfire_scenario

engine, resources = create_full_wildfire_scenario()
print(resources.readiness_summary())
engine.run(ticks=60)
```

### Set a random seed for reproducibility
```python
import random
random.seed(42)
engine = create_basic_wildfire()
```
