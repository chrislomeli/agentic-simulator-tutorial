"""
world-simiulator.domains.wildfire.scenario_loader

Load a wildfire scenario from a JSON file and return the three objects
the pipeline needs:

    engine           : GenericWorldEngine[FireCellState]
    sensor_inventory : SensorInventory
    resource_inventory : ResourceInventory
    risk_heat_map    : RiskHeatMap (initialized with baseline risk=0)

JSON format
───────────
The JSON file is a cell-centric sparse grid.  See scenario_data/ for
examples.  Key sections:

  dimensions   : {"rows": 20, "cols": 20, "layers": 1}
  defaults     : terrain/vegetation/fuel_moisture/slope for unlisted cells
  environment  : weather conditions (temperature, humidity, wind, pressure)
  physics      : engine configuration (use_rothermel, cell_size_ft, etc.)
  cells        : sparse dict keyed by "row,col,layer" with per-cell overrides
  ignition     : list of ignition points with row/col/layer/intensity

Cells can contain:
  - terrain overrides (terrain, vegetation, fuel_moisture, slope)
  - sensors (list of sensor specs)
  - resources (list of resource specs)
  - all three at once (the whole point: everything at a position is together)

Keys starting with "__comment" are ignored (used for documentation in JSON).

Geo overlay
───────────
Every cell is stamped with real-world lat/lon coordinates derived from the
grid position using agents.commons.geo.grid_to_latlon. Coordinates are
stored in GenericCell.attributes["lat"] and GenericCell.attributes["lon"]
so that agent tools (NASA FIRMS, NOAA HRRR, USGS elevation) can be called
with real coordinates without any runtime conversion.

The default bounding box is southern Los Padres National Forest
(Ventura/Santa Barbara counties). Pass a different bounds dict to
load_scenario_from_json to overlay on a different region.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agents.commons.geo import (
    LPNF_SOUTH,
    cell_size_miles,
    grid_to_latlon,
)
from domains.wildfire.cell_state import FireCellState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from world.generic_engine import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid
from world.sensor_inventory import SensorInventory

# Optional: DB-backed sensor/resource loading
from stores.pg_gateway import PgGateway
from stores.sensor_repo import SensorRepository
from stores.terrain_repo import TerrainRepository
from world.risk_heat_map import RiskHeatMap, create_risk_heat_map

logger = logging.getLogger(__name__)


# ── Terrain type lookup ──────────────────────────────────────────────────────

_TERRAIN_LOOKUP: dict[str, TerrainType] = {t.value: t for t in TerrainType}


def _resolve_bounds(spec: dict | None, fallback: dict) -> dict:
    """
    Resolve the scenario's bounding box.

    The JSON `bounds` value must be a dict with the four edge keys, or absent
    (fallback is used). Build-time tooling (build-scenario CLI) is responsible
    for embedding the dict — string region names are not supported at runtime.
    """
    if spec is None:
        return fallback
    required = {"lat_min", "lat_max", "lon_min", "lon_max"}
    missing = required - set(spec)
    if missing:
        raise ValueError(f"Scenario `bounds` dict is missing keys: {sorted(missing)}")
    return spec


# ── Scenario inheritance (`extends:`) ────────────────────────────────────────
#
# A scenario file may declare `"extends": "<scenario-name>"` to inherit from
# a sibling scenario in the same directory. The derivative file becomes a
# small overlay — typically environment tweaks plus an ignition — instead
# of duplicating thousands of cell entries from the baseline.
#
# Merge rules (per top-level field):
#
#   cells           ── union; derivative entries override base entries by key
#   ignition        ── append; derivative ignitions added to base ignitions
#   dict fields     ── shallow merge; derivative keys win
#                      (environment, physics, defaults, dimensions, bounds)
#   scalar fields   ── replace; derivative wins if present
#                      (name, description)
#
# Inheritance is resolved depth-first before the rest of the loader runs,
# so the loader sees a single fully-merged dict and remains unaware of
# whether the file inherits.

_DICT_MERGE_KEYS = frozenset(
    {"environment", "physics", "defaults", "dimensions", "bounds"}
)


def _merge_scenarios(base: dict[str, Any], derivative: dict[str, Any]) -> dict[str, Any]:
    """Merge a derivative scenario dict on top of a base scenario dict."""
    result: dict[str, Any] = dict(base)
    for key, value in derivative.items():
        if key == "extends":
            continue  # already resolved by _resolve_extends
        if key == "cells":
            merged = dict(base.get("cells", {}))
            merged.update(value)
            result[key] = merged
        elif key == "ignition":
            base_list = list(base.get("ignition", []) or [])
            base_list.extend(value or [])
            result[key] = base_list
        elif key in _DICT_MERGE_KEYS and isinstance(value, dict) and isinstance(
            base.get(key), dict
        ):
            merged = dict(base[key])
            merged.update(value)
            result[key] = merged
        else:
            result[key] = value
    return result


def _resolve_extends(
    data: dict[str, Any],
    base_dir: Path,
    _seen: set[Path] | None = None,
) -> dict[str, Any]:
    """Resolve any `extends:` chain, returning a fully merged scenario dict.

    The `extends` field, when present, is a scenario name (without `.json`)
    located in the same directory. Resolution is depth-first and detects
    cycles by resolved file path.
    """
    if "extends" not in data:
        return data

    parent_name = data["extends"]
    parent_path = (base_dir / f"{parent_name}.json").resolve()

    if not parent_path.exists():
        raise FileNotFoundError(
            f"Scenario '{data.get('name', '?')}' extends '{parent_name}', "
            f"but no such file exists at {parent_path}"
        )

    seen = set(_seen or set())
    if parent_path in seen:
        chain = " -> ".join(sorted(str(p) for p in seen)) + f" -> {parent_path}"
        raise ValueError(f"Circular `extends` chain detected: {chain}")
    seen.add(parent_path)

    with open(parent_path) as f:
        parent_data = json.load(f)

    parent_data = _resolve_extends(parent_data, parent_path.parent, _seen=seen)
    return _merge_scenarios(parent_data, data)


def load_scenario_from_json(
    path: str | Path,
    pg_gateway: PgGateway,
    bounds: dict = LPNF_SOUTH,
) -> tuple[GenericWorldEngine[FireCellState], SensorInventory]:
    """
    Load a wildfire scenario from a JSON file.

    A scenario may declare ``"extends": "<scenario-name>"`` to inherit from
    a sibling scenario in the same directory. The derivative becomes a small
    overlay (typically environment tweaks plus an ignition) and the merged
    result is what this function loads. See ``_resolve_extends`` for merge
    semantics.

    Parameters
    ──────────
    path   : Path to the JSON scenario file.
    bounds : Geographic bounding box to overlay the grid onto.
             Defaults to southern Los Padres National Forest.
             Pass a different dict with lat_min/lat_max/lon_min/lon_max
             to overlay on a different region.

    Returns
    ───────
    (engine, sensor_inventory, resource_inventory) tuple, ready to use
    with the pipeline.

    Raises
    ──────
    FileNotFoundError : if the file (or any extends parent) doesn't exist
    ValueError        : if the JSON contains invalid raw, or an `extends`
                        chain forms a cycle
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with open(path) as f:
        data = json.load(f)

    # Resolve any `extends:` inheritance chain before the loader runs.
    # See `_resolve_extends` for merge semantics.
    data = _resolve_extends(data, path.parent, _seen={path.resolve()})

    name = data.get("name", path.stem)
    logger.info("Loading scenario '%s' from %s", name, path)

    # ── Bounds ───────────────────────────────────────────────────
    # A scenario may declare its own geographic region inline (preferred —
    # keeps the file self-describing). The function-arg `bounds` is a
    # fallback used only when the JSON does not declare anything.
    bounds = _resolve_bounds(data.get("bounds"), bounds)

    # ── Dimensions ───────────────────────────────────────────────
    dims = data["dimensions"]
    rows = dims["rows"]
    cols = dims["cols"]
    layers = dims.get("layers", 1)

    # ── Log geo overlay resolution ───────────────────────────────
    lat_miles, lon_miles = cell_size_miles(rows, cols, bounds)
    logger.info(
        "Grid overlaid on '%s' — %dx%d cells, each ~%.1f x %.1f miles",
        name,
        rows,
        cols,
        lat_miles,
        lon_miles,
    )

    # ── Terrain loading from DB ─────────────────────────────────────────
    region_name = data.get("region", path.stem)
    terrain_repo = TerrainRepository(pg_gateway)
    terrain_dict, terrain_config = terrain_repo.fetch_terrain(region_name)

    # ── Defaults (fallback when DB terrain missing cells) ────────────
    defaults = data.get("defaults", {})
    default_terrain = _TERRAIN_LOOKUP.get(defaults.get("terrain", "FOREST"), TerrainType.FOREST)
    default_vegetation = defaults.get("vegetation", 0.8)
    default_fuel_moisture = defaults.get("fuel_moisture", 0.3)
    default_slope = defaults.get("slope", 0.0)

    # ── Physics ──────────────────────────────────────────────────
    physics_cfg = data.get("physics", {})
    # Override with terrain DB config if available
    if terrain_config:
        if terrain_config.cell_size_ft:
            physics_cfg["cell_size_ft"] = terrain_config.cell_size_ft
        if terrain_config.time_step_min:
            physics_cfg["time_step_min"] = terrain_config.time_step_min
        if terrain_config.burn_duration_ticks:
            physics_cfg["burn_duration_ticks"] = terrain_config.burn_duration_ticks
    use_rothermel = physics_cfg.get("use_rothermel", True)
    cell_size_ft = physics_cfg.get("cell_size_ft", 200.0)
    time_step_min = physics_cfg.get("time_step_min", 5.0)
    burn_duration_ticks = physics_cfg.get("burn_duration_ticks", 5)

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

    # ── Build grid with DB terrain ──────────────────────────────
    grid = GenericTerrainGrid(
        rows=rows,
        cols=cols,
        layers=layers,
        initial_state_factory=physics.initial_cell_state,
    )

    # Apply terrain to all cells (DB terrain with JSON defaults for missing cells)
    for r in range(rows):
        for c in range(cols):
            for lay in range(layers):
                # Use DB terrain if available
                if (r, c, lay) in terrain_dict:
                    terrain_record = terrain_dict[(r, c, lay)]
                    fire_state = terrain_repo.build_fire_cell_state(terrain_record)
                    lat = terrain_record.lat
                    lon = terrain_record.long
                else:
                    # Fallback to JSON defaults for missing cells
                    fire_state = FireCellState(
                        terrain_type=default_terrain,
                        vegetation=default_vegetation,
                        fuel_moisture=default_fuel_moisture,
                        slope=default_slope,
                    )
                    latlon = grid_to_latlon(r, c, rows, cols, bounds)
                    lat, lon = latlon.lat, latlon.lon

                grid.update_cell_state(r, c, fire_state, layer=lay)

                # Stamp real-world coordinates into GenericCell.attributes
                cell = grid.get_cell(r, c, lay)
                cell.attributes["lat"] = lat
                cell.attributes["lon"] = lon

    # ── Environment ──────────────────────────────────────────────
    env_cfg = data.get("environment", {})
    environment = FireEnvironmentState(
        temperature_c=env_cfg.get("temperature_c", 30.0),
        humidity_pct=env_cfg.get("humidity_pct", 25.0),
        wind_speed_mps=env_cfg.get("wind_speed_mps", 5.0),
        wind_direction_deg=env_cfg.get("wind_direction_deg", 0.0),
        pressure_hpa=env_cfg.get("pressure_hpa", 1013.0),
    )

    # ── Load sensors from DB ─────────────────────────────────────
    # Grid dimensions come from terrain data (not JSON), validate sensors fit
    sensor_repo = SensorRepository(pg_gateway)
    all_sensors = sensor_repo.fetch_sensors(
        region_name=region_name,
        grid_rows=rows,
        grid_cols=cols,
        grid_layers=layers,
    )

    # Filter sensors to grid bounds using register_layer validation
    sensor_inventory = SensorInventory(
        grid_rows=rows,
        grid_cols=cols,
        grid_layers=layers,
        validate_bounds=False,
    )
    skipped = 0
    for sensor in all_sensors.all_sensors():
        pos = sensor.location
        if grid.register_layer(sensor.source_id, pos.row, pos.col, pos.layer, warn=True):
            sensor_inventory.register_auto(sensor)
        else:
            skipped += 1

    sensor_count = sensor_inventory.size
    if skipped:
        logger.warning("Skipped %d sensors outside terrain grid bounds", skipped)

    # ── Build engine ─────────────────────────────────────────────
    engine = GenericWorldEngine(
        grid=grid,
        environment=environment,
        physics=physics,
    )

    # ── Apply ignition points ────────────────────────────────────
    for ign in data.get("ignition", []):
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
        name,
        rows,
        cols,
        layers,
        sensor_count,
        len(data.get("ignition", [])),
    )

    # ── Initialize Risk Heat Map ─────────────────────────────────
    # Grid-aligned layer for supervisor/resource agent queries
    # Initialized with baseline risk=0 for all cells
    risk_heat_map = create_risk_heat_map(rows=rows, cols=cols, layers=layers)
    
    return engine, sensor_inventory, risk_heat_map


def load_scenario_from_package(
    pg_gateway: PgGateway,
    scenario_name: str = "north_south_fire",
    bounds: dict = LPNF_SOUTH,
) -> tuple[GenericWorldEngine[FireCellState], SensorInventory, RiskHeatMap]:
    """
    Convenience function to load a scenario from the built-in scenario_data/ directory.

    Parameters
    ──────────
    pg_gateway    : PgGateway for DB-backed terrain and sensor loading (required).
    scenario_name : Name of the scenario file (without .json extension).
    bounds        : Geographic bounding box. Defaults to southern Los Padres.

    Returns
    ───────
    (engine, sensor_inventory, risk_heat_map) tuple.
    """
    scenario_dir = Path(__file__).parent / "scenario_data"
    path = scenario_dir / f"{scenario_name}.json"
    return load_scenario_from_json(path, pg_gateway=pg_gateway, bounds=bounds)
