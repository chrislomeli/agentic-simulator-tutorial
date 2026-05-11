"""
domains.wildfire.world_builder

Build-time package that converts real-world GIS and sensor raw into
wildfire simulation scenario files.

Pipeline
────────
    LANDFIRE GeoTIFFs ──► build_fuel_grid  ──► landfire/{region}/fuel_grid.json
    Synoptic API      ──► fetch_raws       ──► (verification only)
                                                       │
    region_data JSON ───────────────────────────────────┤
                                                       ▼
                                              build_scenario
                                                       │
                                                       ▼
                                          scenario_data/{region}.json

This package is build-time only. The runtime simulator (scenario_loader,
physics, sensors) does not import from here — it reads the generated
scenario JSON files directly.

CLI entry points (declared in pyproject.toml):
    build-fuel-grid       -- LANDFIRE TIFFs → fuel_grid.json
    build-scenario        -- fuel_grid + region profile → scenario JSON
    fetch-raws-stations   -- Synoptic API verification
"""

from domains.wildfire.world_builder.calibrations import (
    CALIBRATIONS,
    CALIFORNIA_CALIBRATION,
    TerrainCalibration,
    get_calibration,
)
from domains.wildfire.world_builder.landfire import (
    FuelGridCell,
    SimCellTerrain,
    aggregate_to_sim_grid,
    load_fuel_grid,
)
from domains.wildfire.world_builder.raws import (
    PlacedRawsStation,
    RawsStation,
    place_raws_on_grid,
)
from domains.wildfire.world_builder.regions import (
    REGIONS,
    RegionProfile,
    get_region,
)

__all__ = [
    # Calibration
    "TerrainCalibration",
    "CALIBRATIONS",
    "CALIFORNIA_CALIBRATION",
    "get_calibration",
    # Regions
    "RegionProfile",
    "REGIONS",
    "get_region",
    # RAWS
    "RawsStation",
    "PlacedRawsStation",
    "place_raws_on_grid",
    # LANDFIRE
    "FuelGridCell",
    "SimCellTerrain",
    "load_fuel_grid",
    "aggregate_to_sim_grid",
]
