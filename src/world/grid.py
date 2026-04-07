"""
ogar.world.grid

Canonical source for wildfire domain enums.

TerrainType and FireState are defined here so all parts of the codebase
(domain package, old tests, sensors) share the same enum objects.
"""

from enum import Enum


class TerrainType(str, Enum):
    """
    What kind of land a cell represents.

    Using str mixin so TerrainType.FOREST == "FOREST" for JSON/logging.
    """
    FOREST    = "FOREST"
    GRASSLAND = "GRASSLAND"
    SCRUB     = "SCRUB"
    ROCK      = "ROCK"
    WATER     = "WATER"
    URBAN     = "URBAN"


class FireState(str, Enum):
    """
    The fire state of a single cell.

    UNBURNED — no fire has reached this cell
    BURNING  — actively on fire
    BURNED   — fire has passed through, fuel is exhausted
    """
    UNBURNED = "UNBURNED"
    BURNING  = "BURNING"
    BURNED   = "BURNED"
