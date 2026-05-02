"""
ogar.agents.cluster.graph

Cluster agent LangGraph subgraph — stub mode.

Topology:
  START → ingest_events → classify → route_after_classify
        → report_findings → END

Session 7 adds make_classify_node(registry), tool_node, and the ReAct
cycle (tool_node → classify). The topology changes there, not here.

Usage:
  graph = build_cluster_agent_graph()
"""

import logging
from typing import Optional

from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from agents.cluster.nodes import (
    classify,
    ingest_events,
    make_report_findings,
    route_after_classify,
)
from agents.cluster.state import ClusterAgentState

logger = logging.getLogger(__name__)


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
    builder.add_node("report_findings", make_report_findings(store=store))

    builder.add_edge(START, "ingest_events")
    builder.add_edge("ingest_events", "classify")
    builder.add_conditional_edges("classify", route_after_classify)
    builder.add_edge("report_findings", END)

    compiled = builder.compile()
    return compiled


# Module-level compiled graph.
# Compiled once at import time; used by the supervisor's run_cluster_agent node.
cluster_agent_graph = build_cluster_agent_graph()
