"""
world-simulator.agents.supervisor.nodes

Node functions for the supervisor LangGraph (stub mode).

These are the stateful functions that orchestrate the workflow —
fan out, wait, assess, decide, dispatch. The graph builder
(``add_node``, ``add_edge``, ``compile``) lives in ``graph.py``.

Stub mode produces deterministic output end-to-end so the full graph
topology can be validated and the dashboard pipeline exercised before
LLM reasoning is wired in.

Nodes that depend on long-lived resources (the compiled cluster
subgraph, a LangGraph ``BaseStore``) are exposed as ``make_*``
factories so the graph builder can thread dependencies in at compile
time. This keeps the module free of side effects at import time.
"""

import logging

from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Send

from agents.cluster.state import ClusterAgentState
from agents.commons.schemas import CellReadings, CollatedRecordRisk, Colors
from agents.commons.state_types import StatusValue
from agents.logistics.state import LogisticsAgentState
from agents.supervisor.state import RiskScore, SupervisorState

logger = logging.getLogger(__name__)


# ── Conditional edge: dynamic fan-out ────────────────────────────────────────


def fan_out_to_clusters(state: SupervisorState) -> list[Send]:
    """Dynamic fan-out — one ``Send`` per active cluster.

    NOTE: This is NOT a regular node. It is a conditional-edge function
    attached to ``START``. LangGraph interprets the returned list of
    ``Send()`` objects as: "run all of these targets in parallel, then
    merge their state updates via the registered reducers."

    Each ``Send`` targets ``run_cluster_agent`` with a
    ``ClusterAgentState`` pre-populated with that cluster's CellReadings.
    After all parallel invocations complete (the synchronization barrier),
    LangGraph advances to ``assess_situation`` with the accumulated
    ``cluster_score`` and ``cluster_findings``.
    """
    print(f"{Colors.GREEN} NODE:: fan_out_to_clusters{Colors.RESET}")
    clusters: dict[str, list[CellReadings]] = state.clusters
    cluster_ids = list(clusters.keys())
    logger.info(
        "Supervisor fanning out to %d cluster(s): %s",
        len(cluster_ids),
        cluster_ids,
    )

    sends: list[Send] = []
    for cluster_id, readings in clusters.items():
        cluster_state = ClusterAgentState(
            cluster_id=cluster_id,
            workflow_id=f"{cluster_id}::supervisor-fanout",
            readings=readings,
            error=None,
        )
        sends.append(Send("run_cluster_agent", cluster_state))

    return sends


# ── Stateful nodes (factories) ───────────────────────────────────────────────


def make_run_cluster_agent(cluster_graph: CompiledStateGraph):
    """Factory that closes over the compiled cluster subgraph.

    The supervisor invokes the cluster subgraph once per ``Send`` emitted
    by ``fan_out_to_clusters``. Results are lifted into supervisor state:
      - ``cluster_findings`` receives the list of CollatedRecordRisk objects.
      - ``cluster_score`` receives the highest risk_score in that list
        (0 if the list is empty).

    Both fields use reducers so parallel sends merge cleanly.
    """

    async def run_cluster_agent(state: ClusterAgentState) -> dict:
        print(f"{Colors.GREEN} NODE:: run_cluster_agent{Colors.RESET}")
        cluster_id = state.cluster_id
        logger.info("Supervisor invoking cluster agent for cluster=%s", cluster_id)

        result = await cluster_graph.ainvoke(state)
        assessments: list[CollatedRecordRisk] = result.get("risk_assessments", [])
        if assessments:
            highest = max(assessments, key=lambda r: r.risk_score)
            cluster_score = RiskScore(risk_score=highest.risk_score, confidence=highest.confidence)
        else:
            cluster_score = RiskScore(risk_score=0, confidence=0)

        return {
            "cluster_findings": {cluster_id: assessments},
            "cluster_score": {cluster_id: cluster_score},
        }

    return run_cluster_agent


# ── Stub nodes (the supervisor's own steps) ──────────────────────────────────


def assess_situation(state: SupervisorState) -> dict:
    """Stub assessor — produces a placeholder situation summary.

    A real implementation will read past incidents from the LangGraph
    Store, call an LLM to correlate findings across clusters, and detect
    cross-cluster patterns (e.g. one large event vs many isolated ones).
    """
    print(f"{Colors.GREEN} NODE:: assess_situation{Colors.RESET}")
    findings = state.cluster_findings
    cluster_ids = list(state.clusters.keys())

    summary = (
        f"[STUB] Received findings from {len(findings)} cluster(s) ({len(cluster_ids)} active)."
    )

    return {
        "situation_summary": summary,
        "status": StatusValue.PROCESSING,
    }


