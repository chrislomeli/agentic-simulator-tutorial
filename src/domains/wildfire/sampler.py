"""
ogar.domains.wildfire.sampler

Samples local conditions from the world engine at a sensor's grid position.

This is the ONLY place where sensors and the engine connect.  Sensors
themselves are pure reporting devices — they receive a local_conditions
dict and add noise.  The sampler is the bridge.

The publisher holds the sampler (not the sensors) and calls it once per
sensor per tick to produce the local_conditions dict.

Design rationale
────────────────
Real sensors don't have access to the full world state.  A temperature
sensor at position (2,3) can only measure what's happening at (2,3) and
maybe nearby.  By extracting the engine-reading logic into a sampler,
sensors become testable without an engine — just pass a dict.
"""

from __future__ import annotations

import math
from typing import Any

from domains.wildfire.cell_state import FireCellState, FireState
from domains.wildfire.environment import FireEnvironmentState
from world.generic_engine import GenericWorldEngine


def sample_local_conditions(
    engine: GenericWorldEngine[FireCellState],
    grid_row: int,
    grid_col: int,
) -> dict[str, Any]:
    """
    Sample local conditions at (grid_row, grid_col) from the engine.

    Returns a dict with all the information a sensor at that position
    could plausibly observe.  The sensor's read() method picks out
    what it needs.

    Keys returned:
        ambient_temperature_c : float — environment temperature
        humidity_pct          : float — environment relative humidity
        wind_speed_mps        : float — environment wind speed
        wind_direction_deg    : float — environment wind direction (degrees)
        wind_vector           : tuple[float, float] — (row, col) unit vector
        pressure_hpa          : float — environment atmospheric pressure
        own_fire_intensity    : float — fire intensity at this cell (0.0 if not burning)
        own_fire_state        : str — fire state of this cell ("NONE", "BURNING", etc.)
        neighbor_fire_heat    : float — sum of fire intensity from adjacent burning cells
        nearby_fire_cells     : list[dict] — info about each burning cell within a radius
        grid_rows             : int — total grid rows (for thermal camera bounds)
        grid_cols             : int — total grid columns
    """
    env: FireEnvironmentState = engine.environment  # type: ignore[assignment]

    # Own cell state
    own_cell = engine.grid.get_cell(grid_row, grid_col)
    own_state = own_cell.cell_state
    own_fire_intensity = (
        own_state.fire_intensity
        if own_state.fire_state == FireState.BURNING
        else 0.0
    )

    # Heat from neighboring burning cells
    neighbor_fire_heat = 0.0
    for nr, nc, _nl in engine.grid.neighbors(grid_row, grid_col):
        neighbor = engine.grid.get_cell(nr, nc)
        if neighbor.cell_state.fire_state == FireState.BURNING:
            neighbor_fire_heat += neighbor.cell_state.fire_intensity

    # All burning cells in the grid (for smoke dispersion)
    nearby_fire_cells = []
    for cell in engine.grid.iter_cells():
        if cell.cell_state.fire_state == FireState.BURNING:
            dr = grid_row - cell.row
            dc = grid_col - cell.col
            dist = math.sqrt(dr * dr + dc * dc)
            nearby_fire_cells.append({
                "row": cell.row,
                "col": cell.col,
                "intensity": cell.cell_state.fire_intensity,
                "distance": dist,
                "dr": dr,
                "dc": dc,
            })

    return {
        "ambient_temperature_c": env.temperature_c,
        "humidity_pct": env.humidity_pct,
        "wind_speed_mps": env.wind_speed_mps,
        "wind_direction_deg": env.wind_direction_deg,
        "wind_vector": env.wind_vector(),
        "pressure_hpa": env.pressure_hpa,
        "own_fire_intensity": own_fire_intensity,
        "own_fire_state": own_state.fire_state.value,
        "neighbor_fire_heat": neighbor_fire_heat,
        "nearby_fire_cells": nearby_fire_cells,
        "grid_rows": engine.grid.rows,
        "grid_cols": engine.grid.cols,
    }


def sample_thermal_region(
    engine: GenericWorldEngine[FireCellState],
    top_row: int,
    left_col: int,
    view_rows: int,
    view_cols: int,
) -> dict[str, Any]:
    """
    Sample a rectangular region for the thermal camera sensor.

    Returns the same base conditions as sample_local_conditions,
    plus a `cell_grid` with per-cell fire intensity for the region.
    """
    env: FireEnvironmentState = engine.environment  # type: ignore[assignment]

    cell_grid: list[list[dict[str, float]]] = []
    for r in range(top_row, top_row + view_rows):
        row_data: list[dict[str, float]] = []
        for c in range(left_col, left_col + view_cols):
            if 0 <= r < engine.grid.rows and 0 <= c < engine.grid.cols:
                state = engine.grid.get_cell(r, c).cell_state
                fire_intensity = (
                    state.fire_intensity
                    if state.fire_state == FireState.BURNING
                    else 0.0
                )
            else:
                fire_intensity = 0.0
            row_data.append({"fire_intensity": fire_intensity})
        cell_grid.append(row_data)

    return {
        "ambient_temperature_c": env.temperature_c,
        "cell_grid": cell_grid,
        "top_row": top_row,
        "left_col": left_col,
        "view_rows": view_rows,
        "view_cols": view_cols,
    }
