"""
ogar.domains.wildfire.rothermel_physics

RothermelFirePhysicsModule — simplified Rothermel fire spread model.

Implements PhysicsModule[FireCellState] — drop-in replacement for
SimpleFirePhysicsModule.

Replaces the probabilistic placeholder with physics-grounded equations:
  - Rate of Spread (ROS) from Rothermel (1972)
  - Fireline intensity from Byram (1959)
  - Flame length from Byram (1959)
  - Acres/hr from Anderson (1983) elliptical model
  - Danger rating tiers from the reference widget

The core cellular automaton loop is unchanged in structure: each tick,
burning cells may spread to unburned neighbors.  The key change is that
spread probability is now derived from physics:

    spread_distance_ft = ROS × time_step_min
    prob_spread = min(0.95, spread_distance_ft / cell_size_ft)

This means fire spreads faster when Rothermel says ROS is high (hot, dry,
windy, steep) and slower when conditions suppress spread (wet, calm, flat).

Wind is directional: the effective wind speed for a given spread direction
is the component of the wind vector in that direction (dot product).
Backing fire (negative alignment) receives no wind boost but can still
spread at the base rate.

Slope is applied isotropically from the destination cell's slope field.

References
──────────
  Rothermel, R.C. (1972). USDA Forest Service Research Paper INT-115.
  Byram, G.M. (1959). In: Davis, K.P. Forest Fire Control and Use.
  Anderson, H.E. (1983). USDA Forest Service Research Paper INT-305.
  Reference widget: docs/tutorial/wildfires/wirldfire-logic.md
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List

from domains.wildfire.cell_state import FireCellState, FireState
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire.fuel_models import FUEL_MODELS, FuelModel, get_fuel_model
from world.generic_grid import GenericTerrainGrid
from world.physics import PhysicsModule, StateEvent

# Maximum ROS used for danger rating normalisation (ft/min)
_MAX_ROS_FOR_DANGER = 40.0

# Meters-per-second to miles-per-hour
_MPS_TO_MPH = 2.23694


class RothermelFirePhysicsModule(PhysicsModule[FireCellState]):
    """
    Simplified Rothermel fire spread model.

    Implements PhysicsModule[FireCellState] — drop-in replacement for
    SimpleFirePhysicsModule.

    Computes Rate of Spread (ROS) from fuel model, weather, and terrain,
    then converts to per-tick spread probability for the cellular automaton.
    Also computes derived metrics (flame length, fireline intensity) and
    stores them on FireCellState for tool access.

    Parameters
    ──────────
    cell_size_ft       : Spatial extent of one grid cell (feet).
                         Controls the ROS → probability conversion.
                         Default 200 ft (≈ 60 m, typical demo resolution).
    time_step_min      : Minutes represented by one simulation tick.
                         Default 5 min.
    burn_duration_ticks: How many ticks a cell burns before extinguishing.
                         Default 5 (= 25 min at 5 min/tick).
    """

    def __init__(
        self,
        *,
        cell_size_ft: float = 200.0,
        time_step_min: float = 5.0,
        burn_duration_ticks: int = 5,
    ) -> None:
        self._cell_size_ft = cell_size_ft
        self._time_step_min = time_step_min
        self._burn_duration = burn_duration_ticks

    # ── PhysicsModule interface ───────────────────────────────────────────────

    def initial_cell_state(self, row: int, col: int, layer: int = 0) -> FireCellState:
        """Return the default cell state — unburned grassland."""
        return FireCellState()

    def tick_physics(
        self,
        grid: GenericTerrainGrid[FireCellState],
        environment: FireEnvironmentState,
        tick: int,
    ) -> List[StateEvent[FireCellState]]:
        """
        Compute one tick of Rothermel fire spread.

        For each burning cell:
          1. Compute heading ROS and derived metrics (flame length, intensity).
          2. Check burn duration — extinguish if exceeded (metrics zeroed).
          3. Otherwise update the cell's stored metrics (in-place StateEvent).
          4. For each unburned burnable neighbor, compute directional ROS,
             convert to spread probability, and roll.
          5. Ignited cells carry over the source cell's metrics at ignition.
        """
        events: List[StateEvent[FireCellState]] = []

        wind_row, wind_col = environment.wind_vector()
        wind_mph = environment.wind_speed_mps * _MPS_TO_MPH

        burning = grid.cells_where(
            lambda c: c.cell_state.fire_state == FireState.BURNING
        )

        newly_ignited: set[tuple[int, int, int]] = set()

        for row, col, _layer in burning:
            cell = grid.get_cell(row, col)
            state = cell.cell_state

            fuel_model = get_fuel_model(state.terrain_type)
            if fuel_model is None:
                # Non-burnable terrain that somehow caught fire — extinguish it.
                events.append(StateEvent(
                    row=row, col=col,
                    new_state=state.extinguished(),
                ))
                continue

            # ── Heading ROS and derived metrics ──────────────────────
            # Use full wind speed (heading into wind) for metric storage.
            heading_ros = self._compute_ros(
                fuel_model, environment, state, wind_alignment=1.0
            )
            flame_len = self._compute_flame_length(heading_ros, fuel_model.heat_content_btu_lb)
            moisture_factor = self._moisture_factor(state.fuel_moisture)
            intensity = self._compute_fireline_intensity(
                heading_ros, fuel_model.heat_content_btu_lb, moisture_factor
            )

            # ── Check burn duration ───────────────────────────────────
            if state.fire_start_tick is not None:
                ticks_burning = tick - state.fire_start_tick
                if ticks_burning >= self._burn_duration:
                    events.append(StateEvent(
                        row=row, col=col,
                        new_state=state.extinguished(),
                    ))
                    continue

            # ── Update metrics on still-burning cell ──────────────────
            updated = state.model_copy(update={
                "rate_of_spread_ft_min": round(heading_ros, 3),
                "flame_length_ft": round(flame_len, 3),
                "fireline_intensity_btu_ft_s": round(intensity, 3),
            })
            events.append(StateEvent(row=row, col=col, new_state=updated))

            # ── Try to spread to each burnable neighbor ───────────────
            for nr, nc, _nl in grid.neighbors(row, col):
                if (nr, nc, _nl) in newly_ignited:
                    continue

                neighbor = grid.get_cell(nr, nc)
                neighbor_state = neighbor.cell_state

                if not neighbor_state.is_burnable:
                    continue

                # Directional wind: component in the spread direction.
                dr = nr - row
                dc = nc - col
                dist = math.sqrt(dr * dr + dc * dc)
                if dist > 0:
                    dr_n = dr / dist
                    dc_n = dc / dist
                else:
                    dr_n, dc_n = 0.0, 0.0

                wind_alignment = wind_row * dr_n + wind_col * dc_n

                # Directional ROS for this spread direction.
                dir_ros = self._compute_ros(
                    get_fuel_model(neighbor_state.terrain_type) or fuel_model,
                    environment,
                    neighbor_state,
                    wind_alignment=wind_alignment,
                )

                prob = self._ros_to_spread_probability(dir_ros)

                # Diagonal spread: slight damping (geometry of a square grid).
                if (row != nr) and (col != nc):
                    prob *= 0.8

                if random.random() < prob:
                    neighbor_fuel = get_fuel_model(neighbor_state.terrain_type) or fuel_model
                    n_ros = self._compute_ros(
                        neighbor_fuel, environment, neighbor_state, wind_alignment=1.0
                    )
                    n_flame = self._compute_flame_length(n_ros, neighbor_fuel.heat_content_btu_lb)
                    n_mf = self._moisture_factor(neighbor_state.fuel_moisture)
                    n_intensity = self._compute_fireline_intensity(
                        n_ros, neighbor_fuel.heat_content_btu_lb, n_mf
                    )
                    norm_intensity = min(1.0, intensity / 2000.0)

                    events.append(StateEvent(
                        row=nr, col=nc,
                        new_state=neighbor_state.ignited(
                            tick=tick,
                            intensity=max(0.1, norm_intensity),
                            rate_of_spread_ft_min=round(n_ros, 3),
                            flame_length_ft=round(n_flame, 3),
                            fireline_intensity_btu_ft_s=round(n_intensity, 3),
                        ),
                    ))
                    newly_ignited.add((nr, nc, _nl))

        return events

    def summarize(
        self, grid: GenericTerrainGrid[FireCellState]
    ) -> Dict[str, Any]:
        """
        Return a fire-specific summary including Rothermel behavior metrics.

        Extends the basic summary with:
          - avg_ros_ft_min         : mean ROS across burning cells
          - max_ros_ft_min         : peak ROS
          - avg_flame_length_ft    : mean flame length
          - max_fireline_intensity : peak fireline intensity (BTU/ft/s)
          - estimated_acres_hr     : estimated area growth from Anderson model
          - danger_rating          : Low / Moderate / High / Very High / Extreme
        """
        burning_cells = []
        intensity_map = []
        ros_values: List[float] = []
        flame_values: List[float] = []
        fi_values: List[float] = []

        for r in range(grid.rows):
            row_intensities = []
            for c in range(grid.cols):
                state = grid.get_cell(r, c).cell_state
                if state.fire_state == FireState.BURNING:
                    burning_cells.append((r, c))
                    if state.rate_of_spread_ft_min > 0:
                        ros_values.append(state.rate_of_spread_ft_min)
                        flame_values.append(state.flame_length_ft)
                        fi_values.append(state.fireline_intensity_btu_ft_s)
                row_intensities.append(round(state.fire_intensity, 3))
            intensity_map.append(row_intensities)

        counts = grid.summary_counts()

        avg_ros = sum(ros_values) / len(ros_values) if ros_values else 0.0
        max_ros = max(ros_values) if ros_values else 0.0
        avg_flame = sum(flame_values) / len(flame_values) if flame_values else 0.0
        max_fi = max(fi_values) if fi_values else 0.0

        return {
            "burning_cells": burning_cells,
            "fire_intensity_map": intensity_map,
            "cell_summary": counts,
            "avg_ros_ft_min": round(avg_ros, 2),
            "max_ros_ft_min": round(max_ros, 2),
            "avg_flame_length_ft": round(avg_flame, 2),
            "max_fireline_intensity": round(max_fi, 2),
            "estimated_acres_hr": round(self._compute_acres_per_hour(avg_ros, 0.0), 2),
            "danger_rating": self._danger_rating(max_ros),
        }

    # ── Internal computation methods ──────────────────────────────────────────

    def _compute_ros(
        self,
        fuel_model: FuelModel,
        environment: FireEnvironmentState,
        cell_state: FireCellState,
        wind_alignment: float,
    ) -> float:
        """
        Compute Rate of Spread (ft/min) using the Rothermel model.

        Formula:
          ROS = R₀ × rh_factor × moisture_factor × temp_factor(50%) × wind_factor × slope_factor

        Environmental factors are derived from the reference widget in
        docs/tutorial/wildfires/wirldfire-logic.md.

        Parameters
        ──────────
        fuel_model     : Fuel parameters for this terrain type
        environment    : Current weather conditions
        cell_state     : Per-cell state (slope, moisture)
        wind_alignment : Dot product of wind direction and spread direction.
                         1.0 = fully downwind (heading), 0.0 = cross-wind,
                         negative = backing. Only downwind component is used.
        """
        # Unit conversions.
        temp_f = environment.temperature_c * 9.0 / 5.0 + 32.0
        rh = environment.humidity_pct
        wind_mph = environment.wind_speed_mps * _MPS_TO_MPH
        slope_deg = abs(cell_state.slope)  # magnitude; direction handled by wind_alignment

        # RH factor: 60% = 0.0 (fire won't spread), 0% = 1.0 (fully amplified).
        rh_factor = max(0.0, 1.0 - rh / 60.0)

        # Moisture factor: at extinction → 0.0; bone dry → 1.0.
        moisture_factor = self._moisture_factor(cell_state.fuel_moisture)

        # Temperature factor: 50°F → 0.0; 120°F → 1.0.
        temp_factor = max(0.0, min(1.0, (temp_f - 50.0) / 70.0))

        # Wind factor: directional component only (no backing-fire wind boost).
        effective_wind_mph = max(0.0, wind_mph * wind_alignment)
        wind_factor = 1.0 + (effective_wind_mph / 15.0) * 0.9

        # Slope factor: tangent-based (from Rothermel).
        slope_factor = 1.0 + math.tan(math.radians(slope_deg)) * 1.2

        # Vegetation density scales effective fuel loading.
        veg_factor = max(0.1, cell_state.vegetation)

        ros = (
            fuel_model.base_spread_rate_ft_min
            * rh_factor
            * moisture_factor
            * (0.5 + 0.5 * temp_factor)
            * wind_factor
            * slope_factor
            * veg_factor
        )
        return max(0.1, ros)

    def _compute_flame_length(self, ros: float, heat_content_btu_lb: float) -> float:
        """
        Byram (1959) flame length estimate.

        L = (ROS × heat_content / 500) ^ 0.46
        Returns flame length in feet.
        """
        val = ros * heat_content_btu_lb / 500.0
        return max(0.0, val ** 0.46)

    def _compute_fireline_intensity(
        self,
        ros: float,
        heat_content_btu_lb: float,
        moisture_factor: float,
    ) -> float:
        """
        Byram (1959) fireline intensity.

        I = ROS (ft/s) × heat_content × moisture_factor × 0.9

        ROS is stored in ft/min; divide by 60 to convert to ft/s before
        multiplying by heat content.  This gives physically correct BTU/ft/s
        values that map onto the NWCG intensity thresholds in nwcg_resources.py.

        Returns intensity in BTU/ft/s.
        """
        ros_ft_s = ros / 60.0
        return max(0.0, ros_ft_s * heat_content_btu_lb * moisture_factor * 0.9)

    def _compute_acres_per_hour(self, ros: float, wind_speed_mph: float) -> float:
        """
        Anderson (1983) elliptical fire growth model.

        Assumes elliptical fire shape elongated by wind.  Returns acres/hr.
        """
        # Semi-major axis: forward spread distance in 1 hour.
        a = ros * 60.0
        if a <= 0:
            return 0.0

        # Ellipse elongation increases with wind speed.
        wind_ratio = max(1.0, 1.0 + wind_speed_mph / 40.0)
        b = a / wind_ratio  # semi-minor axis

        # Ellipse area × 2.5 accounts for both heading and backing fire.
        area_sq_ft = math.pi * a * b * 2.5
        return area_sq_ft / 43560.0  # convert sq ft → acres

    def _ros_to_spread_probability(self, ros: float) -> float:
        """
        Convert ROS (ft/min) to per-tick spread probability.

        spread_distance = ROS × time_step_min
        prob = min(0.95, spread_distance / cell_size_ft)
        """
        spread_distance = ros * self._time_step_min
        return min(0.95, spread_distance / self._cell_size_ft)

    def _danger_rating(self, ros: float) -> str:
        """
        Map ROS to a danger tier.

        Tier boundaries are percentages of _MAX_ROS_FOR_DANGER (40 ft/min),
        matching the reference widget danger rating logic.
        """
        pct = ros / _MAX_ROS_FOR_DANGER
        if pct < 0.20:
            return "Low"
        if pct < 0.40:
            return "Moderate"
        if pct < 0.60:
            return "High"
        if pct < 0.80:
            return "Very High"
        return "Extreme"

    @staticmethod
    def _moisture_factor(fuel_moisture: float) -> float:
        """
        Fuel moisture suppression factor.

        Matches the reference doc formula:
          moistFactor = max(0, 1 - moisture_pct / 30)

        At  0% moisture → 1.0 (fully amplified — bone dry)
        At 15% moisture → 0.5 (moderate suppression)
        At 30% moisture → 0.0 (at moisture of extinction — fire won't sustain)

        The 30% denominator is the NFFL fine-fuel moisture of extinction used
        in the reference widget (docs/tutorial/wildfires/wirldfire-logic.md).
        Per-fuel extinction thresholds are documented on FuelModel.moisture_of_extinction
        but are not used in this simplified formula.

        fuel_moisture : cell fuel moisture as a fraction (0.0–1.0)
        """
        moist_pct = fuel_moisture * 100.0
        return max(0.0, 1.0 - moist_pct / 30.0)
