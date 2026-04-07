"""
ogar.domains.wildfire.fuel_models

Rothermel fuel model parameters mapped to TerrainType.

Each fuel model describes how a terrain type burns:
  - base_spread_rate_ft_min : R₀ — base Rate of Spread at reference conditions
  - heat_content_btu_lb     : heat released per pound of dry fuel
  - moisture_of_extinction  : fuel moisture fraction above which fire won't sustain
  - description             : human-readable summary

ROCK and WATER have no fuel model — they are non-burnable and are omitted
from the FUEL_MODELS dict. Physics modules should check terrain burnability
before looking up a fuel model.

Source: simplified from NFFL fuel models (see Rothermel 1972, Anderson 1982).
Values calibrated to the reference widget in docs/tutorial/wildfires/wirldfire-logic.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from world.grid import TerrainType


@dataclass(frozen=True)
class FuelModel:
    """
    Rothermel fuel parameters for a terrain type.

    Attributes
    ──────────
    base_spread_rate_ft_min : R₀ — base ROS at reference conditions (ft/min)
    heat_content_btu_lb     : Heat content for fireline intensity calculation (BTU/lb)
    moisture_of_extinction  : Fuel moisture fraction above which fire won't sustain (0–1)
    description             : Human-readable fuel type summary
    """
    base_spread_rate_ft_min: float
    heat_content_btu_lb: float
    moisture_of_extinction: float
    description: str


# ── Fuel model lookup table ───────────────────────────────────────────────────
#
# ROCK and WATER are intentionally absent — they are non-burnable.

FUEL_MODELS: Dict[TerrainType, FuelModel] = {
    TerrainType.GRASSLAND: FuelModel(
        base_spread_rate_ft_min=18.0,
        heat_content_btu_lb=8000.0,
        moisture_of_extinction=0.15,
        description="Dry grass / shrubland — fast spread, lower intensity",
    ),
    TerrainType.SCRUB: FuelModel(
        base_spread_rate_ft_min=12.0,
        heat_content_btu_lb=9500.0,
        moisture_of_extinction=0.20,
        description="Chaparral / dense shrub — moderate spread, high intensity",
    ),
    TerrainType.FOREST: FuelModel(
        base_spread_rate_ft_min=6.0,
        heat_content_btu_lb=8500.0,
        moisture_of_extinction=0.25,
        description="Timber litter — slower spread, sustained burn",
    ),
    TerrainType.URBAN: FuelModel(
        base_spread_rate_ft_min=8.0,
        heat_content_btu_lb=9000.0,
        moisture_of_extinction=0.10,
        description="Urban fuel loads — variable spread, high structure risk",
    ),
}

# ── Convenience helper ────────────────────────────────────────────────────────

def get_fuel_model(terrain_type: TerrainType) -> FuelModel | None:
    """
    Return the FuelModel for a terrain type, or None if non-burnable.

    ROCK and WATER return None.  All other TerrainTypes return a FuelModel.
    """
    return FUEL_MODELS.get(terrain_type)
