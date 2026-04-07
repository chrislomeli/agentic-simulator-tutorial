"""
ogar.world.generic_grid

GenericTerrainGrid — a domain-agnostic 3D grid of GenericCell objects.

What this is
────────────
The spatial backbone of the simulation.  Each cell has coordinates
(row, col, layer) and a typed CellState that the physics module owns.
The grid knows about topology (neighbors, bounds, iteration) but never
interprets cell state — that is the physics module's job.

Coordinate system
─────────────────
(row, col, layer) where row 0 is the NORTH edge, col 0 is the WEST
edge, and layer 0 is the ground/surface level.  Higher layers are
above, though the physical meaning of layers is domain-defined.

When layers=1 (the default), the grid behaves like a 2D grid with
all layer parameters defaulting to 0.

Construction
────────────
The grid takes an initial_state_factory callable (typically
physics.initial_cell_state) that creates the starting CellState
for each cell.  This means the grid doesn't need to know what
domain it's in — the factory injects the domain.

State changes
─────────────
All cell state changes go through update_cell_state().  The engine
calls this after receiving StateEvents from the physics module.
Nothing else should mutate cell state — this enforces the
"physics returns events, engine applies them" contract.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Generic, Iterator, List, Tuple, TypeVar

from world.cell_state import CellState, GenericCell

C = TypeVar("C", bound=CellState)


class GenericTerrainGrid(Generic[C]):
    """
    Domain-agnostic 3D grid of GenericCell[C] objects.

    Usage
    ─────
      def make_state(row, col, layer=0) -> MyCellState:
          return MyCellState(elevation=row * 0.1)

      grid = GenericTerrainGrid(rows=10, cols=10, layers=1,
                                initial_state_factory=make_state)
      cell = grid.get_cell(3, 4)        # layer defaults to 0
      cell = grid.get_cell(3, 4, 2)     # explicit layer
    """

    def __init__(
        self,
        rows: int,
        cols: int,
        initial_state_factory: Callable[..., C],
        layers: int = 1,
    ) -> None:
        """
        Parameters
        ──────────
        rows                  : number of rows (north-south extent)
        cols                  : number of columns (east-west extent)
        layers                : number of vertical layers (default 1)
        initial_state_factory : callable(row, col, layer) → CellState
                                Called once per cell during construction.
                                Typically physics_module.initial_cell_state.
        """
        if rows < 1 or cols < 1 or layers < 1:
            raise ValueError(
                f"Grid dimensions must be positive, got ({rows}, {cols}, {layers})"
            )
        self.rows = rows
        self.cols = cols
        self.layers = layers
        self._cells: List[List[List[GenericCell[C]]]] = [
            [
                [
                    GenericCell(
                        row=r, col=c, layer=l,
                        cell_state=initial_state_factory(r, c, l),
                    )
                    for l in range(layers)
                ]
                for c in range(cols)
            ]
            for r in range(rows)
        ]

    def get_cell(self, row: int, col: int, layer: int = 0) -> GenericCell[C]:
        """
        Return the GenericCell at (row, col, layer).

        Raises IndexError if out of bounds.
        """
        if not (0 <= row < self.rows and 0 <= col < self.cols
                and 0 <= layer < self.layers):
            raise IndexError(
                f"Cell ({row}, {col}, {layer}) out of bounds for grid "
                f"({self.rows}×{self.cols}×{self.layers})"
            )
        return self._cells[row][col][layer]

    def neighbors(
        self, row: int, col: int, layer: int = 0,
    ) -> List[Tuple[int, int, int]]:
        """
        Return the (row, col, layer) coordinates of all valid neighbors.

        When layers=1: returns the 8-connected horizontal neighbors
        (same as a 2D grid), each as a 3-tuple with layer=0.

        When layers>1: returns up to 26-connected neighbors (the full
        3D Moore neighborhood).

        Only returns coordinates within grid bounds.  Does NOT filter
        by cell state — the caller (physics module) decides which
        neighbors are relevant.
        """
        result = []
        layer_range = (-1, 0, 1) if self.layers > 1 else (0,)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for dl in layer_range:
                    if dr == 0 and dc == 0 and dl == 0:
                        continue
                    nr, nc, nl = row + dr, col + dc, layer + dl
                    if (0 <= nr < self.rows and 0 <= nc < self.cols
                            and 0 <= nl < self.layers):
                        result.append((nr, nc, nl))
        return result

    def update_cell_state(
        self, row: int, col: int, new_state: C, layer: int = 0,
    ) -> None:
        """
        Replace the cell state at (row, col, layer).

        This is the ONLY sanctioned way to change cell state.  The
        engine calls this after receiving StateEvents from the physics
        module.  Physics modules should never call this directly —
        they return StateEvents and let the engine apply them.
        """
        self._cells[row][col][layer].cell_state = new_state

    def iter_cells(self) -> Iterator[GenericCell[C]]:
        """Iterate over all cells in row-major order, then by layer."""
        for row in self._cells:
            for col_cells in row:
                yield from col_cells

    def cells_where(
        self, predicate: Callable[[GenericCell[C]], bool]
    ) -> List[Tuple[int, int, int]]:
        """
        Return (row, col, layer) for all cells matching a predicate.

        Example:
          burning = grid.cells_where(
              lambda c: c.cell_state.fire_state == FireState.BURNING
          )
        """
        return [
            (cell.row, cell.col, cell.layer)
            for cell in self.iter_cells()
            if predicate(cell)
        ]

    def snapshot(self) -> Dict[str, Any]:
        """
        Return a complete serialised snapshot of the grid.

        Used for ground truth recording.  Records every cell's state
        so post-scenario analysis can reconstruct the full grid at
        any tick.
        """
        return {
            "rows": self.rows,
            "cols": self.cols,
            "layers": self.layers,
            "cells": [
                [
                    [
                        self._cells[r][c][l].to_dict()
                        for l in range(self.layers)
                    ]
                    for c in range(self.cols)
                ]
                for r in range(self.rows)
            ],
        }

    def summary_counts(self) -> Dict[str, int]:
        """
        Count cells by their summary_label.

        Returns e.g. {"BURNING": 5, "UNBURNED": 85, "BURNED": 10}
        or {"INFECTED": 20, "HEALTHY": 80} depending on the domain.
        """
        counts: Dict[str, int] = {}
        for cell in self.iter_cells():
            label = cell.cell_state.summary_label()
            counts[label] = counts.get(label, 0) + 1
        return counts
