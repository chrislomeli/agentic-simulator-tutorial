"""
world-simulator.world.cell_state_manager

Stateful per-cell collector that sits between the event stream and
the evaluation pipeline.

Design intent
─────────────
In a real deployment, sensor events arrive one at a time from a message
queue. CellStateManager maintains a running picture of each grid cell's
state — latest readings, recent history per metric — and decides when
a cell's state has changed enough to warrant LLM evaluation.

Lifecycle
─────────
  1. Build once at startup with world_grid + sensor_inventory.
  2. On each event: update() → returns (cluster_id, row, col) for any
     cells that crossed evaluation thresholds.
  3. After draining one tick's worth of events, the caller asks for
     ``readings_for(positions)`` to build a per-cluster CellReadings
     payload from the latest snapshot state.
  4. Caller invokes the supervisor graph with that payload.

Shared extraction logic
───────────────────────
This module also exports the canonical functions for translating opaque
SensorEvent payloads into typed Metrics:

  - extract_metrics(source_type, payload) → [(metric_type, value), ...]
  - resolve_position(event, coverage) → GridPosition | None
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from agents.commons.schemas import (
    CellReadings,
    GridPosition,
    Metric,
)
from transport.schemas import SensorEvent
from world.coverage_index import CoverageIndex
from world.sensor_inventory import SensorInventory

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared payload extraction
# ═══════════════════════════════════════════════════════════════════════════════

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

    Most sensors produce one metric. WindSensor produces two separate
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


def resolve_position(
    event: SensorEvent,
    coverage: CoverageIndex | None,
) -> GridPosition | None:
    """Resolve a SensorEvent to its grid cell.

    Tries the coverage index first (authoritative source from the sensor
    inventory). Falls back to event metadata (grid_row/grid_col injected
    by SensorBase.emit()). Returns None if neither source provides a
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
# Trend categorization
# ═══════════════════════════════════════════════════════════════════════════════

# Per-minute slope thresholds calibrated for wildfire behavior. Values
# outside these bands round to "stable". Metrics not listed here (e.g.
# wind_direction) are omitted from the trend block.
_TREND_THRESHOLDS: dict[str, dict[str, float]] = {
    "temperature": {
        "rising_fast": 2.0,  # °C / min
        "rising": 0.5,
        "falling": -0.5,
        "falling_fast": -2.0,
    },
    "humidity": {
        "rising_fast": 5.0,  # % / min — drying is dangerous, but both directions reported
        "rising": 2.0,
        "falling": -2.0,
        "falling_fast": -5.0,
    },
    "wind_speed": {
        "rising_fast": 3.0,  # m/s / min
        "rising": 1.0,
        "falling": -1.0,
        "falling_fast": -3.0,
    },
}


def _slope_per_minute(history: deque) -> float | None:
    """Linear-regression slope (value per minute) over a history deque.

    Returns None when there's insufficient data or no time variance.
    """
    if len(history) < 2:
        return None

    base = history[0][0]
    xs = [(t - base).total_seconds() / 60.0 for t, _ in history]
    ys = [v for _, v in history]

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    var_x = sum((x - x_mean) ** 2 for x in xs)
    if var_x == 0:
        return None
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return cov / var_x


