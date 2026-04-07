"""
ogar.sensors.base

Abstract base class for all sensors.

Responsibility split
─────────────────────
SensorBase owns:
  - The sensor's identity (source_id, source_type, cluster_id).
  - Assembling the SensorEvent envelope via emit().
  - Tracking the simulation tick counter.
  - Reporting a health / confidence score via health().

The subclass owns:
  - read() — returns a plain dict with domain-specific data.
    This is the ONLY method a new sensor type must implement.

Example: adding a new sensor type
──────────────────────────────────
  class HumiditySensor(SensorBase):
      source_type = "humidity"

      def read(self) -> dict:
          return {"relative_humidity_pct": random.uniform(20, 90)}

That's it.  No envelope logic, no tick management, no Kafka.

Failure modes
─────────────
Real sensors fail in predictable ways.  This base class supports
injecting failure modes so that agents can be tested against them:

  NORMAL    — readings are within expected range
  STUCK     — read() returns the same value every call (frozen sensor)
  DROPOUT   — emit() returns None  (sensor goes silent)
  DRIFT     — a small offset accumulates each tick (calibration decay)
  SPIKE     — occasional large outlier injected into the reading

Failure modes are set externally (e.g. by a scenario script) via
set_failure_mode().  The base class applies the mode in emit() so
subclasses don't have to think about it.

Note: failure mode logic is not implemented in this first pass —
the constants and the set_failure_mode() stub are here so the
interface is established before we build scenarios.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Union

from transport.schemas import SensorEvent

logger = logging.getLogger(__name__)


# ── Failure mode enum ─────────────────────────────────────────────────────────

class FailureMode(str, Enum):
    """
    The set of failure modes a sensor can be put into.

    Using str as the mixin means FailureMode.STUCK == "STUCK" is True,
    which makes logging and JSON serialisation simpler.
    """
    NORMAL  = "NORMAL"   # Sensor is healthy — read() runs as implemented
    STUCK   = "STUCK"    # Sensor returns same value every call
    DROPOUT = "DROPOUT"  # Sensor goes silent — emit() returns None
    DRIFT   = "DRIFT"    # Gradual offset accumulates in numeric readings
    SPIKE   = "SPIKE"    # Occasional large outlier injected


# ── Abstract base class ───────────────────────────────────────────────────────

class SensorBase(ABC):
    """
    Abstract base for all sensor implementations.

    Subclasses MUST implement:
      read() → dict   ← return the domain-specific payload

    Subclasses MAY override:
      health() → float   ← return a confidence score 0.0–1.0
                           Default implementation returns 1.0 when NORMAL,
                           lower values for degraded modes.

    Usage
    ─────
      sensor = MyTemperatureSensor(
          source_id="temp-A1",
          cluster_id="cluster-north",
      )
      event = sensor.emit()          # Returns a SensorEvent or None
      if event:
          publish_to_kafka(event)    # Your transport layer handles this
    """

    def __init__(
        self,
        *,
        source_id: str,
        cluster_id: str,
        grid_row: Optional[int] = None,
        grid_col: Optional[int] = None,
        grid_layer: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Parameters
        ──────────
        source_id   : Stable identifier for this sensor instance.
                      Should be unique within the system. e.g. "temp-A1".
        cluster_id  : Which cluster (and therefore which Kafka topic and
                      cluster agent) this sensor belongs to.
        grid_row    : Row position on the world grid.  Every sensor is a
                      physical device with a location.
        grid_col    : Column position on the world grid.
        grid_layer  : Layer position on the world grid (default None,
                      treated as layer 0 by the inventory).
        metadata    : Optional dict passed through to every SensorEvent
                      this sensor emits.  Good place for static context
                      like geo-coordinates or hardware version.
        """
        self.source_id = source_id
        self.cluster_id = cluster_id
        self.grid_row = grid_row
        self.grid_col = grid_col
        self.grid_layer = grid_layer
        self.metadata = metadata or {}

        # Simulation tick — incremented each time emit() is called.
        # Zero-based.  Stays at 0 in non-simulation use.
        self._tick: int = 0

        # Current failure mode.  Scenario scripts flip this to test agents.
        self._failure_mode: FailureMode = FailureMode.NORMAL

        # Stuck-mode cache: the last real reading, held frozen when stuck.
        self._stuck_payload: Optional[Dict[str, Any]] = None

    # ── Location ──────────────────────────────────────────────────────────────

    @property
    def location(self) -> Union[Tuple[int, int, int], Tuple[int, int], None]:
        """Return sensor position as a tuple, or None if no position is set.

        Returns (row, col, layer) when all three are set,
        (row, col) when only row and col are set, or None.
        """
        if self.grid_row is not None and self.grid_col is not None:
            if self.grid_layer is not None:
                return (self.grid_row, self.grid_col, self.grid_layer)
            return (self.grid_row, self.grid_col)
        return None

    # ── Abstract interface ────────────────────────────────────────────────────

    @property
    @abstractmethod
    def source_type(self) -> str:
        """
        Opaque string tag identifying the sensor type.
        Stored in every SensorEvent envelope as source_type.
        Agents use this to know how to unpack payload.

        Convention: lowercase, hyphen-separated.
        e.g. "temperature", "smoke-density", "wind-speed".

        Define this as a class-level attribute on the subclass:
          class TemperatureSensor(SensorBase):
              source_type = "temperature"
        """
        ...

    @abstractmethod
    def read(self) -> Dict[str, Any]:
        """
        Produce a fresh domain-specific reading.

        Returns a plain dict.  The base class wraps this in a SensorEvent
        envelope — the subclass never touches the envelope.

        This method should NOT apply failure modes.  That is the base
        class's responsibility in emit().

        Example return value for a temperature sensor:
          {"celsius": 42.1, "fahrenheit": 107.8}
        """
        ...

    # ── Health / confidence ───────────────────────────────────────────────────

    def health(self) -> float:
        """
        Return a confidence score for the current reading, 0.0–1.0.

        Default implementation returns values based on failure mode:
          NORMAL  → 1.0
          DRIFT   → 0.7  (degraded but still reporting)
          STUCK   → 0.3  (output is stale, low trust)
          SPIKE   → 0.5  (output is noisy)
          DROPOUT → 0.0  (but emit() returns None in dropout, so this
                          confidence value is never sent)

        Subclasses may override this with a more sophisticated estimate
        (e.g. based on how far a reading is from expected range).
        """
        return {
            FailureMode.NORMAL:  1.0,
            FailureMode.DRIFT:   0.7,
            FailureMode.STUCK:   0.3,
            FailureMode.SPIKE:   0.5,
            FailureMode.DROPOUT: 0.0,
        }[self._failure_mode]

    # ── Failure mode control ──────────────────────────────────────────────────

    def set_failure_mode(self, mode: FailureMode) -> None:
        """
        Set the failure mode.  Called by scenario scripts to simulate faults.

        Example:
          sensor.set_failure_mode(FailureMode.DRIFT)
          # From this point, emit() will apply a drift offset to readings
        """
        logger.debug("Sensor %s failure mode → %s", self.source_id, mode)
        self._failure_mode = mode
        if mode != FailureMode.STUCK:
            # Clear stuck cache when leaving stuck mode so the first
            # real reading after recovery is fresh.
            self._stuck_payload = None

    # ── Core emit ─────────────────────────────────────────────────────────────

    def emit(self) -> Optional[SensorEvent]:
        """
        Produce a SensorEvent envelope wrapping the current reading.

        Returns None if the sensor is in DROPOUT mode (silent sensor).

        This is the primary method called by the sensor runner / publisher.

        The tick counter advances on every call, including dropouts, so
        that scenario scripts can reason about elapsed sim time even when
        a sensor is silent.
        """
        tick = self._tick
        self._tick += 1

        # DROPOUT: sensor goes silent — return None, publish nothing
        if self._failure_mode == FailureMode.DROPOUT:
            logger.debug("Sensor %s DROPOUT at tick %d", self.source_id, tick)
            return None

        # STUCK: return last known reading, frozen
        if self._failure_mode == FailureMode.STUCK:
            if self._stuck_payload is None:
                # First tick in stuck mode — capture a real reading to freeze
                self._stuck_payload = self.read()
            payload = self._stuck_payload

        else:
            # NORMAL / DRIFT / SPIKE: get a fresh reading from the subclass
            payload = self.read()
            # TODO: apply drift offset and spike injection here in a later
            # iteration once scenario scripts are built out.

        # Inject grid location into metadata so downstream consumers
        # can see where this reading came from without changing the
        # SensorEvent schema.
        event_metadata = dict(self.metadata)
        if self.grid_row is not None:
            event_metadata["grid_row"] = self.grid_row
        if self.grid_col is not None:
            event_metadata["grid_col"] = self.grid_col
        if self.grid_layer is not None:
            event_metadata["grid_layer"] = self.grid_layer

        return SensorEvent.create(
            source_id=self.source_id,
            source_type=self.source_type,
            cluster_id=self.cluster_id,
            payload=payload,
            confidence=self.health(),
            sim_tick=tick,
            metadata=event_metadata,
        )

    # ── Repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"source_id={self.source_id!r}, "
            f"cluster_id={self.cluster_id!r}, "
            f"mode={self._failure_mode.value})"
        )
