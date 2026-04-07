from world.generic_engine import GenericWorldEngine, GenericGroundTruthSnapshot
from world.environment import EnvironmentState
from world.physics import PhysicsModule, StateEvent
from world.weather import WeatherState

"""
ogar.world

The world engine — maintains ground truth that sensors sample from.

Design philosophy
─────────────────
The world engine is a deterministic sandbox.  It simulates an environment
(terrain, weather, fire) that evolves over discrete time ticks.  Sensors
attached to the engine read from the world state and produce SensorEvent
envelopes.  The agent never sees the world engine directly — it only sees
sensor readings.

The gap between ground truth (what the engine knows) and sensor output
(what the agent sees) is where interesting agent behaviour lives.
A fire is spreading, but the smoke sensor is in DROPOUT mode.
The thermal camera sees a hot spot, but humidity is normal.
The agent has to reason under uncertainty.

Ground truth is recorded so that after a scenario runs, you can
evaluate the agent's decisions against what was actually happening.

This package does NOT contain LangGraph, Kafka, or agent logic.
It is pure simulation — deterministic (given a seed), stateful,
and fast enough to generate thousands of scenarios offline.

Modules
───────
  grid.py              ← TerrainGrid: 2D cells with vegetation, moisture, fire state
  weather.py           ← WeatherState: global weather that evolves per tick
  engine.py            ← WorldEngine: the tick loop that coordinates everything
  fire_spread/         ← Pluggable fire behaviour models
    interface.py       ← FireSpreadModule ABC (the contract)
    heuristic.py       ← FireSpreadHeuristic (placeholder implementation)
  scenarios/           ← Factory functions that configure named scenarios
    wildfire_basic.py  ← Simple wildfire on a small grid
"""
