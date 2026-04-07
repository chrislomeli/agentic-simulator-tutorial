"""
ogar.world.cell_state

Abstract base class for domain-specific cell states and a generic cell container.

CellState
─────────
Every physics domain defines a concrete subclass of CellState that declares
what data lives on each grid cell.  For example:

  - A wildfire domain defines FireCellState with fire_state, intensity, fuel.
  - An ocean domain defines OceanCellState with current, salinity, temperature.

The framework (grid, engine) never inspects the contents of a CellState —
that is the physics module's job.  The framework only calls summary_label()
for logging.

GenericCell
───────────
A lightweight container that pairs grid coordinates with a typed CellState.
Uses __slots__ because cells are inner-loop objects iterated every tick.
GenericCell is NOT a Pydantic model — keeping it as a plain class avoids
Pydantic v2 generic model pitfalls and keeps the hot path fast.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel


# ── CellState ABC ────────────────────────────────────────────────────────────

class CellState(BaseModel, ABC):
    """
    Base class for all domain-specific cell states.

    Subclasses are Pydantic models, so they get validation, serialisation,
    and schema generation for free.  The only abstract requirement is
    summary_label(), which the engine uses for logging.

    Example
    ───────
      class FireCellState(CellState):
          fire_state: FireState = FireState.UNBURNED
          intensity: float = 0.0

          def summary_label(self) -> str:
              return self.fire_state.value
    """
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(row={self.row}, col={self.col})"


    @abstractmethod
    def summary_label(self) -> str:
        """
        A short string summarising this cell's current state.

        Used by the engine for logging and by ground truth snapshots
        for human-readable summaries.

        Examples: "BURNING", "INFECTED", "OCCUPIED", "IDLE"
        """
        ...


# ── Type variable bound to CellState ─────────────────────────────────────────

C = TypeVar("C", bound=CellState)


# ── GenericCell ──────────────────────────────────────────────────────────────

class GenericCell(Generic[C]):
    """
    A cell in the grid: coordinates + a typed domain state.

    The grid stores a 2D array of these.  The engine and grid never
    inspect cell_state — they pass it to the physics module and apply
    StateEvents returned by the physics module.

    attributes is an optional dict for static per-cell metadata that
    doesn't change during simulation (e.g. geo-coordinates, zone labels).
    """

    __slots__ = ("row", "col", "layer", "cell_state", "attributes")

    def __init__(
        self,
        row: int,
        col: int,
        cell_state: C,
        layer: int = 0,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.row = row
        self.col = col
        self.layer = layer
        self.cell_state = cell_state
        self.attributes = attributes or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for snapshots and logging."""
        return {
            "row": self.row,
            "col": self.col,
            "layer": self.layer,
            "cell_state": self.cell_state.model_dump(),
            "attributes": self.attributes,
        }

    def __repr__(self) -> str:
        return (
            f"GenericCell(row={self.row}, col={self.col}, layer={self.layer}, "
            f"state={self.cell_state.summary_label()})"
        )
