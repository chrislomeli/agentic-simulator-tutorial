"""
domains.wildfire.world_builder.regions

Per-region configuration for the wildfire world-builder.

A RegionProfile groups everything needed to build a sim world for a
specific geographic area: bounding box, sim-grid dimensions, cluster
scheme, RAWS station inventory, and a reference to the TerrainCalibration
that governs how LANDFIRE codes map to simulator terrain types.

All instance data lives in data/regions/*.json. Adding a new region:
  1. Create data/regions/{name}.json (bbox, grid, clusters, stations,
     calibration reference).
  2. Ensure the referenced calibration exists in data/calibrations/.
  3. Build the fuel grid: build-fuel-grid --region {name}
  4. Build the scenario:  build-scenario --region {name}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from domains.wildfire.world_builder.calibrations import TerrainCalibration, get_calibration
from domains.wildfire.world_builder.raws import RawsStation

_REGION_DATA_DIR = Path(__file__).parent / "data" / "regions"
_SCENARIO_DATA_DIR = Path(__file__).parent.parent / "scenario_data"


@dataclass
class RegionProfile:
    """
    Everything needed to build a sim world for one geographic region.

    Loaded from data/regions/{name}.json — use get_region() to retrieve.
    """

    name: str
    display_name: str
    description: str
    bounds: dict  # lat_min / lat_max / lon_min / lon_max
    grid_rows: int
    grid_cols: int
    clusters: tuple[str, ...]
    raws_stations: tuple[RawsStation, ...]
    calibration: TerrainCalibration

    @property
    def fuel_grid_path(self) -> Path:
        """Conventional path for this region's vendored LANDFIRE grid."""
        return _SCENARIO_DATA_DIR / "landfire" / self.name / "fuel_grid.json"

    @property
    def scenario_path(self) -> Path:
        """Output path for the built scenario JSON."""
        return _SCENARIO_DATA_DIR / f"{self.name}.json"


def _load_region(path: Path) -> RegionProfile:
    raw = json.loads(path.read_text())
    stations = tuple(
        RawsStation(
            stid=s["stid"],
            name=s["name"],
            lat=s["lat"],
            lon=s["lon"],
            cluster=s["cluster"],
        )
        for s in raw["raws_stations"]
    )
    return RegionProfile(
        name=raw["name"],
        display_name=raw.get("display_name", raw["name"]),
        description=raw.get("description", ""),
        bounds=raw["bounds"],
        grid_rows=raw["grid"]["rows"],
        grid_cols=raw["grid"]["cols"],
        clusters=tuple(raw["clusters"]),
        raws_stations=stations,
        calibration=get_calibration(raw["calibration"]),
    )


REGIONS: dict[str, RegionProfile] = {
    _region.name: _region
    for _region in (_load_region(p) for p in sorted(_REGION_DATA_DIR.glob("*.json")))
}


def get_region(name: str) -> RegionProfile:
    """Retrieve a loaded region profile by name."""
    if name not in REGIONS:
        raise KeyError(f"Unknown region: {name!r}. Available: {sorted(REGIONS)}")
    return REGIONS[name]
