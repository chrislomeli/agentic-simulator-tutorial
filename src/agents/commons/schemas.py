"""
world-simulator.agents.commons.schemas

Cross-agent data contracts for the risk assessment pipeline.

Design intent
─────────────
These schemas define the data that flows through the cluster agent's
risk pipeline:

    SensorEvent (wire) → CellStateManager → CellReadings → agent → RiskAssessment

CellStateManager maintains a running per-cell snapshot of the latest
metrics, thresholds when a cell should re-evaluate, and emits a
CellReadings envelope (cluster_id + position + metrics) per triggered cell.
The cluster agent's update_world node writes those values onto the
world grid — the session ground truth — then evaluate produces
RiskAssessments and writes them back onto each GenericCell.

Separation of concerns
──────────────────────
  - SensorEvent (transport/schemas.py) is the wire format. Domain-agnostic.
  - CellReadings is the agent's input. The minimum needed to update the
    world grid and identify the cell.
  - RiskAssessment is the agent's output. What the supervisor consumes.

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

from agents.commons.node_types import NodeError
from agents.commons.state_types import StatusValue
from domains.wildfire import FireCellState


class Colors:
    BLUE = "\033[94m"
    GREEN = "\033[32m"
    TEAL = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"


# ── Base state ───────────────────────────────────────────────────────────────


class TracedState(BaseModel):
    """
    Minimum contract that node_executor requires from any graph state.

    All agent state classes inherit from this (directly or indirectly)
    to get the three fields that the execution framework needs:
      - session_id: for request tracing across nodes
      - status: for the state machine (idle/processing/completed/error)
      - error: for structured error capture on exception
    """

    session_id: str | None = Field(
        default=None, description="Request correlation ID for tracing across nodes/graphs"
    )
    status: StatusValue = Field(default=StatusValue.IDLE, description="Current state machine value")
    error: NodeError | None = Field(
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
    layer: int = 0  # Default to 0 for 2D scenarios


# ── Sensor reading ────────────────────────────────────────────────────────────


class Metric(BaseModel):
    """A single validated reading extracted from a SensorEvent.

    CellStateManager produces Metrics from raw SensorEvents by:
      1. Extracting the canonical scalar value from the opaque payload
      2. Mapping the sensor's source_id to a GridPosition
      3. Computing signal_strength (sensor confidence × distance decay)
    """

    sensor_id: str = Field(description="Sensor identifier key")
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


# ── The agent's input ─────────────────────────────────────────────────────────


class CellReadings(BaseModel):
    """Latest metrics for a single triggered cell.

    The orchestrator groups CellReadings by cluster_id and the supervisor
    fans them out to per-cluster agents. The cluster agent's update_world
    node consumes CellReadings, writes the metric values onto the matching
    GenericCell.cell_state in the world grid, and emits a cell-dict snapshot
    for the evaluate node.

    This replaces the previous CollatedRecord, which bundled terrain,
    coverage, and trends inline. Terrain now lives on the cell itself
    (FireCellState); trend categorization is attached as a small dict on
    the cell snapshot by update_world.
    """

    cluster_id: str = Field(description="Which cluster this cell belongs to")
    position: GridPosition = Field(description="Grid coordinates of the cell")
    metrics: list[Metric] = Field(
        default_factory=list,
        description="Latest metric per type (temperature, humidity, wind_speed, wind_direction)",
    )


# ── The agent's output ────────────────────────────────────────────────────────


class RiskAssessment(BaseModel):
    collated_record_risks: list[CollatedRecordRisk] = Field(
        description="A risk assessment for each cell in the provided cluster",
        default_factory=list,
    )


class CollatedRecordRisk(BaseModel):
    """Fire risk score for an individual cell."""

    position: GridPosition = Field(
        description="a row/column reference to the specific cell we are evaluating"
    )
    risk_score: int = Field(
        ge=0,
        le=10,
        description="Agent's fire danger estimate integer",
    )
    confidence: int = Field(
        ge=0,
        le=3,
        description="confidence in risk_score",
    )
    confidence_rationale: str = Field(
        description="Why the agent chose this confidence level. "
        "e.g. 'Based on 2/3 sensor types with strong signal; "
        "wind data inferred from 6-hour forecast tool.'"
    )
    contributing_factors: list[str] = Field(
        default_factory=list,
        description="What drove the assessment: e.g. ['temp=52°C (>38 threshold)', "
        "'humidity=12% (<15 critical)', 'terrain=grassland (high fuel)']",
    )


class CellRiskAssessment(BaseModel):
    """Minimal fire risk assessment stored on GenericCell.

    Token-efficient subset of CollatedRecordRisk for ground truth storage.
    The rationale is kept for debugging/tracing but omitted from LLM
    context to save tokens (the sector summary provides enough context
    for decisions).
    """

    risk_score: int = Field(ge=0, le=10)
    confidence: int = Field(ge=0, le=3)
    confidence_rationale: str = Field(default="", description="Reasoning for tracing/debug")


class FireCell(BaseModel):
    row: int
    col: int
    cell_state: FireCellState
    layer: int
    attributes: dict[str, int] | None = None
