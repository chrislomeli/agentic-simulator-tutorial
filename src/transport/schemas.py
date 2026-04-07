"""
ogar.transport.schemas

The canonical SensorEvent envelope.

Design intent
─────────────
This envelope is the ONLY thing that crosses the wire between a sensor
and the rest of the system.  It is deliberately domain-agnostic:

  - The envelope knows HOW to route an event (cluster_id, source_id).
  - The envelope knows WHEN it happened (timestamp, sim_tick).
  - The envelope knows HOW MUCH TO TRUST IT (confidence).
  - The envelope does NOT know WHAT the reading means.

All domain-specific meaning lives inside `payload`, which is an opaque
dict.  A temperature sensor puts {"celsius": 42.1} in payload.  A smoke
sensor puts {"density_ppm": 300} in payload.  The envelope never touches
either.  Agents unpack payload themselves after routing.

This separation means:
  - You can add new sensor types without changing the envelope.
  - The bridge consumer (Kafka → WorkflowRunner) never needs updating
    when a new domain is added.
  - Tests for the transport layer don't need to know about wildfires,
    ocean buoys, or any other scenario skin.

Fields
──────
event_id    : UUID string, set by the sensor at emit time.
              Downstream consumers use this for deduplication.

source_id   : Stable identifier for the specific sensor instance.
              e.g. "temp-sensor-A1", "smoke-detector-B3".
              Stable means it does not change between runs — it is
              how you track a sensor's history over time.

source_type : Opaque string tag set by the sensor implementation.
              e.g. "temperature", "smoke", "wind".
              Agents use this to know how to unpack payload.
              It is a string (not an enum) so new types can be added
              without touching this file.

cluster_id  : Routing key.  The bridge consumer reads this field to
              decide which workflow (cluster agent) gets the event.
              e.g. "cluster-north", "cluster-south".

timestamp   : Wall-clock datetime of the reading, set by the sensor.
              Always UTC.  Used for ordering and windowing.

sim_tick    : Integer simulation tick counter.  0 if not running in
              simulation mode.  Useful for replaying scenarios at
              a controlled pace independent of wall-clock time.

confidence  : Float 0.0–1.0.  Set by the sensor based on its own
              health estimate.  1.0 = sensor is fully reliable.
              0.0 = sensor is reporting but considers itself faulty.
              Agents can use this to weight readings.

payload     : The actual reading data.  Opaque dict.  The envelope
              carries it but never inspects it.  Structure is
              defined by the sensor type and documented in the
              sensor's own module.

metadata    : Optional dict for extras that don't fit elsewhere.
              e.g. firmware version, geo-coordinates, signal strength.
              Envelope never uses this — it is pass-through context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, Field


class SensorEvent(BaseModel):
    """
    The transport envelope for all sensor readings.

    Create one with SensorEvent.create(...) rather than the constructor
    directly — the factory sets event_id and timestamp automatically.
    """

    # ── Routing fields ────────────────────────────────────────────────
    event_id: str = Field(
        description="UUID string. Unique per emission. Used for dedup downstream."
    )
    source_id: str = Field(
        description="Stable sensor instance identifier. e.g. 'temp-sensor-A1'."
    )
    source_type: str = Field(
        description="Opaque string tag. Tells agents how to unpack payload. "
                    "e.g. 'temperature', 'smoke', 'wind'."
    )
    cluster_id: str = Field(
        description="Routing key. Bridge consumer uses this to pick the target workflow."
    )

    # ── Timing fields ─────────────────────────────────────────────────
    timestamp: datetime = Field(
        description="UTC wall-clock time of the reading."
    )
    sim_tick: int = Field(
        default=0,
        description="Simulation tick counter. 0 when not in simulation mode."
    )

    # ── Trust field ───────────────────────────────────────────────────
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Sensor self-reported health. 1.0 = fully reliable. "
                    "0.0 = sensor considers itself faulty."
    )

    # ── Opaque content ────────────────────────────────────────────────
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific reading data. Envelope never inspects this."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional pass-through extras. Firmware version, GPS coords, etc."
    )

    # ── Factory method ────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        source_type: str,
        cluster_id: str,
        payload: Dict[str, Any],
        confidence: float = 1.0,
        sim_tick: int = 0,
        metadata: Dict[str, Any] | None = None,
    ) -> "SensorEvent":
        """
        Build an envelope with auto-generated event_id and current UTC timestamp.

        Use this factory instead of the constructor directly so callers
        don't have to think about event_id or timestamp generation.

        Example
        -------
        event = SensorEvent.create(
            source_id="temp-A1",
            source_type="temperature",
            cluster_id="cluster-north",
            payload={"celsius": 42.1},
            confidence=0.95,
        )
        """
        return cls(
            event_id=str(uuid4()),
            source_id=source_id,
            source_type=source_type,
            cluster_id=cluster_id,
            timestamp=datetime.now(timezone.utc),
            sim_tick=sim_tick,
            confidence=confidence,
            payload=payload,
            metadata=metadata or {},
        )

    def model_post_init(self, __context: Any) -> None:
        """Clamp confidence to [0.0, 1.0] as a safety net after construction."""
        # Pydantic's ge/le validators cover this, but being explicit about
        # the intent is clearer than relying purely on field constraints.
        object.__setattr__(self, "confidence", max(0.0, min(1.0, self.confidence)))
