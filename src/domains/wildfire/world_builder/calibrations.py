"""
domains.wildfire.world_builder.calibrations

Per-region terrain calibration parameters.

A TerrainCalibration holds the LANDFIRE code → TerrainType mappings
and the biophysical parameters that differ between climate zones: the
canopy-to-vegetation formula parameters and the per-terrain fuel-moisture
defaults.

All calibration raw lives in raw/calibrations/*.json. This module
provides the schema, the logic that uses the raw, and a registry.

Currently available:
  california — Southern California / Mediterranean chaparral
               (Los Padres, Angeles, Cleveland, San Bernardino NFs)

Adding a calibration (e.g. Rocky Mountain ecology):
  1. Create raw/calibrations/rocky-mountain.json following the same schema.
  2. That is it — calibrations are auto-loaded at import time.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from world.grid import TerrainType

_CALIBRATION_DATA_DIR = Path(__file__).parent / "raw" / "calibrations"

_NON_BURNABLE: frozenset[TerrainType] = frozenset(
    {
        TerrainType.ROCK,
        TerrainType.WATER,
        TerrainType.URBAN,
    }
)


class TerrainCalibration:
    """
    All region-specific parameters needed to translate LANDFIRE raster
    codes into simulator terrain cells.

    Retrieve from the module-level registry via get_calibration(); do not
    construct directly.
    """

    def __init__(
        self,
        name: str,
        fbfm40_to_terrain: dict[int, TerrainType],
        evt_to_terrain: dict[int, TerrainType],
        canopy_baseline: float,
        canopy_none_default: float,
        fuel_moisture_by_terrain: dict[TerrainType, float],
    ) -> None:
        self.name = name
        self._fbfm40 = fbfm40_to_terrain
        self._evt = evt_to_terrain
        self._canopy_baseline = canopy_baseline
        self._canopy_none_default = canopy_none_default
        self._moisture = fuel_moisture_by_terrain

    def resolve_terrain(
        self,
        fuel_codes: list[int],
        evt_codes: list[int],
    ) -> TerrainType:
        """
        Pick a TerrainType for one sim cell from its constituent LANDFIRE cells.

        Strategy:
          1. Mode of FBFM40 codes → calibration map.
          2. If non-burnable, check EVT mode as fallback — catches edge cells
             that FBFM40 calls non-burnable but EVT shows real vegetation.
          3. If still unmapped, default to GRASSLAND.
        """
        fuel_mode = Counter(fuel_codes).most_common(1)[0][0] if fuel_codes else None
        fuel_terrain = self._fbfm40.get(fuel_mode) if fuel_mode is not None else None

        if fuel_terrain is not None and fuel_terrain not in _NON_BURNABLE:
            return fuel_terrain

        evt_mode = Counter(evt_codes).most_common(1)[0][0] if evt_codes else None
        evt_terrain = self._evt.get(evt_mode) if evt_mode is not None else None
        if evt_terrain is not None:
            return evt_terrain

        if fuel_terrain is not None:
            return fuel_terrain

        return TerrainType.GRASSLAND

    def canopy_to_vegetation(self, canopy_cover: float | None) -> float:
        """Map LANDFIRE canopy-cover % to simulator vegetation density."""
        if canopy_cover is None:
            return self._canopy_none_default
        return round(min(1.0, self._canopy_baseline + (canopy_cover / 100.0)), 2)

    def fuel_moisture(self, terrain: TerrainType) -> float:
        """Dry-season fuel-moisture default for the given terrain type."""
        return self._moisture[terrain]

    def __repr__(self) -> str:
        return f"TerrainCalibration(name={self.name!r})"


def _load_calibration(path: Path) -> TerrainCalibration:
    raw = json.loads(path.read_text())
    return TerrainCalibration(
        name=raw["name"],
        fbfm40_to_terrain={int(k): TerrainType(v) for k, v in raw["fbfm40_to_terrain"].items()},
        evt_to_terrain={int(k): TerrainType(v) for k, v in raw["evt_to_terrain"].items()},
        canopy_baseline=raw["canopy"]["baseline"],
        canopy_none_default=raw["canopy"]["none_default"],
        fuel_moisture_by_terrain={
            TerrainType(k): v for k, v in raw["fuel_moisture_by_terrain"].items()
        },
    )


CALIBRATIONS: dict[str, TerrainCalibration] = {
    _cal.name: _cal
    for _cal in (_load_calibration(p) for p in sorted(_CALIBRATION_DATA_DIR.glob("*.json")))
}


def get_calibration(name: str) -> TerrainCalibration:
    """Retrieve a loaded calibration by name."""
    if name not in CALIBRATIONS:
        raise KeyError(f"Unknown calibration: {name!r}. Available: {sorted(CALIBRATIONS)}")
    return CALIBRATIONS[name]


CALIFORNIA_CALIBRATION: TerrainCalibration = CALIBRATIONS["california"]
