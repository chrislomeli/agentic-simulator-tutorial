"""
world-simulator.agents.cluster.graph

Cluster agent LangGraph subgraph.

Topology
────────
    START → ingest_events → evaluate → route_after_classify
          → report_findings → END

Construction
────────────
``build_cluster_agent_graph`` is the only public entry point. It takes
the long-lived dependencies (``PromptRegistry``, optional ``BaseStore``)
that the nodes need and threads them in via the ``make_*`` factories.

There is deliberately no module-level compiled graph here. Compiling at
import time would force every consumer to share a single registry/store
configuration and would also run side-effecting work just to import the
module — both make tests harder and leak state across runs.
"""

import logging

from langgraph.graph import END, START, StateGraph

from agents.cluster.nodes import (
    make_evaluate_node,
    make_report_risk_node,
    make_update_world_state,
    route_after_evaluate,
)
from agents.cluster.state import ClusterAgentState, StreamingRiskGraph
from agents.commons.agent_dependencies import AgentDependencies

logger = logging.getLogger(__name__)


def build_cluster_agent_graph(
    *,
    agent_deps: AgentDependencies,
) -> StreamingRiskGraph:
    """Compile the streaming-risk variant of the cluster subgraph.

    Topology
    ────────
        START → evaluate → route_after_evaluate → report_risk → END

    Notably **does not** include the `collate` node. This variant
    expects the caller (the runtime orchestrator) to pre-populate
    ``state.collated_records`` from a streaming collator
    (``CellStateManager``). Including ``collate`` would overwrite
    those records — see docs/runtime-orchestrator.md § Verified facts.

    Use ``build_cluster_agent_graph`` for the demo path that consumes
    raw ``SensorEvent``s in batch.

    Parameters
    ──────────
    agent_deps : AgentDependencies
        DI container with prompt_registry, llm_registry, and optional
        store. The evaluate node uses prompt_registry for the system
        prompt and llm_registry for model lookup. report_risk uses
        store to persist RiskAssessment records.
    """
    builder = StateGraph(ClusterAgentState)

    builder.add_node(
        "update_world",
        make_update_world_state(
            world_engine=agent_deps.world_engine,
            cell_state_manager=agent_deps.cell_state_manager,
        ),
    )

    builder.add_node(
        "evaluate",
        make_evaluate_node(
            prompt_registry=agent_deps.prompt_registry,
            world_engine=agent_deps.world_engine,
        ),
    )
    builder.add_node(
        "report_risk",
        make_report_risk_node(world_engine=agent_deps.world_engine, store=agent_deps.store),
    )

    builder.add_edge(START, "update_world")
    builder.add_edge("update_world", "evaluate")
    builder.add_conditional_edges("evaluate", route_after_evaluate)
    builder.add_edge("report_risk", END)

    return StreamingRiskGraph(builder.compile())
