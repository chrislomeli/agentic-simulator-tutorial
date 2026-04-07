"""
ogar.domains.wildfire

Wildfire domain — stochastic fire spread on a terrain grid.

This package provides everything needed to run a wildfire simulation
using the generic framework:

  - FireCellState    : per-cell state (terrain, fuel, fire status)
  - FireEnvironmentState : weather conditions (temp, humidity, wind)
  - FirePhysicsModule : heuristic fire spread model
  - Fire-specific sensors (temperature, smoke, thermal camera, etc.)
  - Scenario configurations (basic wildfire setup)

Usage
─────
  from ogar.domains.wildfire.cell_state import FireCellState
  from ogar.domains.wildfire.environment import FireEnvironmentState
  from ogar.domains.wildfire.physics import FirePhysicsModule
  from ogar.world.generic_grid import GenericTerrainGrid
  from ogar.world.generic_engine import GenericWorldEngine

  physics = FirePhysicsModule()
  env = FireEnvironmentState(temperature_c=38, humidity_pct=12, wind_speed_mps=8)
  grid = GenericTerrainGrid(rows=10, cols=10,
                            initial_state_factory=physics.initial_cell_state)
  engine = GenericWorldEngine(grid=grid, environment=env, physics=physics)
  engine.run(ticks=60)
"""

from domains.wildfire.cell_state import FireCellState, FireState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire.physics import FirePhysicsModule, SimpleFirePhysicsModule
from domains.wildfire.rothermel_physics import RothermelFirePhysicsModule

__all__ = [
    "FireCellState",
    "FireState",
    "TerrainType",
    "FireEnvironmentState",
    "FirePhysicsModule",        # backward-compat alias for SimpleFirePhysicsModule
    "SimpleFirePhysicsModule",
    "RothermelFirePhysicsModule",
]
