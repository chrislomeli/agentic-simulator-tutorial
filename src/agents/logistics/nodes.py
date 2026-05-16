"""
world-simulator.agents.logistics.nodes

Node functions for the logistics agent ReAct loop.

Loop shape
──────────
    START → logistics_agent ──(tool calls?)──► tools → logistics_agent (repeat)
                             ──(no tool calls)──► extract_plan → END

  logistics_agent : AI boundary. Stub mode returns a placeholder AIMessage
                    with no tool calls so the loop exits immediately.
                    LLM mode calls the model with all three tools bound.
  extract_plan    : Terminal node — copies the LLM's final message content
                    into state.logistics_plan and marks COMPLETED.
  route_after_logistics_agent : Reads the last message; routes to "tools"
                    if tool_calls present, otherwise to "extract_plan".

Milestone flag
──────────────
STUB_LOGISTICS = True  : runs without an LLM. Safe for graph topology tests.
STUB_LOGISTICS = False : requires the "logistics" role (Phase 1 ReAct loop)
                         and the "logistics_extract" role (Phase 2 structured
                         output) in llm_registry.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END

from agents.commons.node_executor import node_executor
from agents.commons.schemas import Colors
from agents.commons.state_types import StatusValue
from agents.logistics.state import LogisticsAgentState, LogisticsAssessment
from llm.llm_registry import LLMRegistry
from prompts import PromptRegistry
from world import GenericWorldEngine, TerrainType, FireState, Direction, SECTOR_VECTORS, HotspotSectors, trace_sector, \
    analyze_sector
from world.cell_state import GenericCell

logger = logging.getLogger(__name__)


# ── Milestone flag ─────────────────────────────────────────────────────────────
#
# True = no LLM, no tool calls, returns stub plan immediately.
# Flip to False once the prompt and LLM are wired in.

STUB_LOGISTICS = False


def make_sector_analysis_node(
    world_engine: GenericWorldEngine,
    risk_threshold: int = 5,
    max_sector_miles: float = 20.0
):
    """Factory: creates node that analyzes radial sectors around fire hotspots.
    
    Scans the grid for cells with risk_score >= threshold and builds
    8-sector radial summaries for each hotspot. This compresses 2000+ cells
    into ~24 sector summaries (3 hotspots × 8 sectors).
    
    Parameters
    ──────────
    world_engine : The simulation engine containing the grid
    risk_threshold : Minimum risk_score to qualify as a hotspot
    max_sector_miles : Maximum distance to trace in each sector
    
    Returns
    ───────
    Node function that returns {"sector_analysis": [...], "status": PROCESSING}
    """
    grid = world_engine.grid
    
    # Infer cell size from physics config (default to 200ft)
    cell_size_ft = getattr(world_engine.physics, 'cell_size_ft', 200.0)
    max_cells = int((max_sector_miles * 5280) / cell_size_ft)
    
    @node_executor("sector_analysis")
    def sector_analysis(state: LogisticsAgentState) -> dict:
        """Analyze radial sectors around high-risk hotspots."""
        from agents.commons.schemas import CellRiskAssessment
        
        hotspots = []
        
        # Scan grid for hotspots
        for row in range(grid.rows):
            for col in range(grid.cols):
                cell = grid.get_cell(row, col)
                
                # Check if cell has risk assessment
                assessment = cell.risk_assessment
                if not isinstance(assessment, CellRiskAssessment):
                    continue
                
                risk_score = assessment.risk_score
                confidence = assessment.confidence
                
                if risk_score >= risk_threshold:
                    # Get wind direction from cell state for alignment check
                    wind_dir = getattr(cell.cell_state, 'wind_direction_deg', 0)
                    
                    # Analyze 8 radial sectors
                    sectors = []
                    for sector_name, (dr, dc) in SECTOR_VECTORS.items():
                        _miles, sector_cells, stop_reason = trace_sector(
                            grid, row, col, dr, dc, max_cells, cell_size_ft
                        )
                        sector_summary = analyze_sector(
                            sector_name, sector_cells, stop_reason, wind_dir, cell_size_ft
                        )
                        sectors.append(sector_summary)
                    
                    hotspot = HotspotSectors(
                        epicenter_row=row,
                        epicenter_col=col,
                        risk_score=risk_score,
                        confidence=confidence,
                        sectors=sectors
                    )
                    hotspots.append(hotspot)
                    
                    logger.info(
                        "Hotspot at (%d, %d): Risk=%d, 8 sectors analyzed, "
                        "max_burnable=%.1f miles",
                        row, col, risk_score,
                        max(s.burnable_miles for s in sectors)
                    )
        
        # Build context string for LLM
        if hotspots:
            context_parts = [
                f"Found {len(hotspots)} fire hotspot(s) with risk ≥ {risk_threshold}:",
                ""
            ]
            for h in hotspots:
                context_parts.append(h.to_context_string())
                context_parts.append("")
            context = "\n".join(context_parts)
        else:
            context = f"No fire hotspots found with risk ≥ {risk_threshold}."
        
        logger.info("Sector analysis complete: %d hotspots, %d total sectors", 
                   len(hotspots), len(hotspots) * 8)
        
        return {
            "sector_analysis": [h.model_dump() for h in hotspots],
            "situation_summary": context,
            "status": StatusValue.PROCESSING
        }
    
    return sector_analysis


# ── Node: logistics_agent ─────────────────────────────────────────────────────


def make_logistics_agent_node(tools: list, prompt_registry: PromptRegistry, llm_registry: LLMRegistry | None):
    """Factory: binds tools to the LLM for the ReAct loop (Phase 1).

    Phase 1 is tool-calling ONLY. We deliberately do NOT chain
    ``.with_structured_output()`` here. In LangChain that helper is implemented
    as a *forced single-tool call*: it re-binds the tool list to just the
    schema, forces ``tool_choice`` to it, and returns a parsed Pydantic object
    instead of an AIMessage. Chaining it after ``.bind_tools(tools)`` therefore
    silently deletes the real tools and makes the ReAct router unreachable.

    Structured output is done separately in the ``extract_plan`` node (Phase 2),
    as its own LLM call over the finished conversation — see make_extract_plan_node.

    Parameters
    ──────────
    tools        : List of bound @tool callables (resources, wildfires, advisory).
    llm_registry : Registry for looking up the LLM. May be None in stub mode.
    """
    llm_with_tools = None
    if not STUB_LOGISTICS and llm_registry is not None:
        try:
            llm = llm_registry.get("logistics")
            llm_with_tools = llm.bind_tools(tools)  # ReAct tool calling — no structured output
        except KeyError:
            logger.warning("No 'logistics' LLM registered — logistics agent will use stub mode.")

    @node_executor("logistics_agent")
    def logistics_agent(state: LogisticsAgentState) -> dict:
        """Call the LLM with tools bound, or return a stub response.

        If this is the first call (no messages yet), the initial human prompt
        is built from the situation summary and cluster findings. On subsequent
        calls (after tool results), the accumulated messages are passed as-is —
        LangGraph's add_messages reducer has already appended the ToolMessages.

        Always returns an AIMessage. The router inspects it: tool_calls present
        → "tools" (keep looping); absent → "extract_plan" (Phase 2).
        """

        if STUB_LOGISTICS or llm_with_tools is None:
            print(f"""\n{Colors.YELLOW}● STUB the LLM - no call to logistics {Colors.RESET}""")
            stub_content = "[STUB] Logistics plan — LLM not active in this milestone."
            stub = AIMessage(content=stub_content)
            return {
                "messages": [stub],
                "logistics_plan": stub_content,
                "status": StatusValue.COMPLETED,
            }

        # Call the LLM
        system_prompt = prompt_registry.render(
            "logistics",
            {"state": state},
        )

        messages = list(state.messages)
        if not messages:
            content = (
                f"Situation summary:\n\n{state.situation_summary}\n\n"
                "Using the tools available, gather resource information for each "
                "hotspot and decide whether a ResourceAdvisory is warranted."
            )
            messages = [HumanMessage(content=content)]

        # Prepend system prompt on every call — it carries the instructions and
        # sector analysis format description the LLM needs on each ReAct iteration.
        messages = [SystemMessage(system_prompt)] + messages

        response = llm_with_tools.invoke(messages)

        if getattr(response, "tool_calls", None):
            logger.info(
                "logistics_agent: tool_calls=%d, continuing ReAct", len(response.tool_calls)
            )
        else:
            logger.info(
                "logistics_agent: no tool_calls — ReAct loop complete, routing to extract_plan"
            )
        return {"messages": [response], "status": StatusValue.PROCESSING}

    return logistics_agent


# ── Router ────────────────────────────────────────────────────────────────────

# Hard cap on ReAct iterations. Each round = one AI message with tool_calls
# followed by one or more ToolMessages. A normal run needs at most 2 rounds
# (resources call + advisory call). 4 allows for multiple hotspots while
# stopping runaway loops that accumulated 82K tokens in one tick.
MAX_LOGISTICS_ITERATIONS = 4


def route_after_logistics_agent(state: LogisticsAgentState) -> str:
    """Conditional edge after logistics_agent (Phase 1 ReAct loop).

    Outcomes:
      - status == ERROR             → END (node_executor already set this)
      - status == COMPLETED         → END (stub mode short-circuit)
      - no messages                 → END (nothing happened to extract)
      - last message has tool_calls → "tools" (continue the ReAct loop),
                                       unless the iteration cap is hit, in
                                       which case → "extract_plan" so we
                                       still produce a structured record of
                                       the (truncated) run
      - last message is plain text  → "extract_plan" (loop done — Phase 2
                                       converts the transcript into a
                                       LogisticsAssessment)
    """
    if state.status == StatusValue.ERROR:
        return END

    if state.status == StatusValue.COMPLETED:
        return END

    if not state.messages:
        return END

    last = state.messages[-1]
    if getattr(last, "tool_calls", None):
        tool_call_rounds = sum(
            1 for m in state.messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
        )
        if tool_call_rounds >= MAX_LOGISTICS_ITERATIONS:
            logger.warning(
                "logistics_agent: max iterations (%d) reached — forcing extract_plan",
                MAX_LOGISTICS_ITERATIONS,
            )
            return "extract_plan"
        return "tools"

    return "extract_plan"


# ── Node: extract_plan (Phase 2 — structured output) ──────────────────────────


def _advisory_was_sent(messages: list[BaseMessage]) -> bool:
    """True if a send_advisory tool call appears anywhere in the transcript.

    This is the factual signal for whether the agent actuated — read from the
    conversation itself, not from whatever the model later self-reports.
    """
    for m in messages:
        for call in getattr(m, "tool_calls", None) or []:
            if call.get("name") == "send_advisory":
                return True
    return False


def _balance_dangling_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Close any unanswered tool_calls with a synthetic ToolMessage.

    Phase 2 re-issues the whole conversation to the provider, which rejects an
    AIMessage whose tool_calls have no matching ToolMessage. That only happens
    on the max-iteration path (loop cut before the ToolNode ran); we stub the
    open calls so the structured-output call still succeeds.
    """
    if not messages:
        return messages
    open_calls = getattr(messages[-1], "tool_calls", None) or []
    if not open_calls:
        return messages
    closers = [
        ToolMessage(
            content="Tool execution skipped: logistics ReAct iteration cap reached.",
            tool_call_id=call["id"],
        )
        for call in open_calls
    ]
    return list(messages) + closers


