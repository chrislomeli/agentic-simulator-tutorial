"""
ogar.agents.cluster.nodes

Node functions for the cluster agent LangGraph subgraph.

These are the stateful functions that process state — ingest, classify,
report findings, and route between them.

The graph builder (add_node, add_edge, compile) lives in graph.py.
"""

import logging
from uuid import uuid4

from langgraph.store.base import BaseStore

from agents.cluster.state import ClusterAgentState
from agents.schemas import AnomalyFinding
from agents.routing import _route_base
from agents.state_types import StatusValue

logger = logging.getLogger(__name__)


# ── Node functions ────────────────────────────────────────────────────────────
# Each node receives the full ClusterAgentState state and returns a PARTIAL state update.
# LangGraph merges the partial update into the current state using reducers.
# Nodes should only return the fields they actually changed.

def ingest_events(state: ClusterAgentState) -> dict:
    """
    First node — acknowledges the trigger event and sets status to processing.

    In a real implementation this node might also:
      - Validate the incoming event schema
      - Load recent history from the LangGraph Store
      - Decide whether the event is worth classifying (pre-filter)

    For now, we just log and set the status to "processing"
    """
    trigger = state.trigger_event
    logger.info(
        "ClusterAgent[%s] ingest_events: ingesting event from source=%s",
        state.cluster_id,
        trigger.source_id if trigger else "unknown",
    )
    return {
        "status": StatusValue.PROCESSING,
        "error_message": None,
    }


def classify(state: ClusterAgentState) -> dict:
    """
    Stub classify node — produces a placeholder finding so the rest of the
    pipeline has something to work with end-to-end.
    """
    cluster_id = state.cluster_id
    trigger = state.trigger_event

    logger.info("ClusterAgent[%s] classify: STUB (no LLM)", cluster_id)

    stub_finding = AnomalyFinding(
        finding_id=str(uuid4()),
        cluster_id=cluster_id,
        anomaly_type="stub_placeholder",
        affected_sensors=[trigger.source_id] if trigger else [],
        confidence=0.5,
        summary=f"[STUB] classify node not yet implemented for cluster {cluster_id}",
        raw_context={
            "trigger_event_id": trigger.event_id if trigger else None,
            "event_count_in_window": len(state.sensor_events),
        },
    )

    return {
        "anomalies": [stub_finding],
        "status": StatusValue.COMPLETED,
    }


def make_report_findings(store: BaseStore | None = None):
    def report_findings(state: ClusterAgentState) -> dict:
        """
        Final node — logs findings and writes each AnomalyFinding to the
        LangGraph Store so the supervisor can recall past incidents.
        """
        anomalies = state.anomalies or []
        cluster_id = state.cluster_id

        logger.info(
            "ClusterAgent[%s] report_findings: reporting %d finding(s)",
            cluster_id,
            len(anomalies),
        )

        if store is not None and anomalies:
            for finding in anomalies:
                store.put(
                    ("incidents", cluster_id),
                    finding.finding_id,
                    finding.model_dump(),
                )

        return {"status": StatusValue.COMPLETED}

    return report_findings


# ── Routers ──────────────────────────────────────────────────────────────────

def route_after_classify(state: ClusterAgentState) -> str:
    return _route_base(state, next_node="report_findings")
