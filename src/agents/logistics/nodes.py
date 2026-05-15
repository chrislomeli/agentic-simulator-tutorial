"""
world-simulator.agents.logistics.nodes

Node functions for the logistics agent ReAct loop.

Loop shape
──────────
    START → sector_analysis → logistics_agent ──(tool calls?)──► tools → logistics_agent (repeat)
                                              ──(no tool calls)──► extract_plan → END

  sector_analysis : Compresses the world grid into per-hotspot 8-direction
                    summaries. Delegated to `world.sector_analysis`.
  logistics_agent : AI boundary. Stub mode returns a placeholder AIMessage
                    with no tool calls so the loop exits immediately.
                    LLM mode calls the model with tools bound.
  extract_plan    : Terminal node — copies the LLM's final message content
                    into state.logistics_plan and marks COMPLETED.
  route_after_logistics_agent : Reads the last message; routes to "tools"
                    if tool_calls present, otherwise to "extract_plan".

Milestone flag
──────────────
STUB_LOGISTICS = True  : runs without an LLM. Safe for graph topology tests.
STUB_LOGISTICS = False : requires the "logistics" role in llm_registry.
"""

from __future__ import annotations

import logging

from agents.commons.node_executor import node_executor
from agents.commons.schemas import CellRiskAssessment, Colors
from agents.commons.state_types import StatusValue
from agents.logistics.state import LogisticsAgentState
from prompts import PromptRegistry
from world import (
    SECTOR_VECTORS,
    GenericWorldEngine,
    HotspotSectors,
    analyze_sector,
    trace_sector,
)

logger = logging.getLogger(__name__)


# ── Milestone flag ────────────────────────────────────────────────────────────
#
# True = no LLM, no tool calls, returns stub plan immediately.
# Flip to False once the prompt and LLM are wired in.

STUB_LOGISTICS = False


# Hard cap on ReAct iterations. Each round = one AI message with tool_calls
# followed by one or more ToolMessages. A normal run needs at most 2 rounds
# (resources call + advisory call). 4 allows for multiple hotspots while
# stopping runaway loops that accumulated 82K tokens in one tick.
MAX_LOGISTICS_ITERATIONS = 4


# ── Node: sector_analysis ─────────────────────────────────────────────────────


def make_sector_analysis_node(
    world_engine: GenericWorldEngine,
    risk_threshold: int = 5,
    max_sector_miles: float = 20.0,
):
    """Factory: creates node that analyzes radial sectors around fire hotspots.

    Scans the grid for cells with risk_score >= threshold and builds
    8-sector radial summaries for each hotspot. This compresses 2000+ cells
    into ~24 sector summaries (3 hotspots × 8 sectors).

    The actual sector geometry/traversal lives in `world.sector_analysis`;
    this node is just the glue: find hotspots, call the service, package the
    output for state.

    Parameters
    ──────────
    world_engine     : The simulation engine containing the grid
    risk_threshold   : Minimum risk_score to qualify as a hotspot
    max_sector_miles : Maximum distance to trace in each sector
    """
    grid = world_engine.grid

    # Infer cell size from physics config (default to 200ft)
    cell_size_ft = getattr(world_engine.physics, "cell_size_ft", 200.0)
    max_cells = int((max_sector_miles * 5280) / cell_size_ft)

    @node_executor("sector_analysis")
    def sector_analysis(state: LogisticsAgentState) -> dict:
        """Analyze radial sectors around high-risk hotspots."""
        hotspots: list[HotspotSectors] = []

        for row in range(grid.rows):
            for col in range(grid.cols):
                cell = grid.get_cell(row, col)

                assessment = cell.risk_assessment
                if not isinstance(assessment, CellRiskAssessment):
                    continue

                risk_score = assessment.risk_score
                confidence = assessment.confidence

                if risk_score < risk_threshold:
                    continue

                wind_dir = getattr(cell.cell_state, "wind_direction_deg", 0)

                sectors = []
                for sector_name, (dr, dc) in SECTOR_VECTORS.items():
                    _miles, sector_cells, stop_reason = trace_sector(
                        grid, row, col, dr, dc, max_cells, cell_size_ft
                    )
                    sectors.append(
                        analyze_sector(
                            sector_name, sector_cells, stop_reason, wind_dir, cell_size_ft
                        )
                    )

                hotspots.append(
                    HotspotSectors(
                        epicenter_row=row,
                        epicenter_col=col,
                        risk_score=risk_score,
                        confidence=confidence,
                        sectors=sectors,
                    )
                )

                logger.info(
                    "Hotspot at (%d, %d): Risk=%d, 8 sectors analyzed, max_burnable=%.1f miles",
                    row,
                    col,
                    risk_score,
                    max(s.burnable_miles for s in sectors),
                )

        # Build context string for LLM
        if hotspots:
            context_parts = [
                f"Found {len(hotspots)} fire hotspot(s) with risk ≥ {risk_threshold}:",
                "",
            ]
            for h in hotspots:
                context_parts.append(h.to_context_string())
                context_parts.append("")
            context = "\n".join(context_parts)
        else:
            context = f"No fire hotspots found with risk ≥ {risk_threshold}."

        logger.info(
            "Sector analysis complete: %d hotspots, %d total sectors",
            len(hotspots),
            len(hotspots) * 8,
        )

        return {
            "sector_analysis": [h.model_dump() for h in hotspots],
            "situation_summary": context,
            "status": StatusValue.PROCESSING,
        }

    return sector_analysis


