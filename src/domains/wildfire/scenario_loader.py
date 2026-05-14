"""
world-simiulator.domains.wildfire.scenario_loader

Load a wildfire scenario from the database and return the objects
the pipeline needs:

    engine           : GenericWorldEngine[FireCellState]
    sensor_inventory : SensorInventory

All terrain and sensor data is read from the database (TerrainRepository,
SensorRepository).  There are no JSON files at runtime.

Grid dimensions are derived from the terrain rows in the DB — the largest
(grid_row, grid_column) values determine the grid size, so there is no
separate dimension config to keep in sync.

Geo overlay
───────────
Every cell is stamped with real-world lat/lon coordinates that come
directly from the terrain table (terrain.lat / terrain.long columns).
Cells not covered by the DB fall back to grid_to_latlon() using the
bounds dict.

Physics defaults
────────────────
The DB terrain table carries cell_size_ft / time_step_min /
burn_duration_ticks on every row.  The first non-null values found
become the physics config.  Hardcoded fallbacks are used only when
the DB has no values for a field.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.commons.geo import (
    LPNF_SOUTH,
    cell_size_miles,
    grid_to_latlon,
)
from domains.wildfire.cell_state import FireCellState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from world import GenericWorldEngine, SensorInventory
from world.generic_engine import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid
from world.sensor_inventory import SensorInventory
from stores.pg_gateway import PgGateway
from stores.sensor_repo import SensorRepository
from stores.terrain_repo import TerrainRepository


logger = logging.getLogger(__name__)

# ── Fallback defaults (used only when DB has no value) ───────────────────────

_DEFAULT_TERRAIN = TerrainType.SCRUB
_DEFAULT_VEGETATION = 0.45
_DEFAULT_FUEL_MOISTURE = 0.12
_DEFAULT_SLOPE = 0.0

_DEFAULT_CELL_SIZE_FT = 6336.0
_DEFAULT_TIME_STEP_MIN = 5.0
_DEFAULT_BURN_DURATION_TICKS = 10

_DEFAULT_ENVIRONMENT = dict(
    temperature_c=30.0,
    humidity_pct=25.0,
    wind_speed_mps=8.0,
    wind_direction_deg=45.0,
    pressure_hpa=1013.0,
)


def load_scenario_from_db(
    region_name: str,
    pg_gateway: PgGateway,
    bounds: dict = LPNF_SOUTH,
    ignition_points: list[dict[str, Any]] | None = None,
    layers: int = 1,
    use_rothermel: bool = True,
) -> tuple[GenericWorldEngine[FireCellState], SensorInventory]:
    """
    Build a wildfire engine and sensor inventory entirely from the database.

    Parameters
    ──────────
    region_name      : DB region key (e.g. 'lpnf-south').
    pg_gateway       : Open PgGateway connection.
    bounds           : Geographic bounding box used as a fallback for cells
                       not in the DB.  Defaults to southern Los Padres NF.
    ignition_points  : Optional list of dicts with keys row, col, layer
                       (default 0), intensity (default 0.8).  Pass [] or
                       None for no ignition (useful for eval/test scenarios).
    layers           : Number of grid layers (default 1).
    use_rothermel    : When True (default) use RothermelFirePhysicsModule;
                       when False use SimpleFirePhysicsModule.

    Returns
    ───────
    (engine, sensor_inventory) tuple ready to hand to RuntimeOrchestrator.

    Raises
    ──────
    ValueError : if the DB returns no terrain rows for the region.
    """
    ignition_points = ignition_points or []

    # ── Load terrain from DB ─────────────────────────────────────
    terrain_repo = TerrainRepository(pg_gateway)
    terrain_dict, terrain_config = terrain_repo.fetch_terrain(region_name)

    if not terrain_dict:
        raise ValueError(
            f"No terrain rows found in DB for region {region_name!r}. "
            "Run the data pipeline to seed the terrain table first."
        )

    # ── Derive grid dimensions from DB rows ──────────────────────
    max_row = max(k[0] for k in terrain_dict) + 1
    max_col = max(k[1] for k in terrain_dict) + 1
    rows, cols = max_row, max_col

    logger.info(
        "Loaded %d terrain cells for region %r — grid %dx%d",
        len(terrain_dict),
        region_name,
        rows,
        cols,
    )

    lat_miles, lon_miles = cell_size_miles(rows, cols, bounds)
    logger.info(
        "Grid overlaid on bounds — %dx%d cells, each ~%.1f x %.1f miles",
        rows,
        cols,
        lat_miles,
        lon_miles,
    )

    # ── Physics — DB values win, hardcoded fallbacks used when absent ─
    cell_size_ft = terrain_config.cell_size_ft or _DEFAULT_CELL_SIZE_FT
    time_step_min = terrain_config.time_step_min or _DEFAULT_TIME_STEP_MIN
    burn_duration_ticks = terrain_config.burn_duration_ticks or _DEFAULT_BURN_DURATION_TICKS

    if use_rothermel:
        from domains.wildfire.rothermel_physics import RothermelFirePhysicsModule

        physics = RothermelFirePhysicsModule(
            cell_size_ft=cell_size_ft,
            time_step_min=time_step_min,
            burn_duration_ticks=burn_duration_ticks,
        )
    else:
        from domains.wildfire.physics import SimpleFirePhysicsModule

        physics = SimpleFirePhysicsModule(
            base_probability=0.15,
            burn_duration_ticks=burn_duration_ticks,
        )

    # ── Build grid ───────────────────────────────────────────────
    grid = GenericTerrainGrid(
        rows=rows,
        cols=cols,
        layers=layers,
        initial_state_factory=physics.initial_cell_state,
    )

    for r in range(rows):
        for c in range(cols):
            for lay in range(layers):
                if (r, c, lay) in terrain_dict:
                    record = terrain_dict[(r, c, lay)]
                    fire_state = terrain_repo.build_fire_cell_state(record)
                    lat = record.lat
                    lon = record.long
                else:
                    fire_state = FireCellState(
                        terrain_type=_DEFAULT_TERRAIN,
                        vegetation=_DEFAULT_VEGETATION,
                        fuel_moisture=_DEFAULT_FUEL_MOISTURE,
                        slope=_DEFAULT_SLOPE,
                    )
                    latlon = grid_to_latlon(r, c, rows, cols, bounds)
                    lat, lon = latlon.lat, latlon.lon

                grid.update_cell_state(r, c, fire_state, layer=lay)
                cell = grid.get_cell(r, c, lay)
                cell.attributes["lat"] = lat
                cell.attributes["lon"] = lon

    # ── Environment ──────────────────────────────────────────────
    environment = FireEnvironmentState(**_DEFAULT_ENVIRONMENT)

    # ── Load sensors from DB ─────────────────────────────────────
    sensor_repo = SensorRepository(pg_gateway)
    all_sensors = sensor_repo.fetch_sensors(
        region_name=region_name,
        grid_rows=rows,
        grid_cols=cols,
        grid_layers=layers,
    )

    sensor_inventory = SensorInventory(
        grid_rows=rows,
        grid_cols=cols,
        grid_layers=layers,
        validate_bounds=False,
    )
    skipped = 0
    for sensor in all_sensors.all_sensors():
        if grid.register_layer(
            sensor.source_id, sensor.grid_row, sensor.grid_col, sensor.grid_layer, warn=True
        ):
            sensor_inventory.register_auto(sensor)
        else:
            skipped += 1

    if skipped:
        logger.warning("Skipped %d sensors outside terrain grid bounds", skipped)

    # ── Build engine ─────────────────────────────────────────────
    engine = GenericWorldEngine(
        grid=grid,
        environment=environment,
        physics=physics,
    )

    # ── Apply ignition points ────────────────────────────────────
    for ign in ignition_points:
        r = ign["row"]
        c = ign["col"]
        lay = ign.get("layer", 0)
        intensity = ign.get("intensity", 0.8)
        ignition_state = grid.get_cell(r, c, lay).cell_state.ignited(
            tick=0,
            intensity=intensity,
        )
        engine.inject_state(r, c, ignition_state)

    logger.info(
        "Scenario '%s' loaded: %dx%dx%d grid, %d sensors, %d ignition point(s)",
        region_name,
        rows,
        cols,
        layers,
        sensor_inventory.size,
        len(ignition_points),
    )

    return engine, sensor_inventory


def load_scenario_from_package(
    pg_gateway: PgGateway,
    region_name: str = "lpnf-south",
    bounds: dict = LPNF_SOUTH,
    ignition_points: list[dict[str, Any]] | None = None,
) -> tuple[GenericWorldEngine[FireCellState], SensorInventory]:
    """
    Convenience wrapper — load a named region from the DB.

    Parameters
    ──────────
    pg_gateway      : Open PgGateway connection.
    region_name     : DB region key (default 'lpnf-south').
    bounds          : Geographic bounding box fallback.
    ignition_points : Optional ignition list (see load_scenario_from_db).

    Returns
    ───────
    (engine, sensor_inventory) tuple.
    """
    return load_scenario_from_db(
        region_name=region_name,
        pg_gateway=pg_gateway,
        bounds=bounds,
        ignition_points=ignition_points,
    )
