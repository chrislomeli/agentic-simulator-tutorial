"""
world-simulator.world.directions

Compass directions and sector geometry for the world grid.

These are pure spatial primitives — they describe directions on the grid,
not agent contracts. Living in `world/` keeps them importable by both the
simulation layer (`world.sector_analysis`) and the agent layer without
forcing a dependency from world → agents.

Coordinate convention (matches `GenericTerrainGrid`):
  - row 0 = NORTH edge, increasing row = southward
  - col 0 = WEST edge,  increasing col = eastward
  - (0, 0) = north-west corner

So the (dr, dc) offset for N is (-1, 0) — decreasing row moves north.
"""

from __future__ import annotations

from enum import Enum


class Direction(str, Enum):
    """One of eight compass directions used for radial grid analysis."""

    N = "N"
    NE = "NE"
    E = "E"
    SE = "SE"
    S = "S"
    SW = "SW"
    W = "W"
    NW = "NW"


# Compass heading in degrees clockwise from N.
SECTOR_ANGLES: dict[Direction, int] = {
    Direction.N: 0,
    Direction.NE: 45,
    Direction.E: 90,
    Direction.SE: 135,
    Direction.S: 180,
    Direction.SW: 225,
    Direction.W: 270,
    Direction.NW: 315,
}

# (delta_row, delta_col) step vectors for moving one cell in each direction.
SECTOR_VECTORS: dict[Direction, tuple[int, int]] = {
    Direction.N: (-1, 0),
    Direction.NE: (-1, 1),
    Direction.E: (0, 1),
    Direction.SE: (1, 1),
    Direction.S: (1, 0),
    Direction.SW: (1, -1),
    Direction.W: (0, -1),
    Direction.NW: (-1, -1),
}


__all__ = ["Direction", "SECTOR_ANGLES", "SECTOR_VECTORS"]
