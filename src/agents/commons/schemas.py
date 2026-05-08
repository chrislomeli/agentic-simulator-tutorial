"""
world-simulator.agents.commons.risk_schemas

Cross-agent data contracts for the risk assessment pipeline.

Design intent
─────────────
These schemas define the data that flows through the cluster agent's
risk pipeline:

    SensorEvent (wire) → collate (deterministic) → CollatedRecord → agent → RiskAssessment

The collation step groups raw SensorEvents by spatial+temporal adjacency,
attaches static terrain data from the world map, and produces CollatedRecords.
The agent (LLM) receives CollatedRecords and reasons about fire risk —
using tools when the available data is insufficient for a confident assessment.

Separation of concerns
──────────────────────
  - SensorEvent (transport/schemas.py) is the wire format. Domain-agnostic.
  - CollatedRecord is the agent's input. Pre-digested, typed, informational.
  - RiskAssessment is the agent's output. What the supervisor consumes.

These schemas intentionally carry NO logic — they are pure data contracts.
The collation node, the agent, and the supervisor each own their own logic
but agree on these shapes at their boundaries.

Coordinate convention
─────────────────────
GridPosition follows GenericTerrainGrid's convention:
  - row 0 = NORTH edge, increasing row = southward
  - col 0 = WEST edge, increasing col = eastward
  - (0, 0) = north-west corner
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from agents.commons.state_types import StatusValue


# ── Spatial primitives ────────────────────────────────────────────────────────
class TracedState(BaseModel):
    """
        Minimum contract that node_executor requires from any graph state.

        All agent state classes inherit from this (directly or indirectly)
        to get the three fields that the execution framework needs:
          - session_id: for request tracing across nodes
          - status: for the state machine (idle/processing/completed/error)
          - error: for structured error capture on exception

        Concrete states add their own fields (e.g., sensor_events, findings)
    on top of this base.
    """

    session_id: str | None = Field(
        default=None, description="Request correlation ID for tracing across nodes/graphs"
    )
    status: StatusValue = Field(default=StatusValue.IDLE, description="Current state machine value")
    error: dict | None = Field(
        default=None, description="Structured error record if last node raised exception"
    )


# ── Spatial primitives ────────────────────────────────────────────────────────


class GridPosition(BaseModel):
    """A cell's location on the simulation grid.

    Coordinate convention (matches GenericTerrainGrid):
      - row 0 = NORTH edge, increasing row = southward
      - col 0 = WEST edge, increasing col = eastward
      - (0, 0) = north-west corner

    Adjacency: neighbors are ±1 in either axis (8-connected).
    """

    row: int
    col: int


# ── Temporal primitives ───────────────────────────────────────────────────────


class TimeWindow(BaseModel):
    """A bounded time segment for grouping sensor readings.

    All readings within a window are considered contemporaneous for
    the purpose of risk assessment. Window size is a configuration
    choice — small windows give responsiveness, large windows give
    stability.
    """

    start: datetime
    end: datetime
    sim_tick_start: int = 0
    sim_tick_end: int = 0


# ── Collation input: what sensors reported ────────────────────────────────────


class Metric(BaseModel):
    """A single validated reading extracted from a SensorEvent.

    The collation step produces Metrics from raw SensorEvents by:
      1. Extracting the canonical scalar value from the opaque payload
      2. Mapping the sensor's source_id to a GridPosition
      3. Computing signal_strength (sensor confidence × distance decay)

    The agent never sees raw SensorEvents — only Metrics.
    """

    type: str = Field(
        description="Sensor type: 'temperature', 'humidity', 'wind_speed', 'wind_direction'"
    )
    value: float = Field(description="Canonical scalar value (celsius, %, m/s, degrees)")
    signal_strength: float = Field(
        ge=0.0,
        le=1.0,
        description="Combined reliability: sensor confidence × distance decay. "
        "1.0 = sensor is at this cell with full health. "
        "0.0 = reading is unreliable for this cell.",
    )
    source_id: str = Field(description="Which sensor produced this reading")
    position: GridPosition = Field(description="Where the sensor sits on the grid")
    timestamp: datetime = Field(description="When the reading was taken (UTC)")


# ── Collation metadata ───────────────────────────────────────────────────────


class CoverageSummary(BaseModel):
    """What sensor data is available for this cell in this window.

    This is descriptive, not prescriptive. The agent decides whether
    the available data is sufficient to assess risk, and at what
    confidence. More coverage → higher confidence. Gaps → the agent
    may use tools to compensate.

    Example: present=["temperature", "humidity"], absent=["wind_speed"]
    means the agent has two readings but no wind data for this cell.
    """

    present: list[str] = Field(
        default_factory=list, description="Sensor types with at least one reading in this window"
    )
    absent: list[str] = Field(
        default_factory=list, description="Expected sensor types with no reading in this window"
    )
    strongest_signal: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Best signal_strength among available metrics"
    )
    weakest_signal: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Worst signal_strength among available metrics"
    )


class TerrainContext(BaseModel):
    """Static properties of a grid cell, joined from the world map at collation time.

    These values are set during scenario initialization and do not change
    during a simulation run. They are attached unconditionally so the agent
    has basic terrain awareness without needing a tool call.

    The agent uses these to contextualize sensor readings — for example,
    high temperature over water is less concerning than over dry grassland.
    """

    terrain_type: str = Field(
        description="Land classification: 'grassland', 'forest', 'rock', 'water'"
    )
    vegetation: float = Field(
        ge=0.0, le=1.0, description="Density of burnable material (0.0 = bare, 1.0 = dense)"
    )
    fuel_moisture: float = Field(
        ge=0.0, le=1.0, description="How wet the fuel is (0.0 = bone dry, 1.0 = saturated)"
    )
    slope: float = Field(description="Terrain gradient in degrees (positive = uphill)")


# ── The agent's input ─────────────────────────────────────────────────────────


class CollatedRecord(BaseModel):
    """A time-windowed, spatially-grouped set of metrics ready for evaluation.

    This is what the agent receives. One CollatedRecord represents
    everything known about a single grid cell in a single time window.

    The agent's job:
      - If coverage is strong and readings are clear → evaluate directly
      - If coverage has gaps or signals are weak → use tools to gather
        more context before classifying
      - Always produce a RiskAssessment with calibrated confidence
    """

    cluster_id: str = Field(description="Which cluster this cell belongs to")
    triggered: bool = Field(
        default=False,
        description="True for cells that recently changed and therefore  caused this record to be sent.",
    )

    position: GridPosition = Field(
        description="Which grid cell in the map (row/column) this record covers"
    )
    window: TimeWindow = Field(description="Time segment these readings were taken in")
    metrics: list[Metric] = Field(
        default_factory=list, description="All validated readings for this cell in this window"
    )
    coverage: CoverageSummary = Field(
        default_factory=CoverageSummary,
        description="Summary of what sensor types are present vs absent",
    )
    terrain: TerrainContext = Field(description="Static terrain properties of the given position")


# ── The agent's output ─────────────────────────────────────────────────────────
class RiskAssessment(BaseModel):
    collated_record_risks: list[CollatedRecordRisk] = Field(
        description="A risk assessment for each CollatedRecord in the provided cluster",
        default_factory=list,
    )


class CollatedRecordRisk(BaseModel):
    """
    Fire risk score for an individual cell (CollatedRecord)

    """

    position: GridPosition = Field(
        description="a row /column reference to the specific record we are evaluating"
    )
    risk_score: int = Field(
        ge=0,
        le=10,
        description="Agent's fire danger estimate (0 = no danger, 5 = moderate danger, 10 = extreme danger)",
    )
    confidence: float = Field(
        ge=0,
        le=3,
        description="0 = no confidence, 2 = some confidence, 3 = good confidence, 4 = very confident",
    )
    confidence_rationale: str = Field(
        description="Why the agent chose this confidence level. "
        "e.g. 'Based on 2/3 sensor types with strong signal; "
        "wind data inferred from 6-hour forecast tool.'"
    )
    contributing_factors: list[str] = Field(
        default_factory=list,
        description="What drove the assessment: ['temp=52°C (>38 threshold)', "
        "'humidity=12% (<15 critical)', 'terrain=grassland (high fuel)']",
    )
