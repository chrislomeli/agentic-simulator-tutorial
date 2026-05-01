"""
ogar.agents.cluster.graph

Cluster agent LangGraph subgraph — stub mode.

Topology:
  START → ingest_events → classify → route_after_classify
        → report_findings → END

Usage:
  graph = build_cluster_agent_graph()

Why a subgraph?
───────────────
The cluster agent is compiled as a standalone subgraph.
The supervisor invokes it as a node (via Send API fan-out).
Each invocation gets its own state, which is why it can run in
parallel for multiple clusters without state collision.

Compiling separately also means it can be tested in isolation —
you can invoke the cluster agent directly with a SensorEvent
without needing the supervisor running.
"""

import logging
from typing import Literal, Optional
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from agents.cluster.state import AnomalyFinding, ClusterAgentState, StatusValue

logger = logging.getLogger(__name__)


# ── Node functions ────────────────────────────────────────────────────────────
# Each node receives the full ClusterAgentState state and returns a PARTIAL state update.
# LangGraph merges the partial update into the current state using reducers.
# Nodes should only return the fields they actually changed.

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
    trigger = state.trigger_event
    logger.info(
        "ClusterAgent[%s]:\tNODE: ingest_events: ingesting event from source=%s",
        state.cluster_id,
        trigger.source_id if trigger else "unknown",
    )

    # Return only the fields we're changing.
    # LangGraph merges this with the existing state.
    return {
        "status": StatusValue.PROCESSING,
        "error_message": None,   # Clear any previous error
    }


def classify(state: ClusterAgentState) -> dict:
    """
    Stub classify node — used when no LLM is provided.

    Produces a placeholder finding so the rest of the pipeline
    has something to work with end-to-end.
    """
    cluster_id = state.cluster_id
    trigger = state.trigger_event

    logger.info(
        "ClusterAgent[%s]:\tNODE classify: STUB (no LLM)",
        cluster_id,
    )

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
        "status": StatusValue.COMPLETED,
    }


def report_findings(state: ClusterAgentState, store: Optional[BaseStore] = None) -> dict:
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

    logger.info(
        "ClusterAgent[%s]\tNODE: report_findings:  reporting %d finding(s) to supervisor",
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
        logger.info(
            "ClusterAgent[%s] wrote %d finding(s) to store",
            cluster_id,
            len(anomalies),
        )

    # No state change needed — anomalies are already in state
    return {}


# ── Routers ──────────────────────────────────────────────────────────────────

def route_after_classify(
    state: ClusterAgentState,
) -> Literal["report_findings", "__end__"]:
    """
    Router for stub mode — classify always goes to report_findings.
    """
    logger.info(
        "ClusterAgent[%s]\tROUTER: route_after_classify ",
        state.cluster_id,
    )

    if state.status == StatusValue.ERROR:
        logger.warning(
            "ClusterAgent[%s] ROUTER: route_after_classify exiting due to error: %s",
            state.cluster_id,
            state.error_message,
        )
        return "__end__"

    return "report_findings"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_cluster_agent_graph(store: Optional[BaseStore] = None):
    """
    Compile and return the cluster agent subgraph (stub mode).

    Returns a compiled LangGraph graph ready for .invoke() or .stream().

    To test the cluster agent in isolation:
      graph = build_cluster_agent_graph()           # no store
      graph = build_cluster_agent_graph(store=s)    # with InMemoryStore
      result = graph.invoke({
          "cluster_id": "cluster-north",
          "workflow_id": "test-run-1",
          "trigger_event": some_sensor_event,
      })
    """

    builder = StateGraph(ClusterAgentState)
    builder.add_node("ingest_events", ingest_events)
    builder.add_node("classify", classify)
    builder.add_node("report_findings", report_findings)

    # ── Stub mode: deterministic classify ──────────────────────────
    builder.add_edge(START, "ingest_events")
    builder.add_edge("ingest_events", "classify")
    builder.add_conditional_edges("classify", route_after_classify)

    builder.add_edge("report_findings", END)

    # Passing store=store makes LangGraph inject it into any node whose
    # signature includes `store: Optional[BaseStore]`.
    # store=None is safe — nodes receive None and guard against it.
    logger.info("ClusterAgent subgraph compiled (stub mode)")
    compiled = builder.compile(store=store)
    return compiled


# Module-level compiled graph (stub mode).
# The graph is compiled once when the module is first imported.
cluster_agent_graph = build_cluster_agent_graph()