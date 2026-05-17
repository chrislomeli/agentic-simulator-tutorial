"""Terrain repository — loads terrain from database for grid initialization."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from domains.wildfire.cell_state import FireCellState, TerrainType
from stores.pg_gateway import PgGateway
from stores.schemas import Terrain

logger = logging.getLogger(__name__)

# Map DB terrain strings to TerrainType enum
_TERRAIN_MAP: dict[str, TerrainType] = {
    "FOREST": TerrainType.FOREST,
    "SCRUB": TerrainType.SCRUB,
    "WATER": TerrainType.WATER,
    "URBAN": TerrainType.URBAN,
    "SNOW": TerrainType.SNOW,
}


@dataclass
class TerrainConfig:
    """Physics configuration from terrain table (optional overrides)."""

    cell_size_ft: float | None = None
    time_step_min: float | None = None
    burn_duration_ticks: int | None = None


class TerrainRepository:
    """Loads terrain definitions from DB for grid population."""

    def __init__(self, pg_gateway: PgGateway):
        self._pg = pg_gateway

    def fetch_terrain(
        self,
        region_name: str,
        limit: int | None = None,
    ) -> tuple[dict[tuple[int, int, int], Terrain], TerrainConfig]:
        """Load terrain cells for a region.

        Parameters
        ----------
        region_name : e.g. 'lpnf_south', 'lpnf_north'
        limit : Optional max cells to load (defensive, default None = all)

        Returns
        -------
        (terrain_dict, terrain_config) where:
            terrain_dict: {(row, col, layer): Terrain} for all cells
            terrain_config: Physics defaults from terrain table (may be None)
        """
        sql = """
            select
                grid_column,
                grid_row,
                layer,
                cell_key,
                terrain,
                vegetation,
                fuel_moisture,
                slope,
                cell_size_ft,
                time_step_min,
                burn_duration_ticks,
                lat,
                long,
                location,
                region,
                temperature_c,
                humidity_pct,
                wind_speed_mps,
                wind_direction_deg,
                pressure_hpa
            from terrain
            where region = %s
            order by grid_row, grid_column, layer
        """
        params: tuple = (region_name,)
        if limit is not None:
            sql += " limit %s"
            params = (region_name, limit)

        rows = self._pg.fetch_rows(sql, params)

        terrain_dict: dict[tuple[int, int, int], Terrain] = {}
        config = TerrainConfig()

        for row in rows:
            record = Terrain.model_validate(row)
            # Use layer=0 if not set in DB
            layer = record.layer if record.layer is not None else 0
            key = (record.grid_row, record.grid_column, layer)
            terrain_dict[key] = record

            # Capture physics config from first row that has it
            if config.cell_size_ft is None and record.cell_size_ft:
                config.cell_size_ft = record.cell_size_ft
            if config.time_step_min is None and record.time_step_min:
                config.time_step_min = record.time_step_min
            if config.burn_duration_ticks is None and record.burn_duration_ticks:
                config.burn_duration_ticks = record.burn_duration_ticks

        logger.info(
            "Loaded %d terrain cells for region %r",
            len(terrain_dict),
            region_name,
        )
        return terrain_dict, config

    def fetch_cell_location(self, row: int, col: int, layer: int = 0) -> tuple[float, float] | None:
        """Return (lat, long) for a single grid cell, or None if not found."""
        rows = self._pg.fetch_rows(
            "select lat, long from terrain where grid_row = %s and grid_column = %s and layer = %s limit 1",
            (row, col, layer),
        )
        if not rows:
            return None
        r = rows[0]
        return r["lat"], r["long"]

    def build_fire_cell_state(self, terrain: Terrain) -> FireCellState:
        """Convert a Terrain record to FireCellState.

        Uses sensible defaults for missing fields.
        Includes per-cell weather seed if available in the DB.
        """
        terrain_type = _TERRAIN_MAP.get(terrain.terrain or "FOREST", TerrainType.FOREST)

        return FireCellState(
            terrain_type=terrain_type,
            vegetation=terrain.vegetation if terrain.vegetation is not None else 0.8,
            fuel_moisture=terrain.fuel_moisture if terrain.fuel_moisture is not None else 0.3,
            slope=terrain.slope if terrain.slope is not None else 0.0,
            # Per-cell weather seed (defaults used if DB columns are NULL)
            temperature_c=terrain.temperature_c if terrain.temperature_c is not None else 30.0,
            humidity_pct=terrain.humidity_pct if terrain.humidity_pct is not None else 25.0,
            wind_speed_mps=terrain.wind_speed_mps if terrain.wind_speed_mps is not None else 5.0,
            wind_direction_deg=terrain.wind_direction_deg if terrain.wind_direction_deg is not None else 0.0,
            pressure_hpa=terrain.pressure_hpa if terrain.pressure_hpa is not None else 1013.0,
        )
