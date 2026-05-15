"""
world-simulator.agents.cluster.nodes

Node functions for the cluster agent's risk assessment pipeline.

Pipeline shape
──────────────
    START → update_world → evaluate → route_after_evaluate → report_risk → END

    update_world : Deterministic. Reads state.readings (CellReadings),
                   writes metric values onto the world grid (session
                   ground truth), and produces cell snapshot dicts in
                   state.updated_cells — each with an optional `trends`
                   block describing recent direction per metric.
    evaluate     : AI boundary. Stub mode returns deterministic placeholder
                   risk scores. LLM mode calls the model with structured
                   output. Both modes write CellRiskAssessment onto each
                   evaluated cell so sector_analysis can find hotspots.
    report_risk  : Terminal node. Persists CollatedRecordRisk records to
                   the optional store and marks the pipeline COMPLETED.

Design principles
─────────────────
  - The AI boundary is explicit: ``evaluate`` is the only node that will
    call an LLM. If the agent produces bad output, debug the prompt and
    tools — not the pipeline structure.
  - Nodes return PARTIAL state updates. LangGraph merges them via reducers.
  - Nodes that need dependencies (prompt registry, LLM, store) are exposed
    as ``make_*`` factories so the graph builder can thread them in at
    compile time — no side effects at import time.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import NamedTuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from agents.cluster.state import ClusterAgentState
from agents.commons.node_executor import node_executor
from agents.commons.routing import route_base
from agents.commons.schemas import (
    CellReadings,
    CellRiskAssessment,
    CollatedRecordRisk,
    Colors,
    GridPosition,
)
from agents.commons.state_types import StatusValue
from domains.wildfire import FireCellState
from llm.llm_registry import LLMRegistry
from prompts import PromptRegistry
from world import GenericCell, GenericWorldEngine
from world.cell_state_manager import CellStateManager

logger = logging.getLogger(__name__)

# ── Milestone flag ────────────────────────────────────────────────────────────
#
# True for the dashboard milestone: evaluate returns stub CollatedRecordRisk
# records without calling an LLM. Flip to False in the next milestone once
# the prompt template and LLM tooling are ready.
STUB_RISK_SCORE = False

# ── Heuristic gate ────────────────────────────────────────────────────────────
#
# Cells whose heuristic_score is strictly below this threshold are skipped by
# the evaluate LLM call and assigned risk_score=0 with high confidence.
# The heuristic is 0–10 based on four binary factors (temp, humidity,
# vegetation, wind). A threshold of 1 skips only cells where ALL four factors
# are absent — the most conservative gate, only bypassing obviously safe cells.
HEURISTIC_EVALUATE_THRESHOLD = 3


class ReadingKey(NamedTuple):
    row: int
    col: int
    rtype: str  # 'type' is reserved, use rtype or metric_type
    value: float


def generic_to_fire():
    pass


# ── Node: update world ────────────────────────────────────────────────────────
def make_update_world_state(
    world_engine: GenericWorldEngine,
    cell_state_manager: CellStateManager | None = None,
):
    """Factory for the update_world node.

    For each cell named in ``state.readings``:
      1. Write the metric values onto the world-grid cell (ground truth).
      2. Snapshot the cell to a dict.
      3. Attach a ``trends`` block sourced from the manager's per-cell
         metric history (categorical: rising_fast/rising/stable/falling/
         falling_fast). Trends are omitted when no manager is wired or
         the cell has too little history.

    The list of cell dicts is what the evaluate node hands to the LLM.
    """

    @node_executor("update_world")
    def update_world(state: ClusterAgentState):
        readings: list[CellReadings] = state.readings
        grid = world_engine.grid

        unique_readings = {
            ReadingKey(m.position.row, m.position.col, m.type, m.value)
            for cell in readings
            for m in cell.metrics
        }

        total_metrics = sum(len(cell.metrics) for cell in readings)
        logger.debug(
            "Deduplicated %d raw metrics into %d unique readings",
            total_metrics,
            len(unique_readings),
        )

        affected_cells: dict = {}
        for reading in unique_readings:
            r: GenericCell = grid.get_cell(reading.row, reading.col)
            key = (r.row, r.col)
            if key not in affected_cells:
                affected_cells[key] = r.to_dict()

            match reading.rtype:
                case "humidity":
                    r.cell_state.humidity_pct = reading.value
                case "temperature":
                    r.cell_state.temperature_c = reading.value
                case "wind_speed":
                    r.cell_state.wind_speed_mps = reading.value
                case "wind_direction":
                    r.cell_state.wind_direction_deg = reading.value
                case _:
                    logger.warning("Unknown metric type: %s", reading.rtype)
                    continue

            # Recompute after each metric write so the final value on the cell
            # reflects all readings processed this tick, not just the first one.
            f: FireCellState = r.cell_state
            factors = [
                f.temperature_c > 32,
                f.humidity_pct < 15,
                f.vegetation < 0.50,
                f.wind_speed_mps > 20,
            ]
            r.heuristic = round(sum(factors) / len(factors) * 10)

        # Attach heuristic and trends after the loop — all metrics are written
        # by this point so r.heuristic is the final value for this tick.
        for (row, col), cell_dict in affected_cells.items():
            cell = grid.get_cell(row, col)
            cell_dict["heuristic_score"] = getattr(cell, "heuristic", 0)
            if cell_state_manager is not None:
                trends = cell_state_manager.get_trend(row, col)
                if trends:
                    cell_dict["trends"] = trends

        return {
            "updated_cells": list(affected_cells.values()),
            "status": StatusValue.PROCESSING,
        }

    return update_world


# ── Node: evaluate ────────────────────────────────────────────────────────────


def make_evaluate_node(
    prompt_registry: PromptRegistry,
    llm_registry: LLMRegistry,
    world_engine: GenericWorldEngine,
):
    """Factory that creates the evaluate node.

    This is the AI boundary. Everything before this node is deterministic.
    The evaluate node receives cell snapshot dicts from ``update_world`` and
    produces one CollatedRecordRisk per cell. Each risk is also written back
    onto the matching GenericCell.risk_assessment so the logistics agent's
    sector_analysis can find hotspots by scanning the grid.

    Parameters
    ──────────
    prompt_registry : PromptRegistry
        For rendering the system prompt template when LLM mode is active.
    llm_registry : LLMRegistry
        For looking up the LLM to use (role: "classifier") when LLM mode
        is active. Unused in stub mode.
    world_engine : GenericWorldEngine
        The session ground truth. Risk assessments are written onto cells
        in ``world_engine.grid``.
    """

    @node_executor("evaluate")
    async def evaluate(state: ClusterAgentState, max_concurrency: int = 3) -> dict:
        """Evaluate fire risk for every cell snapshot in this cluster.

        Stub mode (STUB_RISK_SCORE=True):
          Returns deterministic placeholder scores — one per cell.
          No LLM is called.

        LLM mode (STUB_RISK_SCORE=False):
          Renders the system prompt, serialises the cell snapshot dicts as
          the human message, and calls the LLM with structured output.

        State reads
        ───────────
          - state.updated_cells : cell snapshot dicts from update_world
          - state.cluster_id   : for logging and LLM context

        State writes
        ────────────
          - risk_assessments : list[CollatedRecordRisk], one per cell
          - status           : PROCESSING

        Side effects
        ────────────
          Writes a CellRiskAssessment onto cell.risk_assessment for each
          evaluated cell on the world grid.

        """
        cells = state.updated_cells
        cluster_id: str = state.cluster_id

        if not cells:
            logger.warning("ClusterAgent[%s] evaluate: no cells to evaluate", cluster_id)
            return {
                "risk_assessments": [],
                "status": StatusValue.PROCESSING,
            }

        # Split on heuristic score — only call the LLM for cells that have at
        # least one risk factor present. Cells below the threshold are assigned
        # risk_score=0 with high confidence: the heuristic says nothing is there.
        evaluate_cells = [
            c for c in cells if c.get("heuristic_score", 0) >= HEURISTIC_EVALUATE_THRESHOLD
        ]
        skip_cells = [
            c for c in cells if c.get("heuristic_score", 0) < HEURISTIC_EVALUATE_THRESHOLD
        ]

        if skip_cells:
            logger.info(
                "ClusterAgent[%s] heuristic gate: skipping %d/%d cells (score < %d)",
                cluster_id,
                len(skip_cells),
                len(cells),
                HEURISTIC_EVALUATE_THRESHOLD,
            )

        skipped_risks = [
            CollatedRecordRisk(
                position=GridPosition(row=c["row"], col=c["col"]),
                risk_score=0,
                confidence=3,
                confidence_rationale="Heuristic gate: no risk factors present.",
                contributing_factors=["heuristic_gate"],
            )
            for c in skip_cells
        ]
        if not evaluate_cells:
            print(
                f"""\n{Colors.YELLOW}● not CALLING LLM - no potential hotspots found {Colors.RESET}"""
            )

        if STUB_RISK_SCORE:
            print(f"""\n{Colors.BLUE}● CALLING LLM STUB {Colors.RESET}""")
            llm_risks = [
                CollatedRecordRisk(
                    position=GridPosition(row=cell["row"], col=cell["col"]),
                    risk_score=10,
                    confidence=3,
                    confidence_rationale="Stub score — LLM not active in this milestone.",
                    contributing_factors=["stub"],
                )
                for cell in evaluate_cells
            ]
        else:
            llm = llm_registry.get("classifier")
            system_prompt = prompt_registry.render(
                "evaluate",
                {"cluster_id": cluster_id},
            )

            sem = asyncio.Semaphore(max_concurrency)

            async def assess_risk(cell: dict) -> CollatedRecordRisk | BaseException:
                print(f"""\n{Colors.BLUE}● CALLING LLM  {Colors.RESET}""")
                human_prompt = json.dumps(cell, default=str, indent=2)
                async with sem:
                    return await llm.with_structured_output(CollatedRecordRisk).ainvoke(
                        [
                            SystemMessage(system_prompt),
                            HumanMessage(human_prompt),
                        ]
                    )

            results = await asyncio.gather(
                *(assess_risk(c) for c in evaluate_cells),
                return_exceptions=True,
            )
            llm_risks = []
            for cell, result in zip(evaluate_cells, results):
                if isinstance(result, BaseException):
                    logger.error(
                        "ClusterAgent[%s] assess_risk failed for cell (%s,%s): %s",
                        cluster_id,
                        cell["row"],
                        cell["col"],
                        result,
                    )
                else:
                    print(f"""\n{Colors.TEAL}{result.model_dump_json(indent=2)}{Colors.RESET}""")
                    llm_risks.append(result)

        risks = skipped_risks + llm_risks

        # Write risk back onto the cell so sector_analysis can find hotspots.
        grid = world_engine.grid
        for risk in risks:
            cell = grid.get_cell(risk.position.row, risk.position.col)
            cell.risk_assessment = CellRiskAssessment(
                risk_score=risk.risk_score,
                confidence=risk.confidence,
                confidence_rationale=risk.confidence_rationale,
            )

        return {
            "risk_assessments": risks,
            "status": StatusValue.PROCESSING,
        }

    return evaluate


# ── Node: report_risk ─────────────────────────────────────────────────────────


def make_report_risk_node(world_engine: GenericWorldEngine, store: BaseStore | None = None):
    """Factory that creates the risk reporting node.

    Parameters
    ──────────
    store : BaseStore or None
        Optional LangGraph store. When provided, each CollatedRecordRisk is
        written under (``"risk_assessments"``, cluster_id) keyed by
        ``"{row}_{col}"`` for retrieval by the supervisor or a dashboard.
    """

    @node_executor("report_risk")
    def report_risk(state: ClusterAgentState) -> dict:
        """Terminal node — persists risk assessments and marks pipeline complete.

        State reads
        ───────────
          - state.risk_assessments : what to report
          - state.cluster_id      : for store namespace

        State writes
        ────────────
          - status : COMPLETED
        """
        assessments = state.risk_assessments
        cluster_id = state.cluster_id
        grid = world_engine.grid

        for assessment in assessments:
            cell = grid.get_cell(assessment.position.row, assessment.position.col)
            heuristic = getattr(cell, "heuristic", None)
            if heuristic is not None:
                divergence = abs(assessment.risk_score - heuristic)
                if divergence > 4:
                    logger.warning(
                        "ClusterAgent[%s] heuristic divergence at (%s,%s): llm=%s heuristic=%s delta=%s",
                        cluster_id,
                        assessment.position.row,
                        assessment.position.col,
                        assessment.risk_score,
                        heuristic,
                        divergence,
                    )

        if store is not None and assessments:
            for assessment in assessments:
                key = f"{assessment.position.row}_{assessment.position.col}"
                store.put(
                    ("risk_assessments", cluster_id),
                    key,
                    assessment.model_dump(mode="json"),
                )
            logger.info(
                "ClusterAgent[%s] wrote %d risk assessment(s) to store",
                cluster_id,
                len(assessments),
            )
        else:
            logger.info(
                "ClusterAgent[%s] completed with %d risk assessment(s)",
                cluster_id,
                len(assessments) if assessments else 0,
            )

        return {"status": StatusValue.COMPLETED}

    return report_risk


# ── Routers ──────────────────────────────────────────────────────────────────


def route_after_evaluate(state: ClusterAgentState) -> str:
    """Conditional edge router after evaluate node.

    Delegates to route_base:
      - status == ERROR     → END
      - status == COMPLETED → END
      - otherwise           → "report_risk"
    """
    return route_base(state, next_node="report_risk")
