"""
ogar.agents.supervisor.state

State schema for the supervisor LangGraph.

What is the supervisor?
────────────────────────
The supervisor owns the analysis workflow for one batch of triggered
locations:

  1. Receive a batch of events grouped by cluster.
  2. Fan out to cluster agents via the Send API (parallel).
  3. Wait for ALL cluster agents to finish (synchronization barrier).
  4. Assess the overall situation across clusters.
  5. Decide which actuator commands to issue.
  6. Dispatch commands.

Reducers
────────
aggregate_findings: Cluster agents report findings in parallel. The
  reducer merges each parallel update into one accumulated list,
  deduplicated by finding_id, instead of overwriting.

messages: Standard add_messages — appends, never overwrites.

Node responsibilities (skeleton — logic comes later)
──────────────────────────────────────────────────────
  fan_out_to_clusters : Returns List[Send] — one Send per active cluster.
                        Conditional-edge function, NOT a regular node.
  run_cluster_agent   : Wrapper that invokes the cluster subgraph.
                        Receives a ClusterAgentState (from Send), returns
                        a SupervisorState update with cluster_findings.
  assess_situation    : Correlates findings across clusters.
  decide_actions      : Chooses actuator commands.
  dispatch_commands   : Sends commands; final node.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from agents.cluster.state import AnomalyFinding
from agents.state_types import StatusValue


# ── Stub actuator command ────────────────────────────────────────────────────
# A real implementation will live in src/actuators/. For the stub flow we
# just need a structured container the dispatch node can log.

class ActuatorCommand(BaseModel):
    """Tiny stub of an actuator command for the dummy flow."""
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command_type: str
    cluster_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 3


# ── Custom reducer for aggregating cluster findings ──────────────────────────

def aggregate_findings(
    existing: List[AnomalyFinding],
    incoming: List[AnomalyFinding],
) -> List[AnomalyFinding]:
    """
    Accumulate findings from parallel cluster agent invocations.

    Each Send-target run returns its findings as a separate update.
    This reducer merges them into a single list, deduplicating by
    finding_id so a re-invocation cannot double-count.
    """
    existing_ids = {f.finding_id for f in existing}
    new = [f for f in incoming if f.finding_id not in existing_ids]
    return existing + new


# ── Supervisor state ─────────────────────────────────────────────────────────

class SupervisorState(BaseModel):
    """
    The internal working state for one supervisor graph execution.

    One execution = one batch from the event loop / orchestrator.
    """

    # ── Identity ─────────────────────────────────────────────────────
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Input ────────────────────────────────────────────────────────
    # Which clusters fan_out_to_clusters will target.
    active_cluster_ids: List[str] = Field(default_factory=list)

    # Events grouped by cluster_id. Passed in by the caller (event loop).
    # fan_out_to_clusters reads this to populate each cluster agent's
    # sensor_events before invoking it via Send.
    events_by_cluster: Dict[str, List[Any]] = Field(default_factory=dict)

    # ── Aggregated findings (output of cluster fan-out) ──────────────
    # Populated by run_cluster_agent (one update per parallel invocation).
    # The aggregate_findings reducer merges results after the
    # synchronization barrier.
    cluster_findings: Annotated[List[AnomalyFinding], aggregate_findings] = Field(
        default_factory=list
    )

    # ── LLM reasoning (used once an LLM is wired in) ─────────────────
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)

    # ── Decision output ──────────────────────────────────────────────
    pending_commands: List[ActuatorCommand] = Field(default_factory=list)

    # ── Situation summary ────────────────────────────────────────────
    situation_summary: Optional[str] = None

    # ── Control ──────────────────────────────────────────────────────
    status: StatusValue = Field(default=StatusValue.IDLE)
    error_message: Optional[str] = None
