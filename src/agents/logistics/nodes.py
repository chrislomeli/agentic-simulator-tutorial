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
STUB_LOGISTICS = False : requires the "supervisor" role in llm_registry.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END
from pydantic import BaseModel, Field

from agents.commons.node_executor import node_executor
from agents.commons.schemas import Direction, SECTOR_ANGLES, SECTOR_VECTORS, Colors
from agents.commons.state_types import StatusValue
from agents.logistics.state import LogisticsAgentState
from world import GenericWorldEngine
from world.cell_state import GenericCell

logger = logging.getLogger(__name__)

# ── Sector Analysis Models ───────────────────────────────────────────────────

StopReason = Literal[
    "barrier:urban",  # 🚨 settlement at risk — fire would impact people/property
    "barrier:water",  # natural firebreak
    "barrier:rock",  # natural firebreak
    "barrier:snow",  # natural firebreak
    "burned",  # already-burned area (no more fuel)
    "max_distance",  # hit the configured trace limit — fuel may continue beyond
    "grid_edge",  # ran off the map — unknown beyond
]


class SectorSummary(BaseModel):
    """Radial sector analysis from a fire hotspot."""

    direction: Direction = Field(
        description="Cardinal direction of this sector"
    )
    burnable_miles: float = Field(
        description="Continuous burnable distance from the hotspot in this direction"
    )
    stop_reason: StopReason = Field(
        description="Why the trace stopped. 'barrier:urban' means the fire would "
        "reach a populated area — escalate. 'barrier:water/rock/snow' = natural "
        "firebreak. 'grid_edge' or 'max_distance' = the spread is not bounded by "
        "the data we have."
    )
    avg_vegetation: float = Field(ge=0, le=1, description="Mean vegetation density")
    avg_fuel_moisture: float = Field(ge=0, le=1, description="Mean fuel moisture")
    avg_slope: float = Field(description="Mean slope in degrees")
    max_fire_intensity: float = Field(ge=0, le=1, description="Maximum fire intensity in sector")
    wind_aligned: bool = Field(description="True if sector direction matches wind direction")
    cells_in_sector: int = Field(description="Number of cells scanned in this sector")


class HotspotSectors(BaseModel):
    """Complete sector analysis for a single fire hotspot."""

    epicenter_row: int
    epicenter_col: int
    risk_score: int = Field(ge=0, le=10)
    confidence: int = Field(ge=0, le=3)
    sectors: list[SectorSummary] = Field(description="8 radial sector summaries")

    def to_context_string(self) -> str:
        """Human-readable summary for LLM prompt."""
        lines = [
            f"Hotspot at ({self.epicenter_row}, {self.epicenter_col}): Risk={self.risk_score}/10, Confidence={self.confidence}/3",
            "Radial sector analysis:",
        ]
        for s in self.sectors:
            align_marker = "🔥 WIND-ALIGNED" if s.wind_aligned else ""
            stop_label = _format_stop_reason(s.stop_reason)
            lines.append(
                f"  {s.direction:2}: {s.burnable_miles:.1f}mi → {stop_label} | "
                f"fuel={s.avg_vegetation:.2f} | moisture={s.avg_fuel_moisture:.2f} | "
                f"slope={s.avg_slope:.1f}° | fire_intensity={s.max_fire_intensity:.2f} "
                f"{align_marker}"
            )
        return "\n".join(lines)


def _format_stop_reason(reason: StopReason) -> str:
    """Render a stop_reason for the LLM context string.

    URBAN is rendered with a fire emoji so the model can't miss it — a
    wind-aligned sector ending in URBAN is an escalation signal, not a
    "fire stops at concrete" signal.
    """
    return {
        "barrier:urban": "🚨 URBAN (settlement at risk)",
        "barrier:water": "WATER (natural firebreak)",
        "barrier:rock": "ROCK (natural firebreak)",
        "barrier:snow": "SNOW (natural firebreak)",
        "burned": "burned-out area",
        "max_distance": "fuel continues beyond trace limit",
        "grid_edge": "grid edge (unknown beyond)",
    }[reason]


# ── Milestone flag ─────────────────────────────────────────────────────────────
#
# True = no LLM, no tool calls, returns stub plan immediately.
# Flip to False once the prompt and LLM are wired in.

STUB_LOGISTICS = False


