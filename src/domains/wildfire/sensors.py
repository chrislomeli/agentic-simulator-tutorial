"""
ogar.domains.wildfire.sensors

Fire-specific sensors that sample from a GenericWorldEngine[FireCellState].

These sensors read from the generic engine's grid and environment to
produce domain-specific SensorEvent payloads.  Each sensor holds a
reference to the engine and queries it during read().

The base class (SensorBase) handles wrapping the payload in a
SensorEvent envelope, applying failure modes, and tracking ticks.
These subclasses only implement read().

Noise model
───────────
Each sensor adds Gaussian noise to its readings.  The noise_std
parameter controls how much noise is added.  Set to 0.0 for
perfect readings (useful for debugging).

Sensor types
────────────
  TemperatureSensor   : ambient temp + fire radiant heat
  HumiditySensor      : relative humidity from weather
  WindSensor          : wind speed and direction
  SmokeSensor         : PM2.5 from fire proximity and wind
  BarometricSensor    : atmospheric pressure
  ThermalCameraSensor : 2D heat grid over a region
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List

from domains.wildfire.cell_state import FireCellState, FireState
from domains.wildfire.environment import FireEnvironmentState
from sensors.base import SensorBase
from world.generic_engine import GenericWorldEngine


# ── Temperature sensor ───────────────────────────────────────────────────────

class TemperatureSensor(SensorBase):
    """
    Reads ambient temperature + fire radiant heat from nearby cells.

    Real-world reference:
      RAWS stations report temperature every 10-60 min in °C.
      Fire proximity can raise readings to 80°C+ at close range.
    """

    source_type = "temperature"

    def __init__(
        self,
        *,
        engine: GenericWorldEngine[FireCellState],
        grid_row: int,
        grid_col: int,
        noise_std: float = 0.5,
        **kwargs,
    ) -> None:
        super().__init__(grid_row=grid_row, grid_col=grid_col, **kwargs)
        self._engine = engine
        self._noise_std = noise_std

    def read(self) -> Dict[str, Any]:
        env: FireEnvironmentState = self._engine.environment  # type: ignore[assignment]
        base_temp = env.temperature_c

        # Heat from nearby burning cells.
        heat_boost = 0.0
        for nr, nc, _nl in self._engine.grid.neighbors(self.grid_row, self.grid_col):
            neighbor = self._engine.grid.get_cell(nr, nc)
            if neighbor.cell_state.fire_state == FireState.BURNING:
                heat_boost += neighbor.cell_state.fire_intensity * 15.0

        own_cell = self._engine.grid.get_cell(self.grid_row, self.grid_col)
        if own_cell.cell_state.fire_state == FireState.BURNING:
            heat_boost += own_cell.cell_state.fire_intensity * 40.0

        noise = random.gauss(0, self._noise_std)
        celsius = base_temp + heat_boost + noise
        return {"celsius": round(celsius, 1), "unit": "C"}


# ── Humidity sensor ──────────────────────────────────────────────────────────

class HumiditySensor(SensorBase):
    """
    Reads relative humidity from the environment.

    The sensor has a grid location (it's a physical device) but reads
    global environment humidity — the environment model doesn't have
    per-cell humidity variation.

    Real-world reference:
      Standard hygrometers report 0–100% RH.
      Below 20% is extreme fire danger.
    """

    source_type = "humidity"

    def __init__(
        self,
        *,
        engine: GenericWorldEngine[FireCellState],
        grid_row: int,
        grid_col: int,
        noise_std: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(grid_row=grid_row, grid_col=grid_col, **kwargs)
        self._engine = engine
        self._noise_std = noise_std

    def read(self) -> Dict[str, Any]:
        env: FireEnvironmentState = self._engine.environment  # type: ignore[assignment]
        humidity = env.humidity_pct + random.gauss(0, self._noise_std)
        humidity = max(0.0, min(100.0, humidity))
        return {"relative_humidity_pct": round(humidity, 1), "unit": "%"}


# ── Wind sensor ──────────────────────────────────────────────────────────────

class WindSensor(SensorBase):
    """
    Reads wind speed and direction from the environment.

    The sensor has a grid location (it's a physical device) but reads
    global environment wind — the environment model doesn't have
    per-cell wind variation.

    Real-world reference:
      Anemometers report wind speed (m/s) and direction (°).
    """

    source_type = "wind"

    def __init__(
        self,
        *,
        engine: GenericWorldEngine[FireCellState],
        grid_row: int,
        grid_col: int,
        speed_noise_std: float = 0.3,
        direction_noise_std: float = 3.0,
        **kwargs,
    ) -> None:
        super().__init__(grid_row=grid_row, grid_col=grid_col, **kwargs)
        self._engine = engine
        self._speed_noise_std = speed_noise_std
        self._direction_noise_std = direction_noise_std

    def read(self) -> Dict[str, Any]:
        env: FireEnvironmentState = self._engine.environment  # type: ignore[assignment]
        speed = max(0.0, env.wind_speed_mps + random.gauss(0, self._speed_noise_std))
        direction = (env.wind_direction_deg + random.gauss(0, self._direction_noise_std)) % 360.0
        return {
            "speed_mps": round(speed, 1),
            "direction_deg": round(direction, 1),
            "unit": "m/s",
        }


# ── Smoke sensor ─────────────────────────────────────────────────────────────

class SmokeSensor(SensorBase):
    """
    Reads PM2.5 particulate density based on nearby fire and wind.

    The reading is derived from total fire intensity in nearby cells,
    modulated by wind direction and distance.

    Real-world reference:
      PM2.5 sensors report in µg/m³.
      Clean air: 0–12, moderate: 12–35, unhealthy: 35–150,
      hazardous: 150+, near wildfire: 500+.
    """

    source_type = "smoke"

    def __init__(
        self,
        *,
        engine: GenericWorldEngine[FireCellState],
        grid_row: int,
        grid_col: int,
        noise_std: float = 2.0,
        **kwargs,
    ) -> None:
        super().__init__(grid_row=grid_row, grid_col=grid_col, **kwargs)
        self._engine = engine
        self._noise_std = noise_std

    def read(self) -> Dict[str, Any]:
        env: FireEnvironmentState = self._engine.environment  # type: ignore[assignment]
        baseline_pm25 = 5.0

        wind_row, wind_col = env.wind_vector()
        wind_speed = env.wind_speed_mps

        total_smoke = 0.0
        for cell in self._engine.grid.iter_cells():
            if cell.cell_state.fire_state != FireState.BURNING:
                continue

            dr = self.grid_row - cell.row
            dc = self.grid_col - cell.col
            dist = math.sqrt(dr * dr + dc * dc)
            if dist == 0:
                dist = 0.5

            distance_factor = 1.0 / (1.0 + dist)

            if dist > 0:
                dir_r = dr / dist
                dir_c = dc / dist
                dot = wind_row * dir_r + wind_col * dir_c
                wind_factor = max(0.1, 0.5 + dot * 0.5)
            else:
                wind_factor = 1.0

            speed_factor = 1.0 + min(wind_speed / 15.0, 1.0)
            contribution = (
                cell.cell_state.fire_intensity
                * distance_factor * wind_factor * speed_factor * 80.0
            )
            total_smoke += contribution

        pm25 = max(0.0, baseline_pm25 + total_smoke + random.gauss(0, self._noise_std))
        return {"pm25_ugm3": round(pm25, 1), "unit": "µg/m³"}


# ── Barometric pressure sensor ──────────────────────────────────────────────

class BarometricSensor(SensorBase):
    """
    Reads atmospheric pressure from the environment.

    Real-world reference:
      Standard barometers report in hPa. Normal range: 980–1040 hPa.
    """

    source_type = "barometric_pressure"

    def __init__(
        self,
        *,
        engine: GenericWorldEngine[FireCellState],
        grid_row: int,
        grid_col: int,
        noise_std: float = 0.3,
        **kwargs,
    ) -> None:
        super().__init__(grid_row=grid_row, grid_col=grid_col, **kwargs)
        self._engine = engine
        self._noise_std = noise_std

    def read(self) -> Dict[str, Any]:
        env: FireEnvironmentState = self._engine.environment  # type: ignore[assignment]
        pressure = env.pressure_hpa + random.gauss(0, self._noise_std)
        return {"pressure_hpa": round(pressure, 1), "unit": "hPa"}


# ── Thermal camera sensor ───────────────────────────────────────────────────

class ThermalCameraSensor(SensorBase):
    """
    Reads a 2D heat map from a region of the grid.

    Unlike a point sensor, covers a rectangular area and returns
    a grid of temperature values.  Burning cells appear as hot spots.

    Real-world reference:
      FLIR thermal cameras produce pixel grids of temperature.
      Near-flame surface: up to 800°C+.
    """

    source_type = "thermal_camera"

    def __init__(
        self,
        *,
        engine: GenericWorldEngine[FireCellState],
        top_row: int,
        left_col: int,
        view_rows: int,
        view_cols: int,
        noise_std: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(grid_row=top_row, grid_col=left_col, **kwargs)
        self._engine = engine
        self._top_row = top_row
        self._left_col = left_col
        self._view_rows = view_rows
        self._view_cols = view_cols
        self._noise_std = noise_std

    def read(self) -> Dict[str, Any]:
        env: FireEnvironmentState = self._engine.environment  # type: ignore[assignment]
        ambient = env.temperature_c
        heat_grid: List[List[float]] = []

        for r in range(self._top_row, self._top_row + self._view_rows):
            row_temps: List[float] = []
            for c in range(self._left_col, self._left_col + self._view_cols):
                if 0 <= r < self._engine.grid.rows and 0 <= c < self._engine.grid.cols:
                    state = self._engine.grid.get_cell(r, c).cell_state
                    fire_heat = state.fire_intensity * 200.0
                    temp = ambient + fire_heat + random.gauss(0, self._noise_std)
                else:
                    temp = ambient + random.gauss(0, self._noise_std)
                row_temps.append(round(temp, 1))
            heat_grid.append(row_temps)

        return {
            "grid_celsius": heat_grid,
            "top_row": self._top_row,
            "left_col": self._left_col,
            "view_rows": self._view_rows,
            "view_cols": self._view_cols,
            "unit": "C",
        }
