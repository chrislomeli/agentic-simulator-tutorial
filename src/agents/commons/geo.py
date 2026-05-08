"""
agents.commons.geo

Grid-to-real-world coordinate mapping for the world simulator.

Overlays the simulator's abstract grid onto a real geographic bounding box
so that agent tools (NASA FIRMS, NOAA HRRR, USGS elevation) can be called
with real lat/lon coordinates.

All bounding boxes for named regions live in
domains.wildfire.region_data/*.json and are loaded into RegionProfile
instances by domains.wildfire.regions. The functions here are purely
geometric — they work for any bounding box and have no opinion about
which region is "default."

LPNF_SOUTH is retained as a small test area used by unit-test fixtures
and legacy scenario JSON files that do not declare their own bounds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ── Test / legacy bounding box ────────────────────────────────────────────────

# Small 5-station test area covering Ojai, Sespe Wilderness, Mt Pinos.
# Used only by test fixtures and legacy scenario JSON that does not declare
# its own bounds. Do not use this for the full simulation.
LPNF_SOUTH: dict = {
    "name": "Los Padres National Forest (South — test area)",
    "lat_min": 34.4,
    "lat_max": 34.9,
    "lon_min": -119.3,
    "lon_max": -118.7,
}


# ── Coordinate type ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LatLon:
    """
    A real-world coordinate pair.

    Frozen so it can be used as a dict key or stored in cell attributes
    without accidental mutation.
    """

    lat: float
    lon: float

    def __str__(self) -> str:
        return f"{self.lat:.4f}°N, {abs(self.lon):.4f}°W"

    def as_tuple(self) -> tuple[float, float]:
        """Returns (lat, lon) for passing to external APIs."""
        return (self.lat, self.lon)


# ── Core functions ────────────────────────────────────────────────────────────


def grid_to_latlon(
    row: int,
    col: int,
    grid_rows: int,
    grid_cols: int,
    bounds: dict,
) -> LatLon:
    """
    Convert a grid cell (row, col) to a real-world LatLon coordinate.

    Returns the coordinate of the CENTER of the cell, not its corner.

    Orientation:
      - Row 0 is the NORTHERN edge of the bounding box
      - Row grid_rows-1 is the SOUTHERN edge
      - Col 0 is the WESTERN edge
      - Col grid_cols-1 is the EASTERN edge

    Parameters
    ──────────
    row       : grid row index (0 = north)
    col       : grid column index (0 = west)
    grid_rows : total number of rows in the grid
    grid_cols : total number of columns in the grid
    bounds    : bounding box dict with lat_min/lat_max/lon_min/lon_max.
    """
    cell_lat = (bounds["lat_max"] - bounds["lat_min"]) / grid_rows
    cell_lon = (bounds["lon_max"] - bounds["lon_min"]) / grid_cols

    lat = bounds["lat_max"] - (row + 0.5) * cell_lat
    lon = bounds["lon_min"] + (col + 0.5) * cell_lon

    return LatLon(lat=round(lat, 6), lon=round(lon, 6))


def cell_size_miles(
    grid_rows: int,
    grid_cols: int,
    bounds: dict,
) -> tuple[float, float]:
    """
    Return the approximate size of each cell in miles (lat_miles, lon_miles).

    At mid-latitude (~34.7°N for southern California):
      1° latitude  ≈ 69.0 miles  (constant)
      1° longitude ≈ 56.7 miles  (varies with cos(lat))

    Parameters
    ──────────
    grid_rows : total number of rows
    grid_cols : total number of columns
    bounds    : bounding box dict.
    """
    mid_lat = (bounds["lat_min"] + bounds["lat_max"]) / 2.0

    lat_miles = (bounds["lat_max"] - bounds["lat_min"]) / grid_rows * 69.0
    lon_miles = (
        (bounds["lon_max"] - bounds["lon_min"]) / grid_cols * 69.0 * math.cos(math.radians(mid_lat))
    )

    return round(lat_miles, 2), round(lon_miles, 2)


def latlon_to_grid(
    lat: float,
    lon: float,
    grid_rows: int,
    grid_cols: int,
    bounds: dict,
) -> tuple[int, int] | None:
    """
    Inverse of grid_to_latlon — convert a real-world coordinate to the
    nearest grid cell (row, col).

    Returns None if the coordinate falls outside the bounding box.

    Parameters
    ──────────
    lat       : latitude in decimal degrees
    lon       : longitude in decimal degrees
    grid_rows : total number of rows in the grid
    grid_cols : total number of columns in the grid
    bounds    : bounding box dict.
    """
    if not (bounds["lat_min"] <= lat <= bounds["lat_max"]):
        return None
    if not (bounds["lon_min"] <= lon <= bounds["lon_max"]):
        return None

    cell_lat = (bounds["lat_max"] - bounds["lat_min"]) / grid_rows
    cell_lon = (bounds["lon_max"] - bounds["lon_min"]) / grid_cols

    row = int((bounds["lat_max"] - lat) / cell_lat)
    col = int((lon - bounds["lon_min"]) / cell_lon)

    row = max(0, min(grid_rows - 1, row))
    col = max(0, min(grid_cols - 1, col))

    return row, col
