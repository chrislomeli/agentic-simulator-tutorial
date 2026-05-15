"""
world-simulator.agents.supervisor.graph

Supervisor LangGraph — stub mode (dashboard milestone).

Topology
────────
    START
      → fan_out_to_clusters     (conditional edge — returns list[Send])
        → run_cluster_agent     (parallel, one per cluster)
      → assess_situation
      → run_logistics_agent     (ReAct subgraph: heatmap + resources + wildfire tools)
      → dispatch_commands → END

The Send API pattern
────────────────────
``fan_out_to_clusters`` returns a list of ``Send()`` objects. LangGraph
runs all of them in parallel, merges their results into the supervisor
state via the ``max_cluster_score`` and ``merge_cluster_findings`` reducers,
then advances to ``assess_situation``. This implicit synchronization barrier
is the key LangGraph skill these two graphs together demonstrate.

Why a separate supervisor graph?
─────────────────────────────────
The supervisor is the per-batch orchestrator (one invocation per tick).
The cluster agent is a worker subgraph (one invocation per cluster).
Splitting them keeps cluster state isolated for parallel execution and
lets the cluster subgraph be tested on its own.

Construction
────────────
``build_supervisor_graph`` is the only public entry point. It builds
the cluster subgraph internally, threading the registry and store down
into it, so callers configure dependencies once at the composition root
and the supervisor handles wiring its child graph.
"""

import logging

from langgraph.graph import END, START, StateGraph

from agents.cluster.graph import build_cluster_agent_graph
from agents.commons.agent_dependencies import AgentDependencies
from agents.supervisor.nodes import (
    assess_situation,
    fan_out_to_clusters,
    make_dispatch_commands,
    make_run_cluster_agent,

)
from agents.supervisor.state import SupervisorGraph, SupervisorState

logger = logging.getLogger(__name__)


def build_supervisor_graph(*, agent_dependencies: AgentDependencies) -> SupervisorGraph:
    """Compile and return the supervisor graph.

    Parameters
    ──────────
    agent_deps : AgentDependencies
        DI container with prompt_registry, llm_registry, and optional store.
        The cluster subgraph (built internally) receives these dependencies
        to render prompts, call LLMs, and persist findings.
    """
    cluster_graph = build_cluster_agent_graph(agent_deps=agent_dependencies)

    builder = StateGraph(SupervisorState)
    builder.add_node("run_cluster_agent", make_run_cluster_agent(cluster_graph))
    builder.add_node("assess_situation", assess_situation)
    builder.add_node("dispatch_commands", make_dispatch_commands(store=agent_dependencies.store))

    # fan_out_to_clusters returns list[Send] — must be a conditional edge,
    # NOT a regular node. LangGraph interprets the Sends as parallel
    # dispatches to "run_cluster_agent".
    builder.add_conditional_edges(START, fan_out_to_clusters, ["run_cluster_agent"])

    # After all parallel cluster agents finish (synchronization barrier):
    # assess the situation, call logistics agent for a deployment plan, dispatch.
    builder.add_edge("run_cluster_agent", "assess_situation")
    builder.add_edge("assess_situation", "dispatch_commands")
    builder.add_edge("dispatch_commands", END)

    return SupervisorGraph(builder.compile())
