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
"""

from world.cell_state import CellState as CellState
from world.cell_state import GenericCell as GenericCell
from world.environment import EnvironmentState as EnvironmentState
from world.generic_engine import GenericGroundTruthSnapshot as GenericGroundTruthSnapshot
from world.generic_engine import GenericWorldEngine as GenericWorldEngine
from world.generic_grid import GenericTerrainGrid as GenericTerrainGrid
from world.grid import FireState as FireState
from world.grid import TerrainType as TerrainType
from world.physics import PhysicsModule as PhysicsModule
from world.physics import StateEvent as StateEvent
from world.sensor_inventory import SensorInventory as SensorInventory
from world.weather import WeatherState as WeatherState

__all__ = [
    "CellState",
    "GenericCell",
    "EnvironmentState",
    "GenericGroundTruthSnapshot",
    "GenericWorldEngine",
    "GenericTerrainGrid",
    "FireState",
    "TerrainType",
    "PhysicsModule",
    "StateEvent",
    "SensorInventory",
    "WeatherState",
]
