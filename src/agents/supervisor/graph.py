"""
ogar.agents.supervisor.graph

Supervisor LangGraph — stub mode.

Topology:
  START
    → fan_out_to_clusters     (conditional edge — returns list[Send])
      → run_cluster_agent     (parallel, one per cluster)
    → assess_situation
    → decide_actions
    → dispatch_commands → END

The Send API pattern
────────────────────
fan_out_to_clusters returns a list of Send() objects. LangGraph runs
all of them in parallel, merges their results into the supervisor
state via the aggregate_findings reducer, then advances to
assess_situation.  This implicit synchronization barrier is the key
LangGraph skill these two graphs together demonstrate.

Why a separate supervisor graph?
─────────────────────────────────
The supervisor is the orchestrator (one instance per batch).
The cluster agent is a worker subgraph (one invocation per cluster).
Splitting them keeps cluster state isolated for parallel execution
and lets the cluster subgraph be tested on its own.

Usage:
  cluster_graph = build_cluster_agent_graph()
  supervisor_graph = build_supervisor_graph(cluster_graph=cluster_graph)
  result = supervisor_graph.invoke(SupervisorState(
      active_cluster_ids=["cluster-north"],
      events_by_cluster={"cluster-north": [event]},
  ))
"""

import logging

from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from agents.cluster.graph import build_cluster_agent_graph
from agents.supervisor.nodes import (
    assess_situation,
    decide_actions,
    fan_out_to_clusters,
    make_dispatch_commands,
    make_run_cluster_agent,
    route_after_decide,
)
from agents.supervisor.state import SupervisorState

logger = logging.getLogger(__name__)


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_supervisor_graph(*, store: BaseStore | None = None):
    """
    Compile and return the supervisor graph (stub mode).

    Builds the cluster agent subgraph internally and threads it into
    the run_cluster_agent node via the make_run_cluster_agent factory.

    Parameters
    ──────────
    store : Optional LangGraph Store. Reserved for future use — when
            wired up, dispatch_commands will write the situation summary
            to ("situations", "global") so future runs can read it.
            Stub mode ignores it.
    """
    cluster_graph = build_cluster_agent_graph(store=store)

    builder = StateGraph(SupervisorState)

    builder.add_node("run_cluster_agent", make_run_cluster_agent(cluster_graph))
    builder.add_node("assess_situation", assess_situation)
    builder.add_node("decide_actions", decide_actions)
    builder.add_node("dispatch_commands", make_dispatch_commands(store=store))

    # fan_out_to_clusters returns list[Send] — must be a conditional edge,
    # NOT a regular node. LangGraph interprets the Sends as parallel
    # dispatches to "run_cluster_agent".
    builder.add_conditional_edges(START, fan_out_to_clusters, ["run_cluster_agent"])

    # After all parallel cluster agents finish (synchronization barrier),
    # assess → decide → dispatch.
    builder.add_edge("run_cluster_agent", "assess_situation")
    builder.add_edge("assess_situation", "decide_actions")
    builder.add_conditional_edges("decide_actions", route_after_decide)
    builder.add_edge("dispatch_commands", END)

    compiled = builder.compile()
    return compiled
