"""
world-simulator.agents.logistics.graph

Logistics agent LangGraph — ReAct tool-calling loop.

Topology
────────
    START
      → logistics_agent           (LLM with tools bound)
        → tools                   (ToolNode — executes tool calls)
        → logistics_agent         (loop until no more tool calls)
      → extract_plan → END        (lift final LLM text as the plan)

The ReAct loop
──────────────
1. sector_analysis scans the world grid for hotspots (cells with
   cell.risk_assessment.risk_score >= threshold), produces an 8-sector
   radial summary per hotspot, and writes it into state.situation_summary.
2. logistics_agent calls the LLM with that summary plus data_store tools.
3. If the LLM returns tool calls, ToolNode executes them and appends
   ToolMessages to state.messages. Then logistics_agent is called again.
4. When the LLM returns a plain text response (no tool calls), the router
   sends control to extract_plan, which writes state.logistics_plan.

Construction
────────────
``build_logistics_agent_graph`` is the only public entry point. It receives
AgentDependencies (carries the world_engine, DataStore, and LLMRegistry).

Tools are built only when the required dependency is available:
  - get_wildfire_activity: requires data_store != None
  - get_resources_within : requires data_store != None

The advisory is not a tool. extract_plan produces a LogisticsAssessment via
structured output; if assessment.advisory is not None, extract_plan dispatches
it to the DB directly. Missing dependencies → fewer tools, not a crash.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agents.commons.agent_dependencies import AgentDependencies
from agents.logistics.nodes import (
    make_extract_plan_node,
    make_logistics_agent_node,
    make_sector_analysis_node,
    route_after_logistics_agent,
)
from agents.logistics.state import LogisticsAgentState, LogisticsGraph
from tools.resources import make_get_resources_within
from tools.wildfires import make_get_wildfire_activity

logger = logging.getLogger(__name__)


def build_logistics_agent_graph(*, agent_deps: AgentDependencies) -> LogisticsGraph:
    """Compile and return the logistics agent graph.

    Parameters
    ──────────
    agent_deps : AgentDependencies
        DI container. Relevant fields:
          - world_engine  : grid that sector_analysis scans for hotspots
          - data_store    : DataStore facade (resources + wildfire + advisory tools)
          - llm_registry  : LLM lookup by role (for logistics_agent node)
    """
    tools = _build_tools(agent_deps)

    builder = StateGraph(LogisticsAgentState)

    builder.add_node(
        "sector_analysis",
        make_sector_analysis_node(
            world_engine=agent_deps.world_engine,
            risk_threshold=5,
            max_sector_miles=20.0
        )
    )
    builder.add_node("logistics_agent",
                     make_logistics_agent_node(tools, agent_deps.prompt_registry, agent_deps.llm_registry))
    builder.add_node("tools", ToolNode(tools))
    advisory_repo = agent_deps.data_store.advisories if agent_deps.data_store is not None else None
    builder.add_node("extract_plan",
                     make_extract_plan_node(agent_deps.prompt_registry, agent_deps.llm_registry, advisory_repo))

    builder.add_edge(START, "sector_analysis")
    builder.add_edge("sector_analysis", "logistics_agent")
    builder.add_conditional_edges(
        "logistics_agent",
        route_after_logistics_agent,
        {"tools": "tools", "extract_plan": "extract_plan", END: END},
    )
    builder.add_edge("tools", "logistics_agent")
    builder.add_edge("extract_plan", END)

    return LogisticsGraph(builder.compile())


def _build_tools(agent_deps: AgentDependencies) -> list:
    """Build the tool list from available dependencies."""
    tools = []

    if agent_deps.data_store is not None:
        tools.append(make_get_wildfire_activity(agent_deps.data_store.wildfires))
        tools.append(make_get_resources_within(agent_deps.data_store.terrain, agent_deps.data_store.resources))
    else:
        logger.warning("pg_gateway not available — resource and wildfire tools skipped")

    return tools
