"""
world-simulator.world.coverage_index

Spatial coverage adapter over SensorInventory.

Bridges the sensor inventory (which tracks sensor placements) and the
risk pipeline's collation step (which needs to map SensorEvents to
grid cells and compute signal strength).

Does NOT duplicate inventory raw — wraps the inventory and adds the
spatial queries that collation needs:

  - source_id → GridPosition (which cell is this sensor on?)
  - signal_strength (how reliable is this reading for a target cell?)

Signal strength model
─────────────────────
  signal_strength = sensor_confidence × distance_decay

  At the sensor's own cell: decay = 1.0
  Linear decay to 0.0 at decay_radius
  Beyond decay_radius: 0.0

  Intentionally simple — a sensor reading primarily applies to its
  own cell.  Neighboring cells get a degraded version.  The
  decay_radius controls how far a reading "reaches".
"""

from __future__ import annotations

import logging
import math

from agents.commons.schemas import GridPosition
from world.sensor_inventory import SensorInventory

logger = logging.getLogger(__name__)


class CoverageIndex:
    """
    Spatial coverage adapter over SensorInventory.

    Usage
    ─────
      index = CoverageIndex(inventory)
      pos = index.get_position("temp-A1")       # → GridPosition(row=3, col=4)
      ss  = index.signal_strength("temp-A1", 3, 4, confidence=0.9)  # → 0.9
      ss  = index.signal_strength("temp-A1", 5, 4, confidence=0.9)  # → decayed
    """

    def __init__(
        self,
        inventory: SensorInventory,
        decay_radius: float = 2.0,
    ) -> None:
        """
        Parameters
        ──────────
        inventory    : The sensor inventory tracking all placed sensors.
        decay_radius : Maximum distance (in grid cells) at which a sensor
                       reading has nonzero signal strength for a cell.
                       Default 2.0 means a sensor contributes to cells
                       up to 2 cells away with linearly decayed strength.
        """
        self._inventory = inventory
        self.decay_radius = decay_radius

    @property
    def inventory(self) -> SensorInventory:
        """Access the underlying inventory."""
        return self._inventory

    def get_position(self, source_id: str) -> GridPosition | None:
        """Look up a sensor's grid position by its source_id.

        Returns None if the source_id is not in the inventory.
        """
        try:
            row, col, _layer = self._inventory.get_position(source_id)
            return GridPosition(row=row, col=col)
        except KeyError:
            return None

    def signal_strength(
        self,
        source_id: str,
        cell_row: int,
        cell_col: int,
        sensor_confidence: float = 1.0,
    ) -> float:
        """Compute signal strength for a sensor reading at a target cell.

        signal_strength = sensor_confidence × distance_decay

        Parameters
        ──────────
        source_id          : Which sensor produced the reading.
        cell_row, cell_col : The target cell to compute strength for.
        sensor_confidence  : The sensor's own health/confidence value
                             (from SensorEvent.confidence).

        Returns
        ───────
        0.0–1.0.  Returns 0.0 if the sensor is unknown or beyond
        decay_radius.
        """
        pos = self.get_position(source_id)
        if pos is None:
            return 0.0

        distance = math.sqrt((pos.row - cell_row) ** 2 + (pos.col - cell_col) ** 2)
        if distance == 0.0:
            return sensor_confidence
        if distance >= self.decay_radius:
            return 0.0

        decay = 1.0 - (distance / self.decay_radius)
        return sensor_confidence * decay
