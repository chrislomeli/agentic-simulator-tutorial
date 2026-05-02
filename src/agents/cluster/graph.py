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

from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from agents.cluster.nodes import ingest_events, classify, make_report_findings, route_after_classify
from agents.cluster.state import ClusterAgentState

logger = logging.getLogger(__name__)


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_cluster_agent_graph(*, store: BaseStore | None = None):
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
    builder.add_node("report_findings", make_report_findings(store=store))

    # ── Stub mode: deterministic classify ──────────────────────────
    builder.add_edge(START, "ingest_events")
    builder.add_edge("ingest_events", "classify")
    builder.add_conditional_edges("classify", route_after_classify)

    builder.add_edge("report_findings", END)

    compiled = builder.compile()
    return compiled