# ── Node: logistics_agent ─────────────────────────────────────────────────────


def make_logistics_agent_node(prompt_registry: PromptRegistry):
    """Factory: binds tools to the LLM at graph-build time."""

    @node_executor("logistics_agent")
    def logistics_agent(state: LogisticsAgentState) -> dict:
        """Call the LLM with tools bound, or return a stub response.

        If this is the first call (no messages yet), the initial human prompt
        is built from the situation summary and cluster findings. On subsequent
        calls (after tool results), the accumulated messages are passed as-is —
        LangGraph's add_messages reducer has already appended the ToolMessages.
        """
        print(
            f"{Colors.YELLOW}● NOT CALLING LOGISTICS LLM - "
            f"Determines equipment and crew availability and issues advisories){Colors.RESET}"
        )

        system_prompt = prompt_registry.render("logistics", {"state": state})  # noqa: F841

        response = "Logistics LLM STUB"
        logger.info(
            "logistics_agent LLM response: tool_calls=%d",
            len(response.tool_calls) if hasattr(response, "tool_calls") else 0,
        )
        return {"messages": [response], "status": StatusValue.PROCESSING}

    return logistics_agent


# ── Node: extract_plan ────────────────────────────────────────────────────────


def make_extract_plan_node():
    """Factory that creates the extract_plan terminal node.

    Makes a second structured-output call to extract a LogisticsAssessment
    from the completed ReAct conversation. This is separate from the ReAct
    loop so it can use with_structured_output without conflicting with the
    tool bindings on the logistics_agent node.
    """

    @node_executor("extract_plan")
    def extract_logistics_plan(state: LogisticsAgentState) -> dict:
        """Terminal node — lift the LLM's final text and extract structured assessment."""
        last = state.messages[-1] if state.messages else None
        plan = last.content if last else "[No plan produced]"
        logger.info("Logistics plan extracted (%d chars)", len(plan))

        assessment = "If this is to end in fire, we should all burn together"
        return {
            "logistics_plan": plan,
            "logistics_assessment": assessment,
            "status": StatusValue.COMPLETED,
        }

    return extract_logistics_plan


# ── Router ────────────────────────────────────────────────────────────────────


def route_after_logistics_agent(state: LogisticsAgentState) -> str:
    """Conditional edge after logistics_agent.

    Three outcomes:
      - status == ERROR              → END (node_executor already set this)
      - last message has tool_calls  → "tools" (continue the ReAct loop)
      - last message has no tool_calls → "extract_plan" (LLM is done)

    A hard cap of MAX_LOGISTICS_ITERATIONS tool-call rounds is enforced.
    If the cap is hit, we force → "extract_plan" regardless of tool_calls
    so runaway loops cannot accumulate unbounded tokens.
    """
    from langgraph.graph import END

    if state.status == StatusValue.ERROR:
        return END

    return "extract_plan"