# ── Node: sector_analysis ─────────────────────────────────────────────────────

def _is_wind_aligned(wind_dir_deg: float, sector_angle: int, tolerance: float = 30.0) -> bool:
    """Check if wind direction aligns with sector direction (within tolerance)."""
    diff = abs(wind_dir_deg - sector_angle)
    diff = min(diff, 360 - diff)  # Handle wrap-around
    return diff <= tolerance


def _trace_sector(
    grid, start_row: int, start_col: int, dr: int, dc: int, max_cells: int, cell_size_ft: float
) -> tuple[float, list, StopReason]:
    """Trace a sector outward, return burnable distance, cells, and stop reason.

    The stop reason is the load-bearing signal for the LLM: a 5-mile sector
    ending in WATER means the fire is bounded; the same distance ending in
    URBAN means a settlement is in the spread path.
    """
    from domains.wildfire.cell_state import FireState, TerrainType

    # Maps non-burnable terrain types to the StopReason literal we report.
    _TERRAIN_STOP: dict[TerrainType, StopReason] = {
        TerrainType.URBAN: "barrier:urban",
        TerrainType.WATER: "barrier:water",
        TerrainType.ROCK: "barrier:rock",
        TerrainType.SNOW: "barrier:snow",
    }

    cells = []
    row, col = start_row + dr, start_col + dc
    stop_reason: StopReason = "max_distance"  # default if loop exhausts cleanly

    for _ in range(max_cells):
        if not (0 <= row < grid.rows and 0 <= col < grid.cols):
            stop_reason = "grid_edge"
            break

        cell = grid.get_cell(row, col)
        cell_state = cell.cell_state

        barrier = _TERRAIN_STOP.get(cell_state.terrain_type)
        if barrier is not None:
            stop_reason = barrier
            break

        if cell_state.fire_state == FireState.BURNED:
            stop_reason = "burned"
            break

        cells.append(cell)
        row += dr
        col += dc

    cell_size_miles = cell_size_ft / 5280.0
    burnable_miles = len(cells) * cell_size_miles

    return burnable_miles, cells, stop_reason


def _analyze_sector(
    sector: Direction,
    cells: list[GenericCell],
    stop_reason: StopReason,
    wind_dir_deg: float,
    cell_size_ft: float,
) -> SectorSummary:
    """Create sector summary from traced cells."""
    if not cells:
        # Sector blocked immediately — the adjacent cell was already a
        # barrier or off-grid. stop_reason still carries the signal.
        return SectorSummary(
            direction=sector,
            burnable_miles=0.0,
            stop_reason=stop_reason,
            avg_vegetation=0.0,
            avg_fuel_moisture=1.0,
            avg_slope=0.0,
            max_fire_intensity=0.0,
            wind_aligned=_is_wind_aligned(wind_dir_deg, SECTOR_ANGLES[sector]),
            cells_in_sector=0,
        )

    n = len(cells)
    avg_veg = sum(c.cell_state.vegetation for c in cells) / n
    avg_moisture = sum(c.cell_state.fuel_moisture for c in cells) / n
    avg_slope = sum(c.cell_state.slope for c in cells) / n
    max_intensity = max((c.cell_state.fire_intensity for c in cells), default=0.0)

    cell_size_miles = cell_size_ft / 5280.0
    burnable_miles = n * cell_size_miles

    return SectorSummary(
        direction=sector,
        burnable_miles=burnable_miles,
        stop_reason=stop_reason,
        avg_vegetation=avg_veg,
        avg_fuel_moisture=avg_moisture,
        avg_slope=avg_slope,
        max_fire_intensity=max_intensity,
        wind_aligned=_is_wind_aligned(wind_dir_deg, SECTOR_ANGLES[sector]),
        cells_in_sector=n,
    )


