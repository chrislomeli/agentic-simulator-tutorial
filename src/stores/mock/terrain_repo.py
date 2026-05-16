"""Mock terrain repository — loads from terrain.json (10×10 LPNF-south extract)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from stores.base import TerrainConfig
from stores.base import TerrainRepository as TerrainRepositoryBase
from stores.schemas import Terrain
from world.domains.wildfire.cell_state import FireCellState, TerrainType

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "terrain.json"

_TERRAIN_MAP: dict[str, TerrainType] = {
    "FOREST": TerrainType.FOREST,
    "SCRUB": TerrainType.SCRUB,
    "WATER": TerrainType.WATER,
    "URBAN": TerrainType.URBAN,
    "SNOW": TerrainType.SNOW,
    "ROCK": TerrainType.ROCK,
    "GRASSLAND": TerrainType.GRASSLAND,
}


def _load() -> list[dict]:
    return json.loads(_DATA_FILE.read_text())


class MockTerrainRepository(TerrainRepositoryBase):
    def fetch_terrain(
        self,
        region_name: str,
        limit: int | None = None,
    ) -> tuple[dict[tuple[int, int, int], Terrain], TerrainConfig]:
        rows = _load()
        rows = [r for r in rows if r.get("region") == region_name]
        if limit is not None:
            rows = rows[:limit]

        terrain_dict: dict[tuple[int, int, int], Terrain] = {}
        config = TerrainConfig()

        for row in rows:
            record = Terrain.model_validate(row)
            layer = record.layer if record.layer is not None else 0
            key = (record.grid_row, record.grid_column, layer)
            terrain_dict[key] = record

            if config.cell_size_ft is None and record.cell_size_ft:
                config.cell_size_ft = record.cell_size_ft
            if config.time_step_min is None and record.time_step_min:
                config.time_step_min = record.time_step_min
            if config.burn_duration_ticks is None and record.burn_duration_ticks:
                config.burn_duration_ticks = record.burn_duration_ticks

        logger.info("Mock: loaded %d terrain cells for region %r", len(terrain_dict), region_name)
        return terrain_dict, config

    def fetch_cell_location(self, row: int, col: int, layer: int = 0) -> tuple[float, float] | None:
        for r in _load():
            if r["grid_row"] == row and r["grid_column"] == col and r.get("layer", 0) == layer:
                return r["lat"], r["long"]
        return None

    def build_fire_cell_state(self, terrain: Terrain) -> FireCellState:
        terrain_type = _TERRAIN_MAP.get(terrain.terrain or "SCRUB", TerrainType.SCRUB)
        return FireCellState(
            terrain_type=terrain_type,
            vegetation=terrain.vegetation if terrain.vegetation is not None else 0.8,
            fuel_moisture=terrain.fuel_moisture if terrain.fuel_moisture is not None else 0.3,
            slope=terrain.slope if terrain.slope is not None else 0.0,
            temperature_c=terrain.temperature_c if terrain.temperature_c is not None else 30.0,
            humidity_pct=terrain.humidity_pct if terrain.humidity_pct is not None else 25.0,
            wind_speed_mps=terrain.wind_speed_mps if terrain.wind_speed_mps is not None else 5.0,
            wind_direction_deg=terrain.wind_direction_deg
            if terrain.wind_direction_deg is not None
            else 0.0,
            pressure_hpa=terrain.pressure_hpa if terrain.pressure_hpa is not None else 1013.0,
        )
