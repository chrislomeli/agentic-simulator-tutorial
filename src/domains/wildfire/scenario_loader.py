"""
ogar.domains.wildfire.scenario_loader

Load a wildfire scenario from a JSON file and return the three objects
the pipeline needs:

    engine           : GenericWorldEngine[FireCellState]
    sensor_inventory : SensorInventory
    resource_inventory : ResourceInventory

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
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from domains.wildfire.cell_state import FireCellState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire.sensors import (
    BarometricSensor,
    HumiditySensor,
    SmokeSensor,
    TemperatureSensor,
    ThermalCameraSensor,
    WindSensor,
)
from resources.base import ResourceBase
from resources.inventory import ResourceInventory
from world.generic_engine import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid
from world.sensor_inventory import SensorInventory

logger = logging.getLogger(__name__)


# ── Sensor type registry ─────────────────────────────────────────────────────
# Maps JSON "type" string to the sensor class and its constructor kwargs.

_SENSOR_CLASSES: dict[str, type] = {
    "temperature": TemperatureSensor,
    "humidity": HumiditySensor,
    "wind": WindSensor,
    "smoke": SmokeSensor,
    "barometric": BarometricSensor,
    "thermal_camera": ThermalCameraSensor,
}

# ── Terrain type lookup ──────────────────────────────────────────────────────

_TERRAIN_LOOKUP: dict[str, TerrainType] = {t.value: t for t in TerrainType}


def _parse_cell_key(key: str) -> tuple[int, int, int]:
    """Parse a "row,col,layer" or "row,col" key into (row, col, layer)."""
    parts = key.split(",")
    row, col = int(parts[0]), int(parts[1])
    layer = int(parts[2]) if len(parts) > 2 else 0
    return row, col, layer


def _build_sensor(spec: dict[str, Any], row: int, col: int, layer: int):
    """Instantiate a sensor from a JSON spec dict."""
    sensor_type = spec["type"]
    cls = _SENSOR_CLASSES.get(sensor_type)
    if cls is None:
        raise ValueError(
            f"Unknown sensor type '{sensor_type}' at ({row},{col},{layer}). "
            f"Known types: {list(_SENSOR_CLASSES.keys())}"
        )

    # Build kwargs matching SensorBase.__init__
    kwargs: dict[str, Any] = {
        "source_id": spec["id"],
        "cluster_id": spec["cluster"],
        "grid_row": row,
        "grid_col": col,
        "grid_layer": layer if layer != 0 else None,
    }

    # Pass through noise_std if present (most sensors accept it)
    if "noise_std" in spec:
        kwargs["noise_std"] = spec["noise_std"]

    # Pass through any extra kwargs the sensor class accepts
    if "metadata" in spec:
        kwargs["metadata"] = spec["metadata"]

    return cls(**kwargs)


def _build_resource(spec: dict[str, Any], row: int, col: int) -> ResourceBase:
    """Instantiate a ResourceBase from a JSON spec dict."""
    return ResourceBase(
        resource_id=spec["id"],
        resource_type=spec["type"],
        cluster_id=spec["cluster"],
        grid_row=row,
        grid_col=col,
        capacity=spec.get("capacity", 1.0),
        available=spec.get("available", spec.get("capacity", 1.0)),
        mobile=spec.get("mobile", True),
        metadata=spec.get("metadata", {}),
    )


def load_scenario_from_json(
    path: str | Path,
) -> tuple[GenericWorldEngine[FireCellState], SensorInventory, ResourceInventory]:
    """
    Load a wildfire scenario from a JSON file.

    Parameters
    ──────────
    path : Path to the JSON scenario file.

    Returns
    ───────
    (engine, sensor_inventory, resource_inventory) tuple, ready to use
    with the pipeline.

    Raises
    ──────
    FileNotFoundError : if the file doesn't exist
    ValueError        : if the JSON contains invalid data
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with open(path) as f:
        data = json.load(f)

    name = data.get("name", path.stem)
    logger.info("Loading scenario '%s' from %s", name, path)

    # ── Dimensions ───────────────────────────────────────────────
    dims = data["dimensions"]
    rows = dims["rows"]
    cols = dims["cols"]
    layers = dims.get("layers", 1)

    # ── Defaults ─────────────────────────────────────────────────
    defaults = data.get("defaults", {})
    default_terrain = _TERRAIN_LOOKUP.get(
        defaults.get("terrain", "FOREST"), TerrainType.FOREST
    )
    default_vegetation = defaults.get("vegetation", 0.8)
    default_fuel_moisture = defaults.get("fuel_moisture", 0.3)
    default_slope = defaults.get("slope", 0.0)

    # ── Physics ──────────────────────────────────────────────────
    physics_cfg = data.get("physics", {})
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

    # ── Build grid with defaults ─────────────────────────────────
    grid = GenericTerrainGrid(
        rows=rows, cols=cols, layers=layers,
        initial_state_factory=physics.initial_cell_state,
    )

    # Apply default terrain to all cells
    for r in range(rows):
        for c in range(cols):
            for lay in range(layers):
                grid.update_cell_state(r, c, FireCellState(
                    terrain_type=default_terrain,
                    vegetation=default_vegetation,
                    fuel_moisture=default_fuel_moisture,
                    slope=default_slope,
                ), layer=lay)

    # ── Environment ──────────────────────────────────────────────
    env_cfg = data.get("environment", {})
    environment = FireEnvironmentState(
        temperature_c=env_cfg.get("temperature_c", 30.0),
        humidity_pct=env_cfg.get("humidity_pct", 25.0),
        wind_speed_mps=env_cfg.get("wind_speed_mps", 5.0),
        wind_direction_deg=env_cfg.get("wind_direction_deg", 0.0),
        pressure_hpa=env_cfg.get("pressure_hpa", 1013.0),
    )

    # ── Process sparse cells ─────────────────────────────────────
    sensor_inventory = SensorInventory(
        grid_rows=rows, grid_cols=cols, grid_layers=layers,
    )
    resource_inventory = ResourceInventory(grid_rows=rows, grid_cols=cols)

    cells = data.get("cells", {})
    sensor_count = 0
    resource_count = 0
    terrain_overrides = 0

    for key, cell_data in cells.items():
        # Skip comment keys
        if key.startswith("__"):
            continue

        row, col, layer = _parse_cell_key(key)

        # Validate bounds
        if not (0 <= row < rows and 0 <= col < cols and 0 <= layer < layers):
            raise ValueError(
                f"Cell key '{key}' is out of bounds for grid "
                f"({rows}×{cols}×{layers})"
            )

        # ── Terrain override ─────────────────────────────────────
        if "terrain" in cell_data:
            terrain = _TERRAIN_LOOKUP.get(cell_data["terrain"])
            if terrain is None:
                raise ValueError(
                    f"Unknown terrain '{cell_data['terrain']}' at {key}. "
                    f"Known: {list(_TERRAIN_LOOKUP.keys())}"
                )
            grid.update_cell_state(row, col, FireCellState(
                terrain_type=terrain,
                vegetation=cell_data.get("vegetation", default_vegetation),
                fuel_moisture=cell_data.get("fuel_moisture", default_fuel_moisture),
                slope=cell_data.get("slope", default_slope),
            ), layer=layer)
            terrain_overrides += 1

        # ── Sensors ──────────────────────────────────────────────
        for sensor_spec in cell_data.get("sensors", []):
            # Validate: don't place sensors in water
            cell = grid.get_cell(row, col, layer)
            if cell.cell_state.terrain_type == TerrainType.WATER:
                logger.warning(
                    "Sensor '%s' placed in WATER at (%d,%d,%d) — skipping",
                    sensor_spec.get("id", "?"), row, col, layer,
                )
                continue

            sensor = _build_sensor(sensor_spec, row, col, layer)
            sensor_inventory.register_auto(sensor)
            sensor_count += 1

        # ── Resources ────────────────────────────────────────────
        for resource_spec in cell_data.get("resources", []):
            resource = _build_resource(resource_spec, row, col)
            resource_inventory.register(resource)
            resource_count += 1

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
            tick=0, intensity=intensity,
        )
        engine.inject_state(r, c, ignition_state)

    logger.info(
        "Scenario '%s' loaded: %dx%dx%d grid, %d terrain overrides, "
        "%d sensors, %d resources, %d ignition point(s)",
        name, rows, cols, layers, terrain_overrides,
        sensor_count, resource_count, len(data.get("ignition", [])),
    )

    return engine, sensor_inventory, resource_inventory


def load_scenario_from_package(
    scenario_name: str = "north_south_fire",
) -> tuple[GenericWorldEngine[FireCellState], SensorInventory, ResourceInventory]:
    """
    Convenience function to load a scenario from the built-in scenario_data/ directory.

    Parameters
    ──────────
    scenario_name : Name of the scenario file (without .json extension).

    Returns
    ───────
    (engine, sensor_inventory, resource_inventory) tuple.
    """
    scenario_dir = Path(__file__).parent / "scenario_data"
    path = scenario_dir / f"{scenario_name}.json"
    return load_scenario_from_json(path)