def _assessment_to_plan(assessment: LogisticsAssessment, advisory_sent: bool) -> str:
    """Render a human-readable plan string for the supervisor (which prints it)."""
    decision = "ADVISORY SENT" if advisory_sent else "NO ADVISORY SENT"
    lines = [
        f"Logistics decision: {decision}",
        "",
        "Assessment:",
        assessment.assessment,
        "",
        f"Reason: {assessment.reason_for_no_advisory}",
    ]
    if assessment.data_gaps:
        lines += ["", "Data gaps:"] + [f"  - {g}" for g in assessment.data_gaps]
    return "\n".join(lines)


def make_extract_plan_node(prompt_registry: PromptRegistry, llm_registry: LLMRegistry | None):
    """Factory: Phase 2 terminal node — structured output over the finished loop.

    Reads the accumulated ReAct transcript and makes a SEPARATE LLM call with
    ``.with_structured_output(LogisticsAssessment)``. This is the only safe
    place to combine "the model decided/acted" with "force a structured
    rationale": the loop already ran with real tools, so structured output can
    now consume the tool channel without disabling anything. The rationale is
    faithful because the prior reasoning *is the input* to this call.
    """
    structured_llm = None
    if not STUB_LOGISTICS and llm_registry is not None:
        try:
            llm = llm_registry.get("logistics_extract")
            structured_llm = llm.with_structured_output(LogisticsAssessment)
        except KeyError:
            logger.warning("No 'logistics_extract' LLM registered — extract_plan will pass through.")

    @node_executor("extract_plan")
    def extract_plan(state: LogisticsAgentState) -> dict:
        """Convert the ReAct transcript into a structured LogisticsAssessment."""
        advisory_sent = _advisory_was_sent(state.messages)

        if structured_llm is None:
            # Defensive: stub mode short-circuits at the router (COMPLETED →
            # END), so this is only reached if the loop ran without an LLM.
            last_text = next(
                (
                    m.content
                    for m in reversed(state.messages)
                    if isinstance(m, AIMessage) and m.content
                ),
                "No logistics plan produced.",
            )
            return {"logistics_plan": last_text, "status": StatusValue.COMPLETED}

        system_prompt = prompt_registry.render("logistics_extract", {})
        convo = _balance_dangling_tool_calls(state.messages)

        assessment: LogisticsAssessment = structured_llm.invoke(
            [SystemMessage(system_prompt), *convo]
        )

        plan_text = _assessment_to_plan(assessment, advisory_sent)
        print(f"""{Colors.TEAL}{assessment.model_dump_json(indent=2)}{Colors.RESET}""")
        logger.info(
            "extract_plan: advisory_sent=%s, observations=%d, data_gaps=%d",
            advisory_sent,
            len(assessment.observations),
            len(assessment.data_gaps),
        )

        return {
            "logistics_assessment": assessment,
            "logistics_plan": plan_text,
            "messages": [AIMessage(content=plan_text)],
            "status": StatusValue.COMPLETED,
        }

    return extract_plan
