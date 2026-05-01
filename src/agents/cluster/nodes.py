"""
ogar.agents.cluster.nodes

Node functions for the cluster agent LangGraph subgraph.

These are the stateful functions that process state — ingest, classify,
report findings, and route between them. Wrapped with @node_trace for
automatic per-node timing and structured logging.

The graph builder (add_node, add_edge, compile) lives in graph.py.
"""

import logging
from typing import Optional
from uuid import uuid4

from langgraph.store.base import BaseStore

from agents.cluster.node_tracer import node_trace
from agents.cluster.state import AnomalyFinding, ClusterAgentState
from agents.routing import _route_base
from agents.state_types import StatusValue

logger = logging.getLogger(__name__)


# ── Node functions ────────────────────────────────────────────────────────────
# Each node receives the full ClusterAgentState state and returns a PARTIAL state update.
# LangGraph merges the partial update into the current state using reducers.
# Nodes should only return the fields they actually changed.
@node_trace("ingest_events")
def ingest_events(state: ClusterAgentState) -> dict:
    """
    First node — acknowledges the trigger event and sets status to processing.
    It takes a ClusterAgentState in, and adds the status to the state - all of the actual processing will happen in the classify node (next)

    In a real implementation this node might also:
      - Validate the incoming event schema
      - Load recent history from the LangGraph Store
      - Decide whether the event is worth classifying (pre-filter)

    For now, we just log and set the status to "processing"
    """

    # Return only the fields we're changing.
    # LangGraph merges this with the existing state.
    return {
        "status": StatusValue.PROCESSING,
        "error_message": None,   # Clear any previous error
    }

@node_trace("classify")
def classify(state: ClusterAgentState) -> dict:
    """
    Stub classify node — used when no LLM is provided.

    Produces a placeholder finding so the rest of the pipeline
    has something to work with end-to-end.
    """

    cluster_id = state.cluster_id
    trigger = state.trigger_event

    stub_finding: AnomalyFinding = AnomalyFinding(
        finding_id= str(uuid4()),
        cluster_id= cluster_id,
        anomaly_type= "stub_placeholder",
        affected_sensors= [trigger.source_id] if trigger else [],
        confidence= 0.5,
        summary= f"[STUB] classify node not yet implemented for cluster {cluster_id}",
        raw_context={
            "trigger_event_id": trigger.event_id if trigger else None,
            "event_count_in_window": len(state.sensor_events),
        },
    )

    return {
        "anomalies": [stub_finding],
        "status": StatusValue.PROCESSING,
    }

def make_report_findings(store: Optional[BaseStore] = None):
    @node_trace("report_findings")
    def report_findings(state: ClusterAgentState) -> dict:
        """
        Final node — logs findings and writes each AnomalyFinding to the
        LangGraph Store so the supervisor can recall past incidents.

        Store write (when store is provided):
          namespace : ("incidents", cluster_id)
          key       : finding_id  (UUID — stable across restarts)
          value     : the full AnomalyFinding dict

        store is injected by LangGraph at compile time via
        builder.compile(store=store) — any node whose signature includes
        `store: Optional[BaseStore]` receives it automatically.
        """
        anomalies = state.anomalies or []
        cluster_id = state.cluster_id

        if store is not None and anomalies:
            for finding in anomalies:
                store.put(
                    ("incidents", cluster_id),
                    finding.finding_id,
                    finding.model_dump(),
                )
            logger.info(
                "ClusterAgent[%s] wrote %d finding(s) to store",
                cluster_id,
                len(anomalies),
            )

        # No state change needed — anomalies are already in state
        return {
            "status": StatusValue.COMPLETED,
        }

    return report_findings

# ── Routers ──────────────────────────────────────────────────────────────────

def route_after_classify(state: ClusterAgentState) -> str:
    return _route_base(state, next_node="report_findings")
