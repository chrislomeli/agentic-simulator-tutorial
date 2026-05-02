"""
ogar.agents.cluster.graph

Cluster agent LangGraph subgraph — ReAct-ready topology.

Topology:
  START → ingest_events → classify → route_after_classify_llm
                               ↑              ↓ (tool_calls present)
                          tool_node ←─────────
                               ↓ (no tool_calls)
                          report_findings → END

In stub and session-7 (LLM, no tools) modes, classify never produces
tool_calls so the cycle never activates. The topology is pre-wired so
session 8 only needs to swap tool_node for langgraph.prebuilt.ToolNode
with real tools bound.

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
    route_after_classify_llm,
    tool_node,
)
from agents.cluster.state import ClusterAgentState

logger = logging.getLogger(__name__)


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_cluster_agent_graph(store: Optional[BaseStore] = None):
    """
    Compile and return the cluster agent subgraph.

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
    builder.add_node("tool_node", tool_node)
    builder.add_node("report_findings", make_report_findings(store=store))

    builder.add_edge(START, "ingest_events")
    builder.add_edge("ingest_events", "classify")
    builder.add_conditional_edges(
        "classify",
        route_after_classify_llm,
        ["tool_node", "report_findings", END],
    )
    builder.add_edge("tool_node", "classify")  # ReAct cycle
    builder.add_edge("report_findings", END)

    compiled = builder.compile()
    return compiled


# Module-level compiled graph.
# Compiled once at import time; used by the supervisor's run_cluster_agent node.
cluster_agent_graph = build_cluster_agent_graph()
