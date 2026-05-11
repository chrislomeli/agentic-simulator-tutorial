"""
domains.wildfire.world_builder.landfire

Translate LANDFIRE raster raw into simulator terrain.

LANDFIRE (https://landfire.gov) is the USGS/USFS national fuels and
vegetation dataset. This module provides:

  load_fuel_grid(path)      — read a vendored fuel-grid JSON produced by
                              the build-fuel-grid CLI tool.
  aggregate_to_sim_grid(…)  — bucket fine LANDFIRE cells onto a coarser sim
                              grid, resolving terrain using a
                              caller-supplied TerrainCalibration.

All region-specific mapping logic lives in the calibration object.
This module has no opinion about which FBFM40 codes map to which
TerrainType — that is the calibration's job.

References
──────────
  * FBFM40: https://www.fs.usda.gov/rm/pubs/rmrs_gtr153.pdf
  * EVT:    https://landfire.gov/evt.php
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field

from agents.commons.geo import latlon_to_grid
from domains.wildfire.world_builder.calibrations import TerrainCalibration
from world.grid import TerrainType


class FuelGridCell(BaseModel):
    """One ~900 m LANDFIRE cell, as emitted by the build-fuel-grid CLI tool."""

    cell_id: int
    lat: float
    lon: float
    fuel_model_code: int
    vegetation_type_code: int | None = None
    canopy_cover: float | None = None


def load_fuel_grid(path: str | Path) -> list[FuelGridCell]:
    """Read a vendored fuel grid into typed FuelGridCell records."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(
            f"Vendored fuel grid not found: {target}\n"
            f"Build it with: build-fuel-grid --region <name>"
        )
    raw = json.loads(target.read_text())
    return [FuelGridCell(**rec) for rec in raw]


class SimCellTerrain(BaseModel):
    """Resolved terrain for one sim-grid cell, ready for scenario JSON."""

    terrain: TerrainType
    vegetation: float = Field(ge=0.0, le=1.0)
    fuel_moisture: float = Field(ge=0.0, le=1.0)
    slope: float = 0.0

    def to_scenario_dict(self) -> dict:
        """Match the loader's per-cell schema (terrain as plain string)."""
        return {
            "terrain": self.terrain.value,
            "vegetation": self.vegetation,
            "fuel_moisture": self.fuel_moisture,
            "slope": self.slope,
        }


def aggregate_to_sim_grid(
    fuel_cells: list[FuelGridCell],
    grid_rows: int,
    grid_cols: int,
    bounds: dict,
    calibration: TerrainCalibration,
    layers: int = 1,
) -> dict[tuple[int, int, int], SimCellTerrain]:
    """
    Bucket fine LANDFIRE cells into sim-grid cells and resolve each
    bucket to a single SimCellTerrain using the supplied calibration.

    Returns
    ───────
    dict keyed by (row, col, layer). Cells that no LANDFIRE record falls
    into are omitted — the scenario builder applies defaults to those.
    """
    buckets: dict[tuple[int, int], list[FuelGridCell]] = defaultdict(list)
    for fc in fuel_cells:
        rc = latlon_to_grid(fc.lat, fc.lon, grid_rows, grid_cols, bounds)
        if rc is None:
            continue
        buckets[rc].append(fc)

    resolved: dict[tuple[int, int, int], SimCellTerrain] = {}
    for (row, col), cells in buckets.items():
        fuel_codes = [c.fuel_model_code for c in cells]
        evt_codes = [c.vegetation_type_code for c in cells if c.vegetation_type_code]
        canopies = [c.canopy_cover for c in cells if c.canopy_cover is not None]

        terrain = calibration.resolve_terrain(fuel_codes, evt_codes)
        canopy_mean = mean(canopies) if canopies else None

        cell = SimCellTerrain(
            terrain=terrain,
            vegetation=calibration.canopy_to_vegetation(canopy_mean),
            fuel_moisture=calibration.fuel_moisture(terrain),
            slope=0.0,
        )
        for lay in range(layers):
            resolved[(row, col, lay)] = cell

    return resolved