def make_sector_analysis_node(
    world_engine: GenericWorldEngine, risk_threshold: int = 5, max_sector_miles: float = 20.0
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
    cell_size_ft = getattr(world_engine.physics, "cell_size_ft", 200.0)
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
                    wind_dir = getattr(cell.cell_state, "wind_direction_deg", 0)

                    # Analyze 8 radial sectors
                    sectors = []
                    for sector_name, (dr, dc) in SECTOR_VECTORS.items():
                        _miles, sector_cells, stop_reason = _trace_sector(
                            grid, row, col, dr, dc, max_cells, cell_size_ft
                        )
                        sector_summary = _analyze_sector(
                            sector_name, sector_cells, stop_reason, wind_dir, cell_size_ft
                        )
                        sectors.append(sector_summary)

                    hotspot = HotspotSectors(
                        epicenter_row=row,
                        epicenter_col=col,
                        risk_score=risk_score,
                        confidence=confidence,
                        sectors=sectors,
                    )
                    hotspots.append(hotspot)

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


def make_logistics_agent_node():
    """Factory: binds tools to the LLM at graph-build time.

    Parameters
    ──────────
    tools        : List of bound @tool callables (heatmap, resources, wildfires).
    llm_registry : Registry for looking up the LLM. May be None in stub mode.
    """

    @node_executor("logistics_agent")
    def logistics_agent(state: LogisticsAgentState) -> dict:
        """Call the LLM with tools bound, or return a stub response.

        If this is the first call (no messages yet), the initial human prompt
        is built from the situation summary and cluster findings. On subsequent
        calls (after tool results), the accumulated messages are passed as-is —
        LangGraph's add_messages reducer has already appended the ToolMessages.
        """
        print(f"""{Colors.YELLOW}● NOT CALLING LOGISTICS LLM - Determines equipment and crew availability and issues advisories)  {Colors.RESET}""")
        response = "Logistics LLM STUB"
        logger.info(
            "logistics_agent LLM response: tool_calls=%d",
            len(response.tool_calls) if hasattr(response, "tool_calls") else 0,
        )
        return {"messages": [response], "status": StatusValue.PROCESSING}

    return logistics_agent


# ── Node: extract_plan ────────────────────────────────────────────────────────


def _strip_orphaned_tool_calls(messages: list) -> list:
    """Return a copy of `messages` with orphaned tool_calls stripped.

    The iteration cap can route to extract_plan while the last AIMessage still
    has unanswered tool_calls. OpenAI then rejects the structured-output call
    ("tool_call_ids did not have response messages"). Strip tool_calls from
    any AIMessage whose IDs aren't all matched by a subsequent ToolMessage.
    """
    answered = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None)
    }
    cleaned = []
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            unanswered = [tc for tc in m.tool_calls if tc.get("id") not in answered]
            if unanswered:
                cleaned.append(AIMessage(content=m.content or ""))
                continue
        cleaned.append(m)
    return cleaned


def make_extract_plan_node():
    """Factory that creates the extract_plan terminal node.

    Makes a second structured-output call to extract a LogisticsAssessment
    from the completed ReAct conversation. This is separate from the ReAct
    loop so it can use with_structured_output without conflicting with the
    tool bindings on the logistics_agent node.

    If the 'logistics' LLM role is not registered (e.g. in tests), the
    assessment is skipped and logistics_assessment is left as None.
    """
    @node_executor("extract_plan")
    def extract_logistics_plan(state: LogisticsAgentState) -> dict:
        """Terminal node — lift the LLM's final text and extract structured assessment.

        Two things happen here:
          1. The last message's text content becomes logistics_plan (raw string).
          2. A second structured-output call extracts LogisticsAssessment from
             the full conversation — observations, data_gaps, assessment,
             advisory_sent, advisory_rationale.

        data_gaps is the branching signal: empty = agent had what it needed;
        non-empty = upstream should consider widening search or escalating.
        """
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

# Hard cap on ReAct iterations. Each round = one AI message with tool_calls
# followed by one or more ToolMessages. A normal run needs at most 2 rounds
# (resources call + advisory call). 4 allows for multiple hotspots while
# stopping runaway loops that accumulated 82K tokens in one tick.
MAX_LOGISTICS_ITERATIONS = 4


def route_after_logistics_agent(state: LogisticsAgentState) -> str:
    """Conditional edge after logistics_agent.

    Three outcomes:
      - status == ERROR        → END (node_executor already set this)
      - last message has tool_calls → "tools" (continue the ReAct loop)
      - last message has no tool calls → "extract_plan" (LLM is done)

    A hard cap of MAX_LOGISTICS_ITERATIONS tool-call rounds is enforced.
    If the cap is hit, we force → "extract_plan" regardless of tool_calls
    so runaway loops cannot accumulate unbounded tokens.
    """
    if state.status == StatusValue.ERROR:
        return END

    return "extract_plan"
