"""
domains.wildfire.world_builder.cli.build_scenario

Build a runtime scenario JSON for any registered region.

Combines:
  * Terrain  — vendored LANDFIRE fuel grid (via aggregate_to_sim_grid)
  * Sensors  — curated RAWS station inventory from the region profile

Writes:
    src/domains/wildfire/scenario_data/{region_name}.json

Usage
─────
    build-scenario --region lpnf-south

The region must be registered in world_builder/raw/regions/ and its fuel
grid must already exist at the path returned by region.fuel_grid_path.
Build the fuel grid first if needed:

    build-fuel-grid --region lpnf-south
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from agents.commons.geo import cell_size_miles
from domains.wildfire.world_builder.landfire import (
    SimCellTerrain,
    aggregate_to_sim_grid,
    load_fuel_grid,
)
from domains.wildfire.world_builder.raws import PlacedRawsStation, place_raws_on_grid
from domains.wildfire.world_builder.regions import RegionProfile, get_region
from world.grid import TerrainType

# ── Per-sensor noise defaults ─────────────────────────────────────────────────
TEMP_NOISE_STD = 0.3
HUMIDITY_NOISE_STD = 0.5

# Dry-season defensible weather defaults for southern California fall fire
# weather. Replace with a live RAWS pull to lock a scenario to a specific date.
DEFAULT_ENVIRONMENT = {
    "temperature_c": 30.0,
    "humidity_pct": 25.0,
    "wind_speed_mps": 8.0,
    "wind_direction_deg": 45.0,  # NE — sundowner-flavored
    "pressure_hpa": 1013.0,
}

PHYSICS = {
    "use_rothermel": True,
    "cell_size_ft": 6336.0,
    "time_step_min": 5.0,
    "burn_duration_ticks": 10,
}

# Maximum search radius (cells) when snapping a station off a water cell.
WATER_SNAP_MAX_RADIUS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────


def _snap_off_water(
    p: PlacedRawsStation,
    terrain_map: dict[tuple[int, int, int], SimCellTerrain],
    max_radius: int = WATER_SNAP_MAX_RADIUS,
) -> PlacedRawsStation:
    """
    Move a station that landed on a WATER cell to the nearest burnable neighbor.

    Coarse sim grids cannot distinguish shoreline from open water — Lake
    Casitas, for example, dominates the cell the CASITAS RAWS coordinates
    fall into even though the instrument is on the bank.
    """
    cell = terrain_map.get((p.row, p.col, 0))
    if cell is None or cell.terrain != TerrainType.WATER:
        return p

    for radius in range(1, max_radius + 1):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if max(abs(dr), abs(dc)) != radius:
                    continue
                neighbor = terrain_map.get((p.row + dr, p.col + dc, 0))
                if neighbor and neighbor.terrain != TerrainType.WATER:
                    return PlacedRawsStation(
                        station=p.station,
                        row=p.row + dr,
                        col=p.col + dc,
                    )
    return p


def _sensors_for_station(p: PlacedRawsStation) -> list[dict]:
    """A RAWS unit emits temp + humidity + wind, all in the same cluster."""
    base = p.station.stid
    return [
        {
            "id": f"{base}-temp",
            "type": "temperature",
            "cluster": p.station.cluster,
            "noise_std": TEMP_NOISE_STD,
            "metadata": {"raws_station": p.station.name},
        },
        {
            "id": f"{base}-humidity",
            "type": "humidity",
            "cluster": p.station.cluster,
            "noise_std": HUMIDITY_NOISE_STD,
            "metadata": {"raws_station": p.station.name},
        },
        {
            "id": f"{base}-wind",
            "type": "wind",
            "cluster": p.station.cluster,
            "metadata": {"raws_station": p.station.name},
        },
    ]


# ── Build ─────────────────────────────────────────────────────────────────────


def build(region: RegionProfile) -> None:
    rows = region.grid_rows
    cols = region.grid_cols

    print(f"Building scenario for region: {region.display_name}")
    print(f"  calibration: {region.calibration.name}")
    print(f"  grid: {rows}x{cols}")
    print(f"  fuel grid: {region.fuel_grid_path}")

    # 1. Terrain — aggregate LANDFIRE onto the sim grid.
    fuel_cells = load_fuel_grid(region.fuel_grid_path)
    terrain_map = aggregate_to_sim_grid(
        fuel_cells,
        grid_rows=rows,
        grid_cols=cols,
        bounds=region.bounds,
        calibration=region.calibration,
    )
    terrain_dist = Counter(c.terrain.value for c in terrain_map.values())
    print(f"\nTerrain: {len(terrain_map)} sim cells covered")
    for t, n in terrain_dist.most_common():
        print(f"  {t}: {n} ({n / len(terrain_map) * 100:.1f}%)")

    # 2. Sensors — place stations, snap off water cells.
    placed_raw = place_raws_on_grid(
        region.raws_stations,
        grid_rows=rows,
        grid_cols=cols,
        bounds=region.bounds,
    )
    placed = [_snap_off_water(p, terrain_map) for p in placed_raw]
    snapped = [
        (orig.station.name, (orig.row, orig.col), (new.row, new.col))
        for orig, new in zip(placed_raw, placed, strict=True)
        if (orig.row, orig.col) != (new.row, new.col)
    ]
    print(f"\nRAWS: {len(placed)}/{len(region.raws_stations)} stations placed")
    if snapped:
        print(f"  snapped off water: {len(snapped)}")
        for name, before, after in snapped:
            print(f"    {name}: {before} → {after}")
    cluster_counts = Counter(p.station.cluster for p in placed)
    for c, n in cluster_counts.most_common():
        print(f"  {c}: {n}")

    # 3. Merge terrain + sensors into the sparse cells dict.
    cells: dict[str, dict] = {}

    for (row, col, layer), terrain in terrain_map.items():
        cells[f"{row},{col},{layer}"] = terrain.to_scenario_dict()

    water_collisions: list[str] = []
    for p in placed:
        key = f"{p.row},{p.col},0"
        cell = cells.setdefault(
            key, {"terrain": "SCRUB", "vegetation": 0.45, "fuel_moisture": 0.12, "slope": 0.0}
        )
        if cell.get("terrain") == "WATER":
            water_collisions.append(p.station.name)
        cell.setdefault("sensors", []).extend(_sensors_for_station(p))

    if water_collisions:
        print("\nWARNING: stations landed on WATER cells — sensors will be skipped at load:")
        for n in water_collisions:
            print(f"  - {n}")

    # 4. Build the scenario document.
    lat_mi, lon_mi = cell_size_miles(rows, cols, region.bounds)
    scenario = {
        "name": region.name,
        "description": (
            f"Real-world {region.display_name} scenario. "
            f"Terrain derived from LANDFIRE FBFM40 + EVT + canopy-cover rasters "
            f"via build-fuel-grid (calibration: {region.calibration.name}). "
            f"Sensors from {len(region.raws_stations)} RAWS stations organized into "
            f"{len(region.clusters)} geographic responsibility clusters."
        ),
        "dimensions": {"rows": rows, "cols": cols, "layers": 1},
        "bounds": region.bounds,
        "_resolution_miles": {"lat": lat_mi, "lon": lon_mi},
        "defaults": {"terrain": "SCRUB", "vegetation": 0.45, "fuel_moisture": 0.12, "slope": 0.0},
        "environment": DEFAULT_ENVIRONMENT,
        "physics": PHYSICS,
        "cells": cells,
        "ignition": [],
    }

    output = region.scenario_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scenario, indent=2))
    print(f"\nWrote {output}")
    print(f"  cells:   {len(cells)}")
    print(f"  sensors: {sum(len(c.get('sensors', [])) for c in cells.values())}")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a wildfire scenario JSON for a registered region."
    )
    parser.add_argument("--region", required=True, help="Region name, e.g. lpnf-south")
    args = parser.parse_args()

    region = get_region(args.region)
    if not region.fuel_grid_path.exists():
        print(f"ERROR: fuel grid not found: {region.fuel_grid_path}")
        print(f"Build it first: build-fuel-grid --region {args.region}")
        sys.exit(1)

    build(region)


if __name__ == "__main__":
    main()
