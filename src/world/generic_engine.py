"""
ogar.world.generic_engine

GenericWorldEngine — the domain-agnostic simulation tick loop.

What this does
──────────────
The GenericWorldEngine is the central coordinator.  Each tick:

  1. Environment evolves (tick on EnvironmentState).
  2. Physics module runs (computes StateEvents for cell changes).
  3. StateEvents are applied to the grid.
  4. Ground truth snapshot is recorded.

The engine does NOT:
  - Know what domain it's simulating (fire, ocean, disease, etc.).
  - Interpret cell states or environment values.
  - Know about Kafka, LangGraph, or agents.
  - Publish events to any bus.
  - Run sensors automatically.

Sensors are separate objects managed by SensorInventory.  They
read from the grid/environment when they need a measurement.

Ground truth
────────────
After every tick, the engine records a GenericGroundTruthSnapshot:
  - Environment conditions at that tick
  - What state changes happened (as dicts)
  - A domain-specific summary from the physics module

This is the "answer key" for evaluating agent decisions.
The agent never sees ground truth — it only sees sensor readings.

Reproducibility
───────────────
Set a random seed before running the engine for deterministic results.
This is essential for comparing agent configurations and regression testing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

from world.cell_state import CellState
from world.environment import EnvironmentState
from world.generic_grid import GenericTerrainGrid
from world.physics import PhysicsModule, StateEvent

logger = logging.getLogger(__name__)

C = TypeVar("C", bound=CellState)


# ── Ground truth snapshot ────────────────────────────────────────────────────

@dataclass
class GenericGroundTruthSnapshot:
    """
    What was actually happening in the world at a given tick.

    The agent never sees this.  It is used after the scenario for
    evaluation: comparing what the agent thought was happening to
    what was actually happening.

    tick            : which simulation tick this snapshot is from
    environment     : environment conditions at this tick (from to_dict())
    state_events    : what changed this tick (serialised StateEvents)
    domain_summary  : domain-specific summary from physics.summarize()
    grid_summary    : cell counts by summary_label (e.g. {"BURNING": 5})
    resource_summary: optional resource readiness data, populated by the
                      scenario script or orchestrator (not by the engine).
                      Empty dict when no ResourceInventory is used.
    """
    tick: int
    environment: Dict[str, Any]
    state_events: List[Dict[str, Any]]
    domain_summary: Dict[str, Any]
    grid_summary: Dict[str, int]
    resource_summary: Dict[str, Any] = field(default_factory=dict)


# ── Generic world engine ─────────────────────────────────────────────────────

class GenericWorldEngine(Generic[C]):
    """
    Domain-agnostic simulation coordinator.

    Composes a grid, environment, and physics module.  Runs the
    tick loop and records ground truth.  Never interprets domain-
    specific state.

    Usage
    ─────
      from ogar.domains.wildfire.cell_state import FireCellState
      from ogar.domains.wildfire.environment import FireEnvironmentState
      from ogar.domains.wildfire.physics import FirePhysicsModule

      physics = FirePhysicsModule()
      environment = FireEnvironmentState(temperature_c=35, ...)
      grid = GenericTerrainGrid(rows=10, cols=10,
                                initial_state_factory=physics.initial_cell_state)

      engine = GenericWorldEngine(grid=grid, environment=environment, physics=physics)
      for _ in range(60):
          snapshot = engine.tick()
          print(snapshot.domain_summary)
    """

    def __init__(
        self,
        *,
        grid: GenericTerrainGrid[C],
        environment: EnvironmentState,
        physics: PhysicsModule[C],
    ) -> None:
        """
        Parameters
        ──────────
        grid        : the terrain grid (cells with typed domain state)
        environment : the starting environment conditions
        physics     : the pluggable physics module

        The engine takes ownership of grid and environment — it will
        mutate them on each tick.
        """
        self.grid = grid
        self.environment = environment
        self._physics = physics

        # Current simulation tick.  Starts at 0, incremented after each tick().
        self._tick: int = 0

        # History of ground truth snapshots, one per tick.
        self.history: List[GenericGroundTruthSnapshot] = []

    @property
    def current_tick(self) -> int:
        """The current simulation tick (0-based, incremented after each tick)."""
        return self._tick

    def tick(self) -> GenericGroundTruthSnapshot:
        """
        Advance the simulation by one step.

        Order of operations:
          1. Environment evolves
          2. Physics module computes state events
          3. State events are applied to the grid
          4. Ground truth snapshot is recorded
          5. Tick counter advances

        Returns the ground truth snapshot for this tick.
        """
        # ── 1. Evolve environment ─────────────────────────────────
        self.environment.tick()

        # ── 2. Compute state changes ─────────────────────────────
        state_events: List[StateEvent[C]] = self._physics.tick_physics(
            grid=self.grid,
            environment=self.environment,
            tick=self._tick,
        )

        # ── 3. Apply state events to the grid ────────────────────
        for event in state_events:
            self.grid.update_cell_state(event.row, event.col, event.new_state, event.layer)

        # ── 4. Record ground truth ───────────────────────────────
        domain_summary = self._physics.summarize(self.grid)
        grid_summary = self.grid.summary_counts()

        snapshot = GenericGroundTruthSnapshot(
            tick=self._tick,
            environment=self.environment.to_dict(),
            state_events=[
                {
                    "row": e.row,
                    "col": e.col,
                    "layer": e.layer,
                    "new_state": e.new_state.model_dump(),
                }
                for e in state_events
            ],
            domain_summary=domain_summary,
            grid_summary=grid_summary,
        )
        self.history.append(snapshot)

        # Log a summary line for visibility during demos.
        logger.info(
            "Tick %03d | %s | events=%d",
            self._tick,
            " ".join(f"{k}={v}" for k, v in grid_summary.items()),
            len(state_events),
        )

        # ── 5. Advance tick ──────────────────────────────────────
        self._tick += 1

        return snapshot

    def run(self, ticks: int) -> List[GenericGroundTruthSnapshot]:
        """
        Run the simulation for a fixed number of ticks.

        Convenience method for scenarios that run to completion
        rather than being driven tick-by-tick.
        """
        return [self.tick() for _ in range(ticks)]

    def get_snapshot(self, tick: int) -> Optional[GenericGroundTruthSnapshot]:
        """
        Retrieve the ground truth snapshot for a specific tick.

        Returns None if the tick hasn't been simulated yet.
        """
        if 0 <= tick < len(self.history):
            return self.history[tick]
        return None

    def inject_state(self, row: int, col: int, state: C, layer: int = 0) -> None:
        """
        Manually set a cell's state.

        Used by scenario scripts to set up initial conditions
        (e.g. ignite a cell, place an animal, seed an infection).

        Parameters
        ──────────
        row, col, layer : which cell to modify (layer defaults to 0)
        state           : the new CellState to set
        """
        self.grid.update_cell_state(row, col, state, layer)
        logger.info(
            "Injected state at (%d,%d,%d): %s tick=%d",
            row, col, layer, state.summary_label(), self._tick,
        )
