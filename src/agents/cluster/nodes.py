"""
world-simulator.agents.cluster.nodes

Node functions for the cluster agent's risk assessment pipeline.

Pipeline shape (dashboard milestone)
──────────────────────────────────────
    START → evaluate → route_after_evaluate → report_risk → END

    evaluate    : AI boundary. Stub mode returns deterministic placeholder
                  risk scores (STUB_RISK_SCORE=True). LLM mode calls the
                  model with structured output — enabled in the next milestone.
    report_risk : Terminal node. Persists CollatedRecordRisk records to the
                  optional store and marks the pipeline COMPLETED.

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

import logging

from langgraph.store.base import BaseStore

from agents.cluster.state import ClusterAgentState
from agents.commons.schemas import (
    CollatedRecord,
    CollatedRecordRisk,
)
from agents.commons.state_types import StatusValue

logger = logging.getLogger(__name__)


# ── Milestone flag ────────────────────────────────────────────────────────────
#
# True for the dashboard milestone: evaluate returns stub CollatedRecordRisk
# records without calling an LLM. Flip to False in the next milestone once
# the prompt template and LLM tooling are ready.
STUB_RISK_SCORE = False


# ── Node: evaluate ────────────────────────────────────────────────────────────


def make_evaluate_node():
    """Factory that creates the evaluate node.

    This is the AI boundary. Everything before this node is deterministic.
    The evaluate node receives CollatedRecords and produces CollatedRecordRisk
    assessments — one per cell — by reasoning about fire risk.

    Parameters
    ──────────
    prompt_registry : PromptRegistry
        For rendering the system prompt template when LLM mode is active.
    llm_registry : LLMRegistry
        For looking up the LLM to use (role: "classifier") when LLM mode
        is active. Unused in stub mode.
    """

    def evaluate(state: ClusterAgentState) -> dict:
        """Evaluate fire risk for every CollatedRecord in this cluster.

        Stub mode (STUB_RISK_SCORE=True):
          Returns deterministic placeholder scores — one per record.
          No LLM is called. Used to validate the full pipeline topology
          and drive the dashboard before the prompt template is ready.

        LLM mode (STUB_RISK_SCORE=False, next milestone):
          Renders the system prompt, serialises all records as the human
          message, and calls the LLM with structured output (RiskAssessment).

        State reads
        ───────────
          - state.collated_records : pre-populated by the orchestrator
          - state.cluster_id      : for logging and LLM context

        State writes
        ────────────
          - risk_assessments : list[CollatedRecordRisk], one per record
          - status           : PROCESSING
        """
        records: list[CollatedRecord] = state.collated_records
        cluster_id: str = state.cluster_id

        if not records:
            logger.warning("ClusterAgent[%s] evaluate: no collated records", cluster_id)
            return {
                "risk_assessments": [],
                "status": StatusValue.PROCESSING,
            }

        # Stub: one placeholder risk per record, position copied from input.
        risks = [
            CollatedRecordRisk(
                position=cr.position,
                risk_score=5,
                confidence=3,
                confidence_rationale="Stub score — LLM not active in this milestone.",
                contributing_factors=["stub"],
            )
            for cr in records
        ]
        return {
            "risk_assessments": risks,
            "status": StatusValue.PROCESSING,
        }

    return evaluate


# ── Node: report_risk ─────────────────────────────────────────────────────────


def make_report_risk_node(store: BaseStore | None = None):
    """Factory that creates the risk reporting node.

    Parameters
    ──────────
    store : BaseStore or None
        Optional LangGraph store. When provided, each CollatedRecordRisk is
        written under (``"risk_assessments"``, cluster_id) keyed by
        ``"{row}_{col}"`` for retrieval by the supervisor or a dashboard.
    """

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
    return "report_risk"
