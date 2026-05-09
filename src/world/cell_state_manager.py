"""
world-simulator.world.cell_state_manager

Stateful per-cell collector that sits between the event stream and
the evaluation pipeline.

Design intent
─────────────
In a real deployment, sensor events arrive one at a time from a message
queue.  The CellStateManager maintains a running picture of each grid
cell's state — latest readings, coverage, terrain — and decides when
a cell's state has changed enough to warrant LLM evaluation.

This replaces batch collation for streaming scenarios:

  batch collate:   [events] → group → [CollatedRecords]     (risk_nodes)
  streaming:       event → update cell → threshold? → emit   (this module)

The manager is NOT a LangGraph node.  It's infrastructure that FEEDS
the graph.  The graph only gets invoked when there's something worth
evaluating.

Lifecycle
─────────
  1. Build once at startup with world_grid + sensor_inventory.
  2. Pre-compute static coverage + terrain per cell.
  3. On each event: update() → returns CollatedRecords for cells
     that crossed evaluation thresholds.
  4. Caller sends those records to the evaluate graph.

Shared extraction logic
───────────────────────
This module also exports the canonical functions for translating opaque
SensorEvent payloads into typed Metrics:

  - extract_metrics(source_type, payload) → [(metric_type, value), ...]
  - get_terrain(world_grid, row, col) → TerrainContext
  - EXPECTED_METRIC_TYPES

Both the streaming CellStateManager and the batch collate node in
nodes.py import from here to avoid duplication.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agents.commons.schemas import (
    CollatedRecord,
    CoverageSummary,
    GridPosition,
    Metric,
    TerrainContext,
    TimeWindow,
)
from transport.schemas import SensorEvent
from world.coverage_index import CoverageIndex
from world.sensor_inventory import SensorInventory

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared payload extraction
# ═══════════════════════════════════════════════════════════════════════════════

# Metric types the agent expects for fire risk assessment.
# Other types (smoke, barometric) are valuable but not expected at every cell —
# their absence doesn't appear in CoverageSummary.absent.
EXPECTED_METRIC_TYPES: list[str] = ["temperature", "humidity", "wind_speed"]

# Maps source_type → payload key for single-metric sensors.
# Wind is handled separately because one WindSensor event produces
# two metrics (wind_speed + wind_direction).
_PAYLOAD_KEYS: dict[str, str] = {
    "temperature": "celsius",
    "humidity": "relative_humidity_pct",
    "smoke": "pm25_ugm3",
    "barometric_pressure": "pressure_hpa",
}


def extract_metrics(
    source_type: str,
    payload: dict[str, Any],
) -> list[tuple[str, float]]:
    """Extract (metric_type, value) pairs from a SensorEvent payload.

    Most sensors produce one metric.  WindSensor produces two separate
    metrics (wind_speed and wind_direction) from one event — consistent
    with the design decision to keep Metric values as single scalars.

    Returns an empty list if the payload doesn't contain expected keys,
    which signals a malformed event that should be skipped.
    """
    # Wind events produce two metrics from one SensorEvent
    if source_type == "wind":
        results: list[tuple[str, float]] = []
        speed = payload.get("speed_mps")
        if speed is not None:
            results.append(("wind_speed", float(speed)))
        direction = payload.get("direction_deg")
        if direction is not None:
            results.append(("wind_direction", float(direction)))
        if not results:
            logger.warning(
                "Wind payload missing speed_mps and direction_deg: %s",
                payload,
            )
        return results

    # All other sensors: one metric per event
    key = _PAYLOAD_KEYS.get(source_type)
    if key is None:
        logger.warning("Unknown source_type %r — cannot extract metric", source_type)
        return []

    value = payload.get(key)
    if value is None:
        logger.warning(
            "Payload for %r missing expected key %r: %s",
            source_type,
            key,
            payload,
        )
        return []

    return [(source_type, float(value))]


def get_terrain(world_grid: Any, row: int, col: int) -> TerrainContext:
    """Look up terrain properties from the world grid.

    Falls back to neutral placeholder values when no grid is available
    (e.g. during early development or unit testing without a world).
    """
    if world_grid is not None:
        try:
            cell = world_grid.get_cell(row, col)
            state = cell.cell_state
            return TerrainContext(
                terrain_type=state.terrain_type.value,
                vegetation=state.vegetation,
                fuel_moisture=state.fuel_moisture,
                slope=state.slope,
            )
        except Exception:
            logger.warning("Failed to get terrain at (%d, %d)", row, col)

    return TerrainContext(
        terrain_type="unknown",
        vegetation=0.5,
        fuel_moisture=0.3,
        slope=0.0,
    )


def resolve_position(
    event: SensorEvent,
    coverage: CoverageIndex | None,
) -> GridPosition | None:
    """Resolve a SensorEvent to its grid cell.

    Tries the coverage index first (authoritative source from the sensor
    inventory).  Falls back to event metadata (grid_row/grid_col injected
    by SensorBase.emit()).  Returns None if neither source provides a
    position.
    """
    if coverage:
        pos = coverage.get_position(event.source_id)
        if pos is not None:
            return pos

    # Fallback: SensorBase.emit() injects grid_row/grid_col into metadata
    meta = event.metadata or {}
    grid_row = meta.get("grid_row")
    grid_col = meta.get("grid_col")
    if grid_row is not None and grid_col is not None:
        return GridPosition(row=int(grid_row), col=int(grid_col))

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation thresholds
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EvaluationThresholds:
    """Controls when a cell's state change warrants LLM evaluation.

    All thresholds are optional gates — any single one being crossed
    triggers evaluation.  Set a value to None to disable that gate.
    """

    # Absolute thresholds — a reading above/below this always triggers
    temperature_high: float | None = 45.0  # °C
    humidity_low: float | None = 15.0  # % — critical fire weather
    wind_speed_high: float | None = 8.0  # m/s (~18 mph sustained)

    # Delta thresholds — change since last evaluation triggers re-eval
    temperature_delta: float | None = 5.0  # °C change
    humidity_delta: float | None = 10.0  # percentage points
    wind_speed_delta: float | None = 5.0  # m/s change

    # Time-based — max seconds between evals for cells that have data
    max_eval_interval_sec: float | None = 300.0  # 5 minutes

    # Minimum distinct metric types required before any threshold fires
    required_metrics = {"temperature", "wind_speed", "humidity"}

    # Coverage change — trigger when a new type appears or disappears
    on_coverage_change: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Per-cell snapshot (internal)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _CellSnapshot:
    """Running state for a single grid cell.

    Tracks the latest metric per type, evaluation history, and
    pre-computed static context (terrain).
    """

    position: GridPosition
    terrain: TerrainContext

    # Cluster this cell currently belongs to. Set from the most recent event
    # that contributed data. TRADE-OFF: a cell can be touched by sensors from
    # multiple clusters via the decay-radius fan-out; "latest writer wins" is
    # a defensible simplification for now. Revisit when cross-cluster overlap
    # actually appears in real data.
    cluster_id: str | None = None

    # Latest metric per metric_type (e.g. "temperature" → Metric)
    metrics: dict[str, Metric] = field(default_factory=dict)

    # Metric types we've seen report at least once
    seen_types: set[str] = field(default_factory=set)

    # ── Evaluation tracking ──────────────────────────────────────────

    last_evaluated_at: datetime | None = None
    last_evaluated_values: dict[str, float] = field(default_factory=dict)
    last_evaluated_types: set[str] = field(default_factory=set)

    def update_metric(self, metric: Metric, cluster_id: str) -> None:
        """Update the latest reading for a metric type."""
        self.metrics[metric.type] = metric
        self.seen_types.add(metric.type)
        self.cluster_id = cluster_id

    def should_evaluate(self, thresholds: EvaluationThresholds) -> bool:
        """Check if any threshold is crossed since last evaluation."""
        if not self.metrics:
            return False

        metrics = set(self.metrics.keys())
        if not thresholds.required_metrics.issubset(metrics):
            return False

        # ── Coverage change ─────────────────────────────────────────
        if thresholds.on_coverage_change:
            if self.seen_types != self.last_evaluated_types:
                return True

        # ── Absolute thresholds ─────────────────────────────────────
        if thresholds.temperature_high is not None:
            temp = self.metrics.get("temperature")
            if temp is not None and temp.value >= thresholds.temperature_high:
                return True

        if thresholds.humidity_low is not None:
            humidity = self.metrics.get("humidity")
            if humidity is not None and humidity.value <= thresholds.humidity_low:
                return True

        if thresholds.wind_speed_high is not None:
            wind = self.metrics.get("wind_speed")
            if wind is not None and wind.value >= thresholds.wind_speed_high:
                return True

        # ── Delta thresholds ────────────────────────────────────────
        delta_checks: list[tuple[str, float | None]] = [
            ("temperature", thresholds.temperature_delta),
            ("humidity", thresholds.humidity_delta),
            ("wind_speed", thresholds.wind_speed_delta),
        ]
        for metric_type, delta in delta_checks:
            if delta is None:
                continue
            current = self.metrics.get(metric_type)
            if current is None:
                continue
            last_val = self.last_evaluated_values.get(metric_type)
            if last_val is None:
                # First reading for this type since last eval → trigger
                return True
            if abs(current.value - last_val) >= delta:
                return True

        # ── Time-based ──────────────────────────────────────────────
        if thresholds.max_eval_interval_sec is not None:
            if self.last_evaluated_at is None:
                # Never evaluated but has data → trigger
                return True
            elapsed = (datetime.now(UTC) - self.last_evaluated_at).total_seconds()
            if elapsed >= thresholds.max_eval_interval_sec:
                return True

        return False

    def to_collated_record(
        self,
        cluster_id: str,
        triggered: bool = False,
    ) -> CollatedRecord:
        """Snapshot the current state as a CollatedRecord.

        ``triggered`` flags this cell as the one whose state change caused
        the cluster's re-evaluation. Other cells in the same cluster
        snapshot are spatial context; the LLM should treat the triggered
        cell as the focal point of its assessment.
        """
        metrics_list = list(self.metrics.values())
        timestamps = [m.timestamp for m in metrics_list]

        present_types = list(self.seen_types)
        absent_types = [t for t in EXPECTED_METRIC_TYPES if t not in self.seen_types]
        signals = [m.signal_strength for m in metrics_list]

        return CollatedRecord(
            cluster_id=cluster_id,
            triggered=triggered,
            position=self.position,
            window=TimeWindow(
                start=min(timestamps),
                end=max(timestamps),
            ),
            metrics=metrics_list,
            coverage=CoverageSummary(
                present=present_types,
                absent=absent_types,
                strongest_signal=max(signals) if signals else 0.0,
                weakest_signal=min(signals) if signals else 0.0,
            ),
            terrain=self.terrain,
        )

    def mark_evaluated(self) -> None:
        """Record that this cell was just sent for evaluation."""
        self.last_evaluated_at = datetime.now(UTC)
        self.last_evaluated_values = {mtype: m.value for mtype, m in self.metrics.items()}
        self.last_evaluated_types = set(self.seen_types)


# ═══════════════════════════════════════════════════════════════════════════════
# CellStateManager
# ═══════════════════════════════════════════════════════════════════════════════


class CellStateManager:
    """Stateful per-cell collector for streaming sensor events.

    Maintains a running picture of each grid cell and emits
    CollatedRecords when evaluation thresholds are crossed.

    Usage
    ─────
      manager = CellStateManager(
          world_grid=grid,
          sensor_inventory=inventory,
      )

      # On each event from the queue:
      records = manager.update(event)
      for record in records:
          evaluate_graph.invoke({"collated_records": [record], ...})

      # Peek at a cell's current state:
      snap = manager.get_snapshot(row=3, col=4)
    """

    def __init__(
        self,
        world_grid: Any = None,
        sensor_inventory: SensorInventory | None = None,
        thresholds: EvaluationThresholds | None = None,
    ) -> None:
        """
        Parameters
        ──────────
        world_grid        : GenericTerrainGrid for terrain context lookup.
        sensor_inventory  : SensorInventory for source_id → GridPosition.
        thresholds        : Controls when cells trigger evaluation.
                            Uses sensible defaults if not provided.
        """
        self._world_grid = world_grid
        self._coverage = CoverageIndex(sensor_inventory) if sensor_inventory else None
        self._thresholds = thresholds or EvaluationThresholds()
        self._cells: dict[tuple[int, int], _CellSnapshot] = {}

    # ── Public API ───────────────────────────────────────────────────────────

    def update(self, event: SensorEvent) -> list[CollatedRecord]:
        """Process one sensor event.

        Updates the sensor's home cell AND nearby cells within the
        coverage decay radius.  Adjacent cells receive the same reading
        at decayed signal strength — giving the LLM richer (but less
        confident) data to reason about.

        Parameters
        ──────────
        event : A single SensorEvent from the queue.

        Returns
        ───────
        A list of CollatedRecords for cells that crossed evaluation
        thresholds.  Usually 0 or 1 records, but multiple cells can
        trigger from a single event if the fan-out crosses thresholds
        on adjacent cells.
        """
        home_pos = resolve_position(event, self._coverage)
        if home_pos is None:
            logger.warning(
                "Cannot map source_id %r to a grid cell — skipping",
                event.source_id,
            )
            return []

        # Extract metrics once — reused across all target cells
        raw_metrics = extract_metrics(event.source_type, event.payload)
        if not raw_metrics:
            return []

        # Determine which cells this event contributes to
        target_cells = self._cells_in_range(home_pos)

        results: list[CollatedRecord] = []

        for target_pos in target_cells:
            snap = self._get_or_create_snapshot(target_pos)

            for metric_type, value in raw_metrics:
                if self._coverage:
                    strength = self._coverage.signal_strength(
                        event.source_id,
                        target_pos.row,
                        target_pos.col,
                        sensor_confidence=event.confidence,
                    )
                    # Fallback: sensor not in inventory but position known
                    # from metadata — compute decay from home_pos directly
                    if strength <= 0.0 and self._coverage.get_position(event.source_id) is None:
                        dist = math.sqrt(
                            (home_pos.row - target_pos.row) ** 2
                            + (home_pos.col - target_pos.col) ** 2
                        )
                        if dist < self._coverage.decay_radius:
                            decay = 1.0 - (dist / self._coverage.decay_radius)
                            strength = event.confidence * decay
                else:
                    strength = event.confidence

                # Skip if signal is effectively zero (beyond radius)
                if strength <= 0.0:
                    continue

                metric = Metric(
                    type=metric_type,
                    value=value,
                    signal_strength=strength,
                    source_id=event.source_id,
                    position=home_pos,
                    timestamp=event.timestamp,
                )
                snap.update_metric(metric, event.cluster_id)

            # Only the home cell can trigger evaluation — adjacent cells
            # accumulate metrics for spatial context but do not independently
            # trigger graph invocations.
            if target_pos == home_pos and snap.should_evaluate(self._thresholds):
                record = snap.to_collated_record(cluster_id=event.cluster_id)
                results.append(record)

        return results

    def snapshot_cluster(
        self,
        cluster_id: str,
        triggered_positions: set[tuple[int, int]] | None = None,
    ) -> list[CollatedRecord]:
        """Snapshot every cell currently associated with a cluster.

        Returns a CollatedRecord per cell that has data and belongs to
        ``cluster_id`` — including cells that did NOT cross thresholds.
        The point is to give the LLM the full cluster picture: a cell
        that triggered evaluation is rarely interesting in isolation,
        and adjacent cells provide critical spatial context.

        ``triggered_positions`` is the set of (row, col) pairs whose
        thresholds actually fired during this drain pass. The matching
        records are returned with ``triggered=True`` so the LLM can
        distinguish the focal cells from the surrounding context.

        Pair with ``mark_cluster_evaluated(cluster_id)`` after the
        graph invocation so future re-evaluations are computed
        relative to the state the LLM actually saw.
        """
        triggers = triggered_positions or set()
        records: list[CollatedRecord] = []
        for snap in self._cells.values():
            if snap.cluster_id != cluster_id:
                continue
            if not snap.metrics:
                continue
            triggered = (snap.position.row, snap.position.col) in triggers
            records.append(snap.to_collated_record(cluster_id=cluster_id, triggered=triggered))
        return records

    def mark_cluster_evaluated(self, cluster_id: str) -> None:
        """Mark every cell in a cluster as evaluated.

        Called by the orchestrator immediately after invoking the graph
        with ``snapshot_cluster(cluster_id)``. This way a cell whose
        readings were *included* in the LLM call (but did not trigger
        the call itself) won't redundantly trigger on the next tick
        just because its delta-since-last-eval crossed a threshold —
        the LLM has already seen its current value.
        """
        for snap in self._cells.values():
            if snap.cluster_id == cluster_id and snap.metrics:
                snap.mark_evaluated()

    def snapshot_halo(
        self,
        center_positions: set[tuple[int, int]],
        triggered_positions: set[tuple[int, int]],
    ) -> dict[str, list[CollatedRecord]]:
        """Get 3x3 halo around triggered cells, grouped by cluster.

        Returns all cells within 1 cell of any triggered position that have
        data, grouped by their cluster_id. This provides spatial context
        without sending the entire cluster.

        Parameters
        ----------
        center_positions : set of (row, col) tuples
            The triggered cell positions (centers of 3x3 windows).
        triggered_positions : set of (row, col) tuples
            Which positions should be marked triggered=True in their records.

        Returns
        -------
        dict[str, list[CollatedRecord]]
            Records grouped by cluster_id. Each cell appears once even if
            it's within multiple halos (triggered flag is preserved).
        """
        seen: set[tuple[int, int]] = set()
        records_by_cluster: dict[str, list[CollatedRecord]] = {}

        for (tr, tc) in center_positions:
            for r in range(tr - 1, tr + 2):
                for c in range(tc - 1, tc + 2):
                    if (r, c) in seen:
                        continue
                    seen.add((r, c))

                    snap = self._cells.get((r, c))
                    if not snap or not snap.metrics:
                        continue

                    cluster_id = snap.cluster_id
                    if cluster_id is None:
                        continue

                    triggered = (r, c) in triggered_positions
                    record = snap.to_collated_record(cluster_id, triggered=triggered)
                    records_by_cluster.setdefault(cluster_id, []).append(record)

        return records_by_cluster

    def mark_cells_evaluated(self, positions: set[tuple[int, int]]) -> None:
        """Mark specific cells as evaluated.

        Called after snapshot_halo() so future evaluations compute deltas
        relative to the state the LLM actually saw.
        """
        for (r, c) in positions:
            snap = self._cells.get((r, c))
            if snap and snap.metrics:
                snap.mark_evaluated()

    def get_snapshot(self, row: int, col: int) -> _CellSnapshot | None:
        """Peek at a cell's current state.  None if no events received."""
        return self._cells.get((row, col))

    def active_cells(self) -> list[tuple[int, int]]:
        """Return (row, col) pairs for cells that have received events."""
        return list(self._cells.keys())

    # ── Internal ─────────────────────────────────────────────────────────────

    def _cells_in_range(self, home: GridPosition) -> list[GridPosition]:
        """Return all grid cells within decay_radius of the home position.

        Always includes the home cell.  When no coverage index is
        configured (no decay radius), returns only the home cell.
        """
        if self._coverage is None:
            return [home]

        radius = int(self._coverage.decay_radius)
        if radius <= 0:
            return [home]

        # Grid bounds
        max_row = self._world_grid.rows if self._world_grid else 9999
        max_col = self._world_grid.cols if self._world_grid else 9999

        cells: list[GridPosition] = []
        for r in range(home.row - radius, home.row + radius + 1):
            if r < 0 or r >= max_row:
                continue
            for c in range(home.col - radius, home.col + radius + 1):
                if c < 0 or c >= max_col:
                    continue
                cells.append(GridPosition(row=r, col=c))

        return cells

    def _get_or_create_snapshot(self, pos: GridPosition) -> _CellSnapshot:
        """Get existing snapshot or create with terrain pre-loaded."""
        key = (pos.row, pos.col)
        if key not in self._cells:
            self._cells[key] = _CellSnapshot(
                position=pos,
                terrain=get_terrain(self._world_grid, pos.row, pos.col),
            )
        return self._cells[key]