def decide_actions(state: SupervisorState) -> dict:
    """Stub decider — returns no commands.

    A real implementation will use the situation summary and cluster scores
    to choose actuator commands (alert, escalate, drone_task, ...).
    """
    return {
        "pending_commands": [],
        "status": StatusValue.PROCESSING,
    }


def make_run_logistics_agent(logistics_graph: CompiledStateGraph):
    """Factory that closes over the compiled logistics subgraph.

    Builds the initial LogisticsAgentState from the supervisor's situation
    summary and cluster findings, invokes the logistics graph, then lifts the
    resulting plan back into supervisor state.
    """

    def run_logistics_agent(state: SupervisorState) -> dict:
        print(f"{Colors.GREEN} NODE:: run_logistics_agent{Colors.RESET}")
        logistics_state = LogisticsAgentState(
            situation_summary=state.situation_summary or "",
            cluster_findings=state.cluster_findings,
        )
        result = logistics_graph.invoke(logistics_state)
        plan = result.get("logistics_plan")
        logger.info(
            "Logistics agent completed. Plan preview: %s",
            (plan[:120] + "...") if plan and len(plan) > 120 else plan,
        )
        return {"logistics_plan": plan, "status": StatusValue.PROCESSING}

    return run_logistics_agent


def make_dispatch_commands(store: BaseStore | None = None):
    """Factory for the final dispatch node.

    The store parameter is reserved for persisting situation summaries to
    long-term memory once that capability is wired in. Stub mode ignores it.
    """

    def dispatch_commands(state: SupervisorState) -> dict:
        print(f"{Colors.GREEN} NODE:: dispatch_commands{Colors.RESET}")
        commands = state.pending_commands
        logger.info("Supervisor dispatching %d command(s)", len(commands))

        print(f"\n{Colors.YELLOW}DISPATCH FINAL FINDINGS")
        print(f"{state.situation_summary}")
        print(f"{state.cluster_findings}\n\n")
        print("Cluster risk scores (0–10)")
        for key, value in state.cluster_score.items():
            print(f"{key}: risk_score: {value.risk_score}, confidence: {value.confidence}")
        if state.logistics_plan:
            print("\nLOGISTICS PLAN")
            print(state.logistics_plan)
        print(f"{Colors.RESET}")
        return {"status": StatusValue.COMPLETED}

    return dispatch_commands


# ── Routers ──────────────────────────────────────────────────────────────────

# Must match the risk_threshold passed to make_sector_analysis_node.
# If sector_analysis won't find a hotspot, there's nothing for logistics to do.
LOGISTICS_RISK_THRESHOLD = 5


def route_after_assess(state: SupervisorState) -> str:
    """Conditional edge after assess_situation.

    Skips the logistics agent entirely when no cluster has a risk score at
    or above the sector_analysis threshold — there are no hotspots to report
    on, so firing the logistics LLM would waste tokens and produce noise.

    Routes to:
      "run_logistics_agent"  — at least one cluster scored >= LOGISTICS_RISK_THRESHOLD
      "dispatch_commands"    — all scores below threshold, or no scores at all
    """
    if not state.cluster_score:
        logger.info("route_after_assess: no cluster scores — skipping logistics")
        return "dispatch_commands"

    max_score = max(rs.risk_score for rs in state.cluster_score.values())
    if max_score >= LOGISTICS_RISK_THRESHOLD:
        logger.info(
            "route_after_assess: max score %d >= %d — invoking logistics agent",
            max_score,
            LOGISTICS_RISK_THRESHOLD,
        )
        return "run_logistics_agent"

    logger.info(
        "route_after_assess: max score %d < %d — skipping logistics",
        max_score,
        LOGISTICS_RISK_THRESHOLD,
    )
    return "dispatch_commands"


def route_after_decide(state: SupervisorState) -> str:
    """Conditional edge router after decide_actions.

    Delegates to route_base:
      - status == ERROR     → END
      - status == COMPLETED → END
      - otherwise           → "dispatch_commands"
    """
    return "dispatch_commands"
