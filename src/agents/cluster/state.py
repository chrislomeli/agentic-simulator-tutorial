"""
ogar.agents.cluster.state

State schema for the cluster agent LangGraph subgraph.

What is a cluster agent?
────────────────────────
One cluster agent runs per geographic/logical cluster of sensors.
Its job is to:
  1. Accumulate sensor events from its cluster (rolling window).
  2. Run a LangGraph tool loop to classify anomalies.
  3. Report findings (structured anomaly records) upward to the supervisor.

The cluster agent is a LangGraph subgraph — it has its own state schema
that is separate from the supervisor's state.  The supervisor maps
its own state in/out when it invokes the cluster agent subgraph.

State design principles
────────────────────────
  - Only fields that at least one node reads OR writes belong here.
  - Fields the LLM tool loop needs (messages) use LangGraph's add_messages
    reducer so new messages are appended rather than overwriting the list.
  - sensor_events uses a custom reducer (append-only) for the same reason:
    we want to accumulate events across invocations, not replace them.
  - Fields are Optional where they may not be set yet at graph start.

Node responsibilities (skeleton — logic comes later)
──────────────────────────────────────────────────────
  ingest_events    : Receives incoming SensorEvent, adds to sensor_events.
                     Sets status to "processing".
  classify         : LLM tool loop node.  Reads sensor_events and messages.
                     Uses tools to query history, cross-reference readings.
                     Writes anomalies when detected.
  report_findings  : Packages anomalies into Finding objects for the supervisor.
                     Sets status to "complete".
"""

from __future__ import annotations

import uuid
from typing import Annotated
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from agents.state_types import StatusValue
from transport.schemas import SensorEvent





# ── Custom reducer for sensor event accumulation ──────────────────────────────

def append_events(
        existing: List[SensorEvent],
        new: List[SensorEvent],
) -> List[SensorEvent]:
    """
    Reducer that appends new sensor events to the existing list.

    LangGraph calls the reducer when a node returns a partial state update.
    Without a reducer, the default behaviour is to OVERWRITE the field.
    With this reducer, returning {"sensor_events": [new_event]} APPENDS
    to the existing list rather than replacing it.

    We also cap the window at MAX_EVENT_WINDOW to prevent unbounded growth.
    The oldest events are dropped first.
    """
    MAX_EVENT_WINDOW = 50  # Keep the last 50 events per cluster agent
    combined = existing + new
    return combined[-MAX_EVENT_WINDOW:]  # Trim from the front (oldest first)



# ── Finding model ─────────────────────────────────────────────────────────────

class AnomalyFinding(BaseModel):
    """
    A structured anomaly record produced by the cluster agent.

    The cluster agent writes these; the supervisor reads them.

    finding_id      : UUID string.
    cluster_id      : Which cluster detected this.
    anomaly_type    : e.g. "sensor_fault", "threshold_breach", "correlated_event"
    affected_sensors: List of source_ids involved.
    confidence      : Agent's confidence this is a real event (not noise).
    summary         : Human-readable description for the supervisor's context.
    raw_context     : Relevant sensor readings that led to this finding.
                      Passed to the supervisor for cross-cluster correlation.
    """
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_id: str
    anomaly_type: str
    affected_sensors: List[str] = Field(default_factory=list)
    confidence: float
    summary: str
    raw_context: Dict[str, Any]



# ── Cluster agent state ───────────────────────────────────────────────────────

class ClusterAgentState(BaseModel):
    """
    The internal working state for a single cluster agent execution.

    This state lives inside the LangGraph subgraph.
    It is NOT shared directly with the supervisor — the supervisor
    invokes the subgraph and receives only the output mapping.
    """

    # ── Identity ──────────────────────────────────────────────────────
    cluster_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # Which workflow execution this state belongs to.
    # Matches the workflow_id in WorkflowRunner.
    workflow_id: str

    # ── Incoming sensor data ──────────────────────────────────────────
    # Annotated with append_events reducer so new events accumulate.
    # ingest_events node writes here; classify node reads here.
    sensor_events: Annotated[List[SensorEvent], append_events] = Field(default_factory=list)

    # The single most-recent event that triggered this invocation.
    # Separate from sensor_events so classify can easily find the trigger.
    trigger_event: Optional[SensorEvent]

    # ── LLM tool loop ─────────────────────────────────────────────────
    # add_messages reducer appends new messages rather than overwriting.
    # classify node reads and writes here via the ToolNode loop.
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)

    # ── Findings output ───────────────────────────────────────────────
    # Populated by classify when anomalies are detected.
    # Read by report_findings to package for the supervisor.
    anomalies: List[AnomalyFinding] = Field(default_factory=list)

    # ── Control ───────────────────────────────────────────────────────
    # idle       : Waiting for a new trigger event
    # processing : Currently running the classify loop
    # complete   : Finished this invocation, findings are ready
    # error      : Something went wrong — details in error_message
    status: StatusValue = Field(default=StatusValue.IDLE)

    error_message: Optional[str]
