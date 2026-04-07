"""
ogar.world.physics

Abstract base class for domain-specific physics modules and the
StateEvent data class.

PhysicsModule
─────────────
The physics module is the pluggable heart of a domain.  It defines:

  - What the initial cell state looks like (initial_cell_state)
  - How the world evolves each tick (tick_physics)
  - How to summarise the grid for logging (summarize)

The engine calls tick_physics() each step and gets back a list of
StateEvents.  The engine applies those events to the grid.  The
physics module never mutates the grid directly — the engine is
always in control of state changes.

StateEvent
──────────
A lightweight dataclass that says "cell (row, col) should now have
this new_state."  The engine applies these after each tick.

StateEvent uses Generic[C] for type safety — a fire physics module
produces StateEvent[FireCellState], and the type checker ensures
you don't accidentally mix state types.

StateEvent is a dataclass, not a Pydantic model, because it's
internal plumbing that never crosses a serialisation boundary.
Keeping it lightweight matters — a single tick can produce many
state events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Generic, List, TypeVar

from world.cell_state import CellState

if TYPE_CHECKING:
    from world.environment import EnvironmentState
    from world.generic_grid import GenericTerrainGrid

# ── Type variable ────────────────────────────────────────────────────────────

C = TypeVar("C", bound=CellState)


# ── StateEvent ───────────────────────────────────────────────────────────────

@dataclass
class StateEvent(Generic[C]):
    """
    A single cell state change produced by the physics module.

    The engine applies these to the grid after each tick.
    Physics modules produce them but never apply them directly.

    row, col, layer : which cell changed
    new_state       : the complete new CellState for that cell
    """
    row: int
    col: int
    new_state: C
    layer: int = 0


# ── PhysicsModule ABC ────────────────────────────────────────────────────────

class PhysicsModule(ABC, Generic[C]):
    """
    Abstract contract for domain physics.

    To implement a new domain:
      1. Define a CellState subclass (your domain's cell data)
      2. Define an EnvironmentState subclass (ambient conditions)
      3. Subclass PhysicsModule[YourCellState]
      4. Implement initial_cell_state, tick_physics, summarize
      5. Pass your physics module to GenericWorldEngine

    The module should be stateless between ticks — all state lives
    in the grid and environment.  This makes it safe to swap modules
    mid-simulation if needed (e.g. for A/B testing different models).

    Example
    ───────
      class FirePhysicsModule(PhysicsModule[FireCellState]):
          def initial_cell_state(self, row, col) -> FireCellState:
              return FireCellState()

          def tick_physics(self, grid, environment, tick):
              events = []
              # ... compute spread ...
              events.append(StateEvent(row=r, col=c, new_state=new_fire_state))
              return events

          def summarize(self, grid) -> dict:
              burning = sum(1 for r, c, cell in ... if cell.fire_state == BURNING)
              return {"burning_cells": burning}
    """

    @abstractmethod
    def initial_cell_state(self, row: int, col: int, layer: int = 0) -> C:
        """
        Return the default cell state for a new cell at (row, col, layer).

        Called by GenericTerrainGrid during construction to initialise
        every cell.  The coordinates are provided in case the initial
        state depends on position (e.g. elevation from a terrain map,
        or different state per layer).
        """
        ...

    @abstractmethod
    def tick_physics(
        self,
        grid: GenericTerrainGrid[C],
        environment: EnvironmentState,
        tick: int,
    ) -> List[StateEvent[C]]:
        """
        Compute state changes for one simulation tick.

        Parameters
        ──────────
        grid        : the current grid (read cell states, check neighbors)
        environment : the current environment conditions
        tick        : the current simulation tick number

        Returns
        ───────
        A list of StateEvent objects describing what changed.
        May be empty if nothing happened this tick.

        IMPORTANT: do NOT mutate the grid.  Return StateEvents and
        let the engine apply them.
        """
        ...

    @abstractmethod
    def summarize(self, grid: GenericTerrainGrid[C]) -> Dict[str, Any]:
        """
        Return a domain-specific summary of the current grid state.

        Called by the engine after each tick to populate the
        domain_summary field of GroundTruthSnapshot.

        Example return for fire domain:
          {"burning": 5, "unburned": 85, "burned": 10}

        Example return for ocean domain:
          {"warm_cells": 30, "cold_cells": 70, "avg_salinity": 35.2}
        """
        ...
