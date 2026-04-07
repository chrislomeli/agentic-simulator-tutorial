"""
ogar.world.sensor_inventory

SensorInventory — first-class management of sensor placement on a grid.

What this is
────────────
The SensorInventory tracks which sensors are placed at which grid
positions.  It is the primary experimental knob for the testbed:

  - Change sensor density to see how agent accuracy degrades.
  - Inject failures to test agent resilience.
  - Thin the inventory to simulate sparse deployments.
  - Measure coverage to quantify observation gaps.

The inventory is domain-agnostic — it works with any SensorBase
subclass regardless of whether the domain is wildfire, ocean, or
anything else.

Placement model
───────────────
Each sensor is placed at a specific (row, col, layer) on the grid.
Multiple sensors can occupy the same cell (e.g. a temperature
sensor and a smoke sensor co-located).

A sensor's "position" is where it samples from.  The sensor's
read() method is responsible for reading from the right location
in the world — the inventory just tracks the mapping.
"""

from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional, Set, Tuple

from sensors.base import FailureMode, SensorBase
from transport.schemas import SensorEvent

logger = logging.getLogger(__name__)


class SensorInventory:
    """
    Manages sensor placement, coverage analysis, and failure injection.

    Usage
    ─────
      inventory = SensorInventory(grid_rows=10, grid_cols=10)
      inventory.register(temp_sensor, row=3, col=4)
      inventory.register(smoke_sensor, row=3, col=4)  # co-located

      print(f"Coverage: {inventory.coverage_ratio():.0%}")
      inventory.thin(keep_fraction=0.5)  # remove half the sensors
      inventory.inject_bulk_failure(FailureMode.DRIFT, fraction=0.2)
    """

    def __init__(self, grid_rows: int, grid_cols: int, grid_layers: int = 1) -> None:
        """
        Parameters
        ──────────
        grid_rows   : number of rows in the grid (for coverage calculations)
        grid_cols   : number of columns in the grid
        grid_layers : number of vertical layers (default 1)
        """
        self._grid_rows = grid_rows
        self._grid_cols = grid_cols
        self._grid_layers = grid_layers
        self._sensors: Dict[str, SensorBase] = {}                    # source_id → sensor
        self._positions: Dict[str, Tuple[int, int, int]] = {}        # source_id → (row, col, layer)
        self._type_index: Dict[str, Set[str]] = {}                   # source_type → {source_ids}

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, sensor: SensorBase, row: int, col: int, layer: int = 0) -> None:
        """
        Add a sensor to the inventory at a specific grid position.

        Raises ValueError if:
          - A sensor with the same source_id is already registered
          - The position is out of grid bounds
        """
        if sensor.source_id in self._sensors:
            raise ValueError(
                f"Sensor {sensor.source_id!r} is already registered"
            )
        if not (0 <= row < self._grid_rows and 0 <= col < self._grid_cols
                and 0 <= layer < self._grid_layers):
            raise ValueError(
                f"Position ({row}, {col}, {layer}) out of bounds for grid "
                f"({self._grid_rows}×{self._grid_cols}×{self._grid_layers})"
            )
        self._sensors[sensor.source_id] = sensor
        self._positions[sensor.source_id] = (row, col, layer)
        self._type_index.setdefault(sensor.source_type, set()).add(sensor.source_id)
        logger.debug(
            "Registered sensor %s (%s) at (%d, %d, %d)",
            sensor.source_id, sensor.source_type, row, col, layer,
        )

    def unregister(self, source_id: str) -> SensorBase:
        """
        Remove a sensor from the inventory.

        Returns the removed sensor.
        Raises KeyError if the source_id is not registered.
        """
        sensor = self._sensors.pop(source_id)
        self._positions.pop(source_id)
        type_set = self._type_index.get(sensor.source_type)
        if type_set is not None:
            type_set.discard(source_id)
            if not type_set:
                del self._type_index[sensor.source_type]
        logger.debug("Unregistered sensor %s", source_id)
        return sensor

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_sensor(self, source_id: str) -> SensorBase:
        """Get a sensor by its source_id. Raises KeyError if not found."""
        return self._sensors[source_id]

    def get_position(self, source_id: str) -> Tuple[int, int, int]:
        """Get the (row, col, layer) position of a sensor. Raises KeyError if not found."""
        return self._positions[source_id]

    def get_sensors_at(self, row: int, col: int, layer: int = 0) -> List[SensorBase]:
        """Return all sensors placed at the given grid position."""
        return [
            sensor
            for sid, sensor in self._sensors.items()
            if self._positions[sid] == (row, col, layer)
        ]

    def all_sensors(self) -> List[SensorBase]:
        """Return all registered sensors."""
        return list(self._sensors.values())

    @property
    def size(self) -> int:
        """Number of registered sensors."""
        return len(self._sensors)

    # ── Auto-registration ─────────────────────────────────────────────────────

    def register_auto(self, sensor: SensorBase) -> None:
        """
        Register a sensor using its own grid_row/grid_col/grid_layer attributes.

        Raises ValueError if the sensor has no location set.
        grid_layer defaults to 0 if not set on the sensor.
        """
        if sensor.grid_row is None or sensor.grid_col is None:
            raise ValueError(
                f"Sensor {sensor.source_id!r} has no grid location — "
                f"set grid_row and grid_col before calling register_auto()"
            )
        layer = sensor.grid_layer if sensor.grid_layer is not None else 0
        self.register(sensor, row=sensor.grid_row, col=sensor.grid_col, layer=layer)

    # ── Layer queries ───────────────────────────────────────────────────────

    def layer_types(self) -> Set[str]:
        """Return the set of distinct source_type values currently registered."""
        return set(self._type_index.keys())

    def get_layer(self, source_type: str) -> Dict[str, Tuple[int, int, int]]:
        """
        Return all sensors of a given type as {source_id: (row, col, layer)}.

        Returns an empty dict if no sensors of that type exist.
        """
        sids = self._type_index.get(source_type, set())
        return {sid: self._positions[sid] for sid in sids}

    def layer_positions(self, source_type: str) -> Set[Tuple[int, int, int]]:
        """Return the set of (row, col, layer) positions occupied by a sensor type."""
        sids = self._type_index.get(source_type, set())
        return {self._positions[sid] for sid in sids}

    def all_layer_positions(self) -> Dict[str, Set[Tuple[int, int, int]]]:
        """Return {source_type: {(row, col, layer), ...}} for every registered type."""
        return {
            stype: self.layer_positions(stype)
            for stype in self._type_index
        }

    def layer_coverage_ratio(self, source_type: str) -> float:
        """
        Fraction of grid cells covered by sensors of a specific type.

        Returns 0.0–1.0.
        """
        total_cells = self._grid_rows * self._grid_cols * self._grid_layers
        if total_cells == 0:
            return 0.0
        return len(self.layer_positions(source_type)) / total_cells

    # ── Layer experimental knobs ────────────────────────────────────────────

    def thin_layer(self, source_type: str, keep_fraction: float) -> List[str]:
        """
        Randomly remove sensors of a specific type.

        Returns the source_ids of removed sensors.
        """
        if not (0.0 <= keep_fraction <= 1.0):
            raise ValueError(f"keep_fraction must be 0.0–1.0, got {keep_fraction}")

        sids = list(self._type_index.get(source_type, set()))
        keep_count = max(0, int(len(sids) * keep_fraction))
        keep_ids = set(random.sample(sids, min(keep_count, len(sids))))

        removed = []
        for sid in sids:
            if sid not in keep_ids:
                self.unregister(sid)
                removed.append(sid)

        logger.info(
            "Thinned layer %r: kept %d/%d sensors, removed %d",
            source_type, len(sids) - len(removed), len(sids), len(removed),
        )
        return removed

    def inject_layer_failure(
        self,
        source_type: str,
        mode: FailureMode,
        fraction: float = 1.0,
    ) -> List[str]:
        """
        Apply a failure mode to a fraction of sensors in a specific layer.

        Returns the source_ids of affected sensors.
        """
        if not (0.0 <= fraction <= 1.0):
            raise ValueError(f"fraction must be 0.0–1.0, got {fraction}")

        sids = list(self._type_index.get(source_type, set()))
        count = max(0, int(len(sids) * fraction))
        targets = random.sample(sids, min(count, len(sids)))

        for sid in targets:
            self._sensors[sid].set_failure_mode(mode)

        logger.info(
            "Injected %s failure on %d/%d %s sensors",
            mode.value, len(targets), len(sids), source_type,
        )
        return targets

    # ── Coverage analysis ────────────────────────────────────────────────────

    def covered_cells(self) -> Set[Tuple[int, int, int]]:
        """Return the set of grid cells that have at least one sensor."""
        return set(self._positions.values())

    def coverage_ratio(self) -> float:
        """
        Fraction of grid cells that have at least one sensor.

        Returns 0.0–1.0.  A value of 0.3 means 30% of cells have
        sensor coverage.
        """
        total_cells = self._grid_rows * self._grid_cols * self._grid_layers
        if total_cells == 0:
            return 0.0
        return len(self.covered_cells()) / total_cells

    # ── Experimental knobs ───────────────────────────────────────────────────

    def thin(self, keep_fraction: float) -> List[str]:
        """
        Randomly remove sensors to simulate sparse deployment.

        Parameters
        ──────────
        keep_fraction : fraction of sensors to keep (0.0–1.0).
                        0.5 means remove roughly half.

        Returns the source_ids of removed sensors.
        """
        if not (0.0 <= keep_fraction <= 1.0):
            raise ValueError(f"keep_fraction must be 0.0–1.0, got {keep_fraction}")

        all_ids = list(self._sensors.keys())
        keep_count = max(0, int(len(all_ids) * keep_fraction))
        keep_ids = set(random.sample(all_ids, min(keep_count, len(all_ids))))

        removed = []
        for sid in all_ids:
            if sid not in keep_ids:
                self.unregister(sid)
                removed.append(sid)

        logger.info(
            "Thinned inventory: kept %d/%d sensors (%.0f%%), removed %d",
            len(self._sensors), len(all_ids),
            keep_fraction * 100, len(removed),
        )
        return removed

    def inject_failure(self, source_id: str, mode: FailureMode) -> None:
        """
        Set the failure mode on a specific sensor.

        Raises KeyError if the source_id is not registered.
        """
        self._sensors[source_id].set_failure_mode(mode)

    def inject_bulk_failure(
        self,
        mode: FailureMode,
        fraction: float,
    ) -> List[str]:
        """
        Randomly apply a failure mode to a fraction of sensors.

        Parameters
        ──────────
        mode     : the failure mode to inject (STUCK, DROPOUT, DRIFT, SPIKE)
        fraction : fraction of sensors to affect (0.0–1.0)

        Returns the source_ids of affected sensors.
        """
        if not (0.0 <= fraction <= 1.0):
            raise ValueError(f"fraction must be 0.0–1.0, got {fraction}")

        all_ids = list(self._sensors.keys())
        count = max(0, int(len(all_ids) * fraction))
        targets = random.sample(all_ids, min(count, len(all_ids)))

        for sid in targets:
            self._sensors[sid].set_failure_mode(mode)

        logger.info(
            "Injected %s failure on %d/%d sensors (%.0f%%)",
            mode.value, len(targets), len(all_ids), fraction * 100,
        )
        return targets

    def reset_all_failures(self) -> None:
        """Reset all sensors to NORMAL failure mode."""
        for sensor in self._sensors.values():
            sensor.set_failure_mode(FailureMode.NORMAL)

    # ── Emission ─────────────────────────────────────────────────────────────

    def emit_all(self) -> List[SensorEvent]:
        """
        Call emit() on every sensor and collect the results.

        Returns a list of SensorEvents (excluding None from dropout sensors).
        """
        events = []
        for sensor in self._sensors.values():
            event = sensor.emit()
            if event is not None:
                events.append(event)
        return events

    # ── Repr ─────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"SensorInventory(sensors={len(self._sensors)}, "
            f"coverage={self.coverage_ratio():.0%}, "
            f"grid={self._grid_rows}×{self._grid_cols}×{self._grid_layers})"
        )
