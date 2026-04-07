"""
ogar.domains.wildfire.physics

SimpleFirePhysicsModule — heuristic fire spread model (placeholder).

This is a simplified probabilistic fire spread model for R&D and agent
testing. It does NOT model real wildfire physics.

See rothermel_physics.py for the physics-based Rothermel model, which
replaces this placeholder and uses real fire behavior equations.

This module is retained for backward compatibility and as a reference
implementation. FirePhysicsModule is an alias for SimpleFirePhysicsModule.

Spread probability factors
───────────────────────────
  base_probability     : starting chance of spread (default 0.15)
  wind_factor          : 0.5 (upwind) to ~2.0 (downwind)
  slope_factor         : 0.7 (downhill) to 1.5 (steep uphill)
  fuel_moisture_factor : 0.1 (saturated) to 1.5 (bone dry)
  vegetation_factor    : 0.0 (bare) to 1.3 (dense)
  humidity_factor      : 0.3 (humid) to 1.4 (dry)
  diagonal_factor      : 0.8 for diagonal neighbors

Final probability = base × wind × slope × fuel_moisture × vegetation × humidity × diagonal
Clamped to [0.0, 0.95].

Burn duration: fixed ticks (default 5).  A cell burns for this many
ticks then transitions to BURNED.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List

from domains.wildfire.cell_state import FireCellState, FireState
from domains.wildfire.environment import FireEnvironmentState
from world.generic_grid import GenericTerrainGrid
from world.physics import PhysicsModule, StateEvent


class SimpleFirePhysicsModule(PhysicsModule[FireCellState]):
    """
    Heuristic fire spread model implementing PhysicsModule[FireCellState].

    See module docstring for detailed explanation of spread factors.
    """

    def __init__(
        self,
        *,
        base_probability: float = 0.15,
        burn_duration_ticks: int = 5,
    ) -> None:
        """
        Parameters
        ──────────
        base_probability    : starting probability of fire spreading to any
                              one neighbor, before environmental factors.
        burn_duration_ticks : how many ticks a cell burns before extinguishing.
        """
        self._base_prob = base_probability
        self._burn_duration = burn_duration_ticks

    def initial_cell_state(self, row: int, col: int, layer: int = 0) -> FireCellState:
        """Return the default cell state — unburned grassland."""
        return FireCellState()

    def tick_physics(
        self,
        grid: GenericTerrainGrid[FireCellState],
        environment: FireEnvironmentState,
        tick: int,
    ) -> List[StateEvent[FireCellState]]:
        """
        Compute one tick of fire spread.

        For each burning cell:
          1. Check burn duration — extinguish if exceeded.
          2. For each unburned burnable neighbor, compute spread
             probability and roll the dice.
        """
        events: List[StateEvent[FireCellState]] = []

        # Pre-compute values used for every burning cell.
        wind_row, wind_col = environment.wind_vector()
        humidity_factor = self._compute_humidity_factor(environment.humidity_pct)

        # Find all currently burning cells.
        burning = grid.cells_where(
            lambda c: c.cell_state.fire_state == FireState.BURNING
        )

        # Track cells ignited this tick to avoid double-ignition.
        newly_ignited: set[tuple[int, int, int]] = set()

        for row, col, _layer in burning:
            cell = grid.get_cell(row, col)
            state = cell.cell_state

            # ── Check burn duration ───────────────────────────────
            if state.fire_start_tick is not None:
                ticks_burning = tick - state.fire_start_tick
                if ticks_burning >= self._burn_duration:
                    events.append(StateEvent(
                        row=row, col=col,
                        new_state=state.extinguished(),
                    ))
                    continue

            # ── Try to spread to each burnable neighbor ───────────
            for nr, nc, _nl in grid.neighbors(row, col):
                if (nr, nc, _nl) in newly_ignited:
                    continue

                neighbor = grid.get_cell(nr, nc)
                neighbor_state = neighbor.cell_state

                if not neighbor_state.is_burnable:
                    continue

                prob = self._spread_probability(
                    row, col, nr, nc,
                    state, neighbor_state,
                    wind_row, wind_col,
                    environment.wind_speed_mps,
                    humidity_factor,
                )

                if random.random() < prob:
                    new_intensity = min(
                        1.0, state.fire_intensity * neighbor_state.vegetation * 1.2
                    )
                    new_intensity = max(0.1, new_intensity)

                    events.append(StateEvent(
                        row=nr, col=nc,
                        new_state=neighbor_state.ignited(tick, new_intensity),
                    ))
                    newly_ignited.add((nr, nc, _nl))

        return events

    def summarize(
        self, grid: GenericTerrainGrid[FireCellState]
    ) -> Dict[str, Any]:
        """
        Return a fire-specific summary of the grid.

        Provides burning_cells list and fire_intensity_map for
        ground truth evaluation.
        """
        burning_cells = []
        intensity_map = []

        for r in range(grid.rows):
            row_intensities = []
            for c in range(grid.cols):
                state = grid.get_cell(r, c).cell_state
                if state.fire_state == FireState.BURNING:
                    burning_cells.append((r, c))
                row_intensities.append(round(state.fire_intensity, 3))
            intensity_map.append(row_intensities)

        counts = grid.summary_counts()
        return {
            "burning_cells": burning_cells,
            "fire_intensity_map": intensity_map,
            "cell_summary": counts,
        }

    # ── Internal spread probability calculation ──────────────────────────────

    def _spread_probability(
        self,
        from_row: int, from_col: int,
        to_row: int, to_col: int,
        from_state: FireCellState,
        to_state: FireCellState,
        wind_row: float, wind_col: float,
        wind_speed: float,
        humidity_factor: float,
    ) -> float:
        """Compute probability of fire spreading from one cell to a neighbor."""
        # ── Wind factor ───────────────────────────────────────────
        dr = to_row - from_row
        dc = to_col - from_col
        dist = math.sqrt(dr * dr + dc * dc)
        if dist > 0:
            dr /= dist
            dc /= dist

        dot = wind_row * dr + wind_col * dc
        wind_influence = dot * min(wind_speed / 10.0, 1.0)
        wind_factor = 1.0 + wind_influence * 0.5
        if dot > 0.5 and wind_speed > 8.0:
            wind_factor *= 1.3

        # ── Slope factor ──────────────────────────────────────────
        slope_deg = to_state.slope
        if slope_deg > 0:
            slope_factor = 1.0 + min(slope_deg / 30.0, 0.5)
        else:
            slope_factor = 1.0 + max(slope_deg / 30.0, -0.3)

        # ── Fuel moisture factor ──────────────────────────────────
        moisture = to_state.fuel_moisture
        fuel_moisture_factor = 1.5 - moisture * 1.4

        # ── Vegetation density factor ─────────────────────────────
        vegetation_factor = to_state.vegetation * 1.3

        # ── Diagonal penalty ──────────────────────────────────────
        is_diagonal = (from_row != to_row) and (from_col != to_col)
        diagonal_factor = 0.8 if is_diagonal else 1.0

        # ── Combine all factors ───────────────────────────────────
        prob = (
            self._base_prob
            * wind_factor
            * slope_factor
            * fuel_moisture_factor
            * vegetation_factor
            * humidity_factor
            * diagonal_factor
        )

        return max(0.0, min(0.95, prob))

    @staticmethod
    def _compute_humidity_factor(humidity_pct: float) -> float:
        """Convert global humidity percentage to a spread multiplier."""
        h = max(0.0, min(100.0, humidity_pct)) / 100.0
        return 1.5 - h * 1.3


# ── Backward compatibility alias ──────────────────────────────────────────────
# Existing code that imports FirePhysicsModule continues to work unchanged.

FirePhysicsModule = SimpleFirePhysicsModule
