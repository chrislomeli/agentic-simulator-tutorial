"""
world-simulator.agents.supervisor.state

State schema for the supervisor LangGraph.

What is the supervisor?
────────────────────────
The supervisor owns the analysis workflow for one batch of triggered
locations:

  1. Receive a batch of CollatedRecords grouped by cluster.
  2. Fan out to cluster agents via the Send API (parallel execution).
  3. Wait for ALL cluster agents to finish (synchronization barrier).
  4. Assess the overall situation across clusters.
  5. Decide which actuator commands to issue.
  6. Dispatch commands.

Reducers
────────
max_cluster_score: Records the highest risk score reported for each cluster
  across parallel cluster-agent sends in a single tick. Because each cluster
  is sent exactly once per tick, this is effectively a last-write-wins merge,
  with max() as the defensive fallback if that ever changes.

merge_cluster_findings: Stores the full list of CollatedRecordRisk objects
  per cluster. Per-cluster entries overwrite (each cluster is sent once).

messages: Standard add_messages — appends, never overwrites.

Node responsibilities
──────────────────────
  fan_out_to_clusters : Conditional-edge function (not a node) that returns
                        list[Send] — one Send per active cluster.
  run_cluster_agent   : Invokes the cluster subgraph; lifts risk scores and
                        findings into supervisor state via reducers.
  assess_situation    : Stub — summarises findings across clusters.
  decide_actions      : Stub — returns empty command list.
  dispatch_commands   : Stub — logs commands; final node before END.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, NewType

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from agents.commons.schemas import CollatedRecord, CollatedRecordRisk, TracedState

# ── Typed graph ────────────────────────────────────────────────────
SupervisorGraph = NewType("SupervisorGraph", CompiledStateGraph)


# ── Stub actuator command ────────────────────────────────────────────────────
# Real implementation lives in src/actuators/. For the stub flow we
# just need a structured container the dispatch node can log.


class ActuatorCommand(BaseModel):
    """Stub actuator command — placeholder until src/actuators/ is implemented."""

    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command_type: str
    cluster_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 3


# ── Reducers ─────────────────────────────────────────────────────────────────


def max_cluster_score(
    existing: dict[str, RiskScore],
    incoming: dict[str, RiskScore],
) -> dict[str, RiskScore]:

    merged = dict(existing)
    for cluster_id, score in incoming.items():
        current = merged.get(cluster_id)
        merged[cluster_id] = (
            max([current, score], key=lambda s: s.risk_score if s else -1) if current else score
        )
    return merged


def merge_cluster_findings(
    existing: dict[str, list[CollatedRecordRisk]],
    incoming: dict[str, list[CollatedRecordRisk]],
) -> dict[str, list[CollatedRecordRisk]]:
    """Merge per-cluster risk findings by overwriting each cluster's entry.

    Each cluster is fanned-out exactly once per supervisor invocation, so
    the incoming entry for a cluster always replaces the prior value.
    """
    merged = dict(existing)
    for cluster_id, risks in incoming.items():
        merged[cluster_id] = risks
    return merged


# ── Supervisor state ─────────────────────────────────────────────────────────


class RiskScore(BaseModel):
    risk_score: int
    confidence: int


class SupervisorState(TracedState):
    """
    The internal working state for one supervisor graph execution.

    One execution = one batch of CollatedRecords from the orchestrator.
    """

    # ── Identity ─────────────────────────────────────────────────────
    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Input ────────────────────────────────────────────────────────
    clusters: dict[str, list[CollatedRecord]] = Field(default_factory=dict)

    # ── Aggregated output of cluster fan-out ─────────────────────────
    cluster_score: Annotated[dict[str, RiskScore], max_cluster_score] = Field(default_factory=dict)

    cluster_findings: Annotated[dict[str, list[CollatedRecordRisk]], merge_cluster_findings] = (
        Field(default_factory=dict)
    )

    # ── LLM reasoning (reserved for when the LLM is wired in) ────────
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)

    # ── Decision output ──────────────────────────────────────────────
    pending_commands: list[ActuatorCommand] = Field(default_factory=list)

    # ── Situation summary ────────────────────────────────────────────
    situation_summary: str | None = None