def _categorize(metric_type: str, slope: float) -> str:
    """Map a slope value to one of: rising_fast/rising/stable/falling/falling_fast."""
    bands = _TREND_THRESHOLDS[metric_type]
    if slope >= bands["rising_fast"]:
        return "rising_fast"
    if slope >= bands["rising"]:
        return "rising"
    if slope <= bands["falling_fast"]:
        return "falling_fast"
    if slope <= bands["falling"]:
        return "falling"
    return "stable"


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation thresholds
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EvaluationThresholds:
    """Controls when a cell's state change warrants LLM evaluation.

    All thresholds are optional gates — any single one being crossed
    triggers evaluation. Set a value to None to disable that gate.
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

    # Required metric types that must all be present on a cell before any
    # threshold fires. ClassVar marks this as a fixed contract shared across
    # instances (not a configurable per-instance field), and frozenset makes
    # it immutable so accidental mutation can't bleed into other thresholds.
    required_metrics: ClassVar[frozenset[str]] = frozenset(
        {"temperature", "wind_speed", "humidity"}
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Per-cell snapshot (internal)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _CellSnapshot:
    """Running state for a single grid cell.

    Tracks the latest metric per type and recent per-metric history
    used for trend computation.
    """

    position: GridPosition

    # Cluster this cell currently belongs to. Set from the most recent event
    # that contributed data. TRADE-OFF: a cell can be touched by sensors from
    # multiple clusters via the decay-radius fan-out; "latest writer wins" is
    # a defensible simplification for now. Revisit when cross-cluster overlap
    # actually appears in real data.
    cluster_id: str | None = None

    # Latest metric per metric_type (e.g. "temperature" → Metric)
    metrics: dict[str, Metric] = field(default_factory=dict)

    # Short-term history per metric type for trend computation.
    # Each deque holds up to HISTORY_WINDOW recent (timestamp, value) pairs.
    HISTORY_WINDOW: ClassVar[int] = 10
    metric_history: dict[str, deque] = field(default_factory=dict)

    # ── Evaluation tracking ──────────────────────────────────────────

    last_evaluated_at: datetime | None = None
    last_evaluated_values: dict[str, float] = field(default_factory=dict)

    def update_metric(self, metric: Metric, cluster_id: str) -> None:
        """Update the latest reading for a metric type.

        Keeps the strongest-signal reading — a local sensor is never
        clobbered by a weaker fan-out reading from a distant sensor.
        Also appends to the history deque for trend computation.
        """
        existing = self.metrics.get(metric.type)
        if existing is None or metric.signal_strength >= existing.signal_strength:
            self.metrics[metric.type] = metric
        # Always append to history (even weaker signals contribute to trend)
        if metric.type not in self.metric_history:
            self.metric_history[metric.type] = deque(maxlen=self.HISTORY_WINDOW)
        self.metric_history[metric.type].append((metric.timestamp, metric.value))
        self.cluster_id = cluster_id

    def should_evaluate(self, thresholds: EvaluationThresholds) -> bool:
        """Check if any threshold is crossed since last evaluation."""
        if not self.metrics:
            return False

        metrics = set(self.metrics.keys())
        if not thresholds.required_metrics.issubset(metrics):
            return False

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

    def to_readings(self, cluster_id: str) -> CellReadings:
        """Snapshot the current state as a CellReadings envelope."""
        return CellReadings(
            cluster_id=cluster_id,
            position=self.position,
            metrics=list(self.metrics.values()),
        )

    def mark_evaluated(self) -> None:
        """Record that this cell was just sent for evaluation."""
        self.last_evaluated_at = datetime.now(UTC)
        self.last_evaluated_values = {mtype: m.value for mtype, m in self.metrics.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# CellStateManager
# ═══════════════════════════════════════════════════════════════════════════════


class CellStateManager:
    """Stateful per-cell collector for streaming sensor events.

    Maintains a running picture of each grid cell and emits triggered
    cell identifiers when evaluation thresholds are crossed. Callers
    then ask for ``readings_for(positions)`` to build a per-cluster
    CellReadings payload from the latest snapshot state.
    """

    def __init__(
        self,
        world_grid: Any = None,
        sensor_inventory: SensorInventory | None = None,
        thresholds: EvaluationThresholds | None = None,
    ) -> None:
        self._world_grid = world_grid
        self._coverage = CoverageIndex(sensor_inventory) if sensor_inventory else None
        self._thresholds = thresholds or EvaluationThresholds()
        self._cells: dict[tuple[int, int], _CellSnapshot] = {}

    # ── Public API ───────────────────────────────────────────────────────────

    def update(self, event: SensorEvent) -> list[tuple[str, int, int]]:
        """Process one sensor event.

        Updates the sensor's home cell AND nearby cells within the
        coverage decay radius. Adjacent cells receive the same reading
        at decayed signal strength.

        Returns
        ───────
        A list of (cluster_id, row, col) tuples for cells that crossed
        evaluation thresholds on this event. Usually 0 or 1. The caller
        aggregates these across all events in a tick, then asks for the
        full readings via ``readings_for()``.
        """
        home_pos = resolve_position(event, self._coverage)
        if home_pos is None:
            logger.warning(
                "Cannot map source_id %r to a grid cell — skipping",
                event.source_id,
            )
            return []

        raw_metrics = extract_metrics(event.source_type, event.payload)
        if not raw_metrics:
            return []

        target_cells = self._cells_in_range(home_pos)

        triggered: list[tuple[str, int, int]] = []

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

                if strength <= 0.0:
                    continue

                metric = Metric(
                    type=metric_type,
                    value=value,
                    signal_strength=strength,
                    sensor_id=event.source_id,
                    source_id=event.source_id,
                    position=home_pos,
                    timestamp=event.timestamp,
                )
                snap.update_metric(metric, event.cluster_id)

            # Only the home cell can trigger evaluation — adjacent cells
            # accumulate metrics for spatial context but do not independently
            # trigger graph invocations.
            if target_pos == home_pos and snap.should_evaluate(self._thresholds):
                triggered.append((event.cluster_id, home_pos.row, home_pos.col))

        return triggered

    def readings_for(
        self,
        positions: set[tuple[int, int]],
    ) -> dict[str, list[CellReadings]]:
        """Build a per-cluster CellReadings payload for the given positions.

        Snapshots the latest state of each requested cell — so values
        reflect any updates from subsequent events in the same tick,
        not the state at trigger time.
        """
        records_by_cluster: dict[str, list[CellReadings]] = {}

        for r, c in positions:
            snap = self._cells.get((r, c))
            if not snap or not snap.metrics:
                continue

            cluster_id = snap.cluster_id
            if cluster_id is None:
                continue

            records_by_cluster.setdefault(cluster_id, []).append(snap.to_readings(cluster_id))

        return records_by_cluster

    def mark_cells_evaluated(self, positions: set[tuple[int, int]]) -> None:
        """Mark specific cells as evaluated.

        Called after ``readings_for()`` so future evaluations compute
        deltas relative to the state the LLM actually saw.
        """
        for r, c in positions:
            snap = self._cells.get((r, c))
            if snap and snap.metrics:
                snap.mark_evaluated()

    def get_trend(self, row: int, col: int) -> dict[str, str]:
        """Return a categorical trend per metric for the given cell.

        Each value is one of: rising_fast, rising, stable, falling,
        falling_fast. Metrics without a configured threshold band
        (e.g. wind_direction) are omitted. Cells with no history or
        too few readings yield an empty dict.
        """
        snap = self._cells.get((row, col))
        if snap is None:
            return {}

        result: dict[str, str] = {}
        for metric_type, history in snap.metric_history.items():
            if metric_type not in _TREND_THRESHOLDS:
                continue
            slope = _slope_per_minute(history)
            if slope is None:
                continue
            result[metric_type] = _categorize(metric_type, slope)
        return result

    def get_snapshot(self, row: int, col: int) -> _CellSnapshot | None:
        """Peek at a cell's current state. None if no events received."""
        return self._cells.get((row, col))

    def active_cells(self) -> list[tuple[int, int]]:
        """Return (row, col) pairs for cells that have received events."""
        return list(self._cells.keys())

    # ── Internal ─────────────────────────────────────────────────────────────

    def _cells_in_range(self, home: GridPosition) -> list[GridPosition]:
        """Return all grid cells within decay_radius of the home position."""
        if self._coverage is None:
            return [home]

        radius = int(self._coverage.decay_radius)
        if radius <= 0:
            return [home]

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
        key = (pos.row, pos.col)
        if key not in self._cells:
            self._cells[key] = _CellSnapshot(position=pos)
        return self._cells[key]
