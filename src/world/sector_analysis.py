"""
world-simulator.world.sector_analysis

Radial sector analysis service over the world grid.

Purpose
───────
Given a fire hotspot (row, col) on a GenericTerrainGrid, this module
produces an 8-direction summary of what surrounds the hotspot: how far
the fire could spread before hitting a barrier, what stopped it, and
how the fuel/moisture/slope/wind look along the way.

This is a pure read-only analytical service over the grid — it has no
knowledge of agents, LangGraph state, messages, or LLMs. It used to
live inside `agents/logistics/nodes.py`; it was lifted here because:

  * It only reads the grid and produces summary records.
  * It is reusable: anything that wants a "compress the grid into
    sector summaries around a point" view can call it.
  * It belongs to the simulation/world layer's stated job of
    exposing grid views (see `world/__init__.py`).

Output shape
────────────
For a hotspot we return a `HotspotSectors` with:
  - epicenter_row, epicenter_col, risk_score, confidence
  - 8 `SectorSummary` records (one per cardinal/intercardinal direction)

Each `SectorSummary` contains:
  - direction, burnable_miles, stop_reason
  - avg_vegetation, avg_fuel_moisture, avg_slope, max_fire_intensity
  - wind_aligned (sector direction vs. wind direction)
  - cells_in_sector

The `stop_reason` is the load-bearing signal for downstream LLM prompts:
a 5-mile sector ending in WATER means the fire is bounded; the same
distance ending in URBAN means a settlement is in the spread path.

Coordinate convention matches `GenericTerrainGrid`:
  - row 0 = NORTH edge, increasing row = southward
  - col 0 = WEST edge, increasing col = eastward
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from world.cell_state import GenericCell
from world.directions import SECTOR_ANGLES, Direction
from world.grid import FireState, TerrainType

# ── Public types ──────────────────────────────────────────────────────────────

StopReason = Literal[
    "barrier:urban",  # settlement at risk — fire would impact people/property
    "barrier:water",  # natural firebreak
    "barrier:rock",  # natural firebreak
    "barrier:snow",  # natural firebreak
    "burned",  # already-burned area (no more fuel)
    "max_distance",  # hit the configured trace limit — fuel may continue beyond
    "grid_edge",  # ran off the map — unknown beyond
]


class SectorSummary(BaseModel):
    """Radial sector analysis from a fire hotspot."""

    direction: Direction = Field(description="Cardinal direction of this sector")
    burnable_miles: float = Field(
        description="Continuous burnable distance from the hotspot in this direction"
    )
    stop_reason: StopReason = Field(
        description="Why the trace stopped. 'barrier:urban' means the fire would "
        "reach a populated area — escalate. 'barrier:water/rock/snow' = natural "
        "firebreak. 'grid_edge' or 'max_distance' = the spread is not bounded by "
        "the data we have."
    )
    avg_vegetation: float = Field(ge=0, le=1, description="Mean vegetation density")
    avg_fuel_moisture: float = Field(ge=0, le=1, description="Mean fuel moisture")
    avg_slope: float = Field(description="Mean slope in degrees")
    max_fire_intensity: float = Field(ge=0, le=1, description="Maximum fire intensity in sector")
    wind_aligned: bool = Field(description="True if sector direction matches wind direction")
    cells_in_sector: int = Field(description="Number of cells scanned in this sector")


class HotspotSectors(BaseModel):
    """Complete sector analysis for a single fire hotspot."""

    epicenter_row: int
    epicenter_col: int
    risk_score: int = Field(ge=0, le=10)
    confidence: int = Field(ge=0, le=3)
    sectors: list[SectorSummary] = Field(description="8 radial sector summaries")

    def to_context_string(self) -> str:
        """Human-readable summary suitable for inclusion in an LLM prompt."""
        lines = [
            f"Hotspot at ({self.epicenter_row}, {self.epicenter_col}): "
            f"Risk={self.risk_score}/10, Confidence={self.confidence}/3",
            "Radial sector analysis:",
        ]
        for s in self.sectors:
            align_marker = "🔥 WIND-ALIGNED" if s.wind_aligned else ""
            stop_label = format_stop_reason(s.stop_reason)
            lines.append(
                f"  {s.direction:2}: {s.burnable_miles:.1f}mi → {stop_label} | "
                f"fuel={s.avg_vegetation:.2f} | moisture={s.avg_fuel_moisture:.2f} | "
                f"slope={s.avg_slope:.1f}° | fire_intensity={s.max_fire_intensity:.2f} "
                f"{align_marker}"
            )
        return "\n".join(lines)


# ── Rendering helpers ─────────────────────────────────────────────────────────


def format_stop_reason(reason: StopReason) -> str:
    """Render a stop_reason for the LLM context string.

    URBAN is rendered with a fire emoji so the model can't miss it — a
    wind-aligned sector ending in URBAN is an escalation signal, not a
    "fire stops at concrete" signal.
    """
    return {
        "barrier:urban": "🚨 URBAN (settlement at risk)",
        "barrier:water": "WATER (natural firebreak)",
        "barrier:rock": "ROCK (natural firebreak)",
        "barrier:snow": "SNOW (natural firebreak)",
        "burned": "burned-out area",
        "max_distance": "fuel continues beyond trace limit",
        "grid_edge": "grid edge (unknown beyond)",
    }[reason]


# ── Geometry / orientation ────────────────────────────────────────────────────


def is_wind_aligned(wind_dir_deg: float, sector_angle: int, tolerance: float = 30.0) -> bool:
    """True if wind direction is within `tolerance` degrees of the sector heading."""
    diff = abs(wind_dir_deg - sector_angle)
    diff = min(diff, 360 - diff)  # Handle wrap-around at 0°/360°
    return diff <= tolerance


# Maps non-burnable terrain types to the StopReason literal we report.
_TERRAIN_STOP: dict[TerrainType, StopReason] = {
    TerrainType.URBAN: "barrier:urban",
    TerrainType.WATER: "barrier:water",
    TerrainType.ROCK: "barrier:rock",
    TerrainType.SNOW: "barrier:snow",
}


# ── Grid traversal ────────────────────────────────────────────────────────────


def trace_sector(
    grid,
    start_row: int,
    start_col: int,
    dr: int,
    dc: int,
    max_cells: int,
    cell_size_ft: float,
) -> tuple[float, list[GenericCell], StopReason]:
    """Walk outward from (start_row, start_col) along (dr, dc) until blocked.

    Returns:
        burnable_miles : continuous burnable distance covered
        cells          : the burnable cells traversed (in order)
        stop_reason    : why the walk stopped

    The stop reason is the load-bearing signal for downstream consumers:
    a 5-mile sector ending in WATER means the fire is bounded; the same
    distance ending in URBAN means a settlement is in the spread path.
    """
    cells: list[GenericCell] = []
    row, col = start_row + dr, start_col + dc
    stop_reason: StopReason = "max_distance"  # default if loop exhausts cleanly

    for _ in range(max_cells):
        if not (0 <= row < grid.rows and 0 <= col < grid.cols):
            stop_reason = "grid_edge"
            break

        cell = grid.get_cell(row, col)
        cell_state = cell.cell_state

        barrier = _TERRAIN_STOP.get(cell_state.terrain_type)
        if barrier is not None:
            stop_reason = barrier
            break

        if cell_state.fire_state == FireState.BURNED:
            stop_reason = "burned"
            break

        cells.append(cell)
        row += dr
        col += dc

    cell_size_miles = cell_size_ft / 5280.0
    burnable_miles = len(cells) * cell_size_miles

    return burnable_miles, cells, stop_reason


def analyze_sector(
    sector: Direction,
    cells: list[GenericCell],
    stop_reason: StopReason,
    wind_dir_deg: float,
    cell_size_ft: float,
) -> SectorSummary:
    """Reduce a list of traced cells to a single SectorSummary record."""
    if not cells:
        # Sector blocked immediately — the adjacent cell was already a
        # barrier or off-grid. stop_reason still carries the signal.
        return SectorSummary(
            direction=sector,
            burnable_miles=0.0,
            stop_reason=stop_reason,
            avg_vegetation=0.0,
            avg_fuel_moisture=1.0,
            avg_slope=0.0,
            max_fire_intensity=0.0,
            wind_aligned=is_wind_aligned(wind_dir_deg, SECTOR_ANGLES[sector]),
            cells_in_sector=0,
        )

    n = len(cells)
    avg_veg = sum(c.cell_state.vegetation for c in cells) / n
    avg_moisture = sum(c.cell_state.fuel_moisture for c in cells) / n
    avg_slope = sum(c.cell_state.slope for c in cells) / n
    max_intensity = max((c.cell_state.fire_intensity for c in cells), default=0.0)

    cell_size_miles = cell_size_ft / 5280.0
    burnable_miles = n * cell_size_miles

    return SectorSummary(
        direction=sector,
        burnable_miles=burnable_miles,
        stop_reason=stop_reason,
        avg_vegetation=avg_veg,
        avg_fuel_moisture=avg_moisture,
        avg_slope=avg_slope,
        max_fire_intensity=max_intensity,
        wind_aligned=is_wind_aligned(wind_dir_deg, SECTOR_ANGLES[sector]),
        cells_in_sector=n,
    )


__all__ = [
    "HotspotSectors",
    "SectorSummary",
    "StopReason",
    "analyze_sector",
    "format_stop_reason",
    "is_wind_aligned",
    "trace_sector",
]
