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
import json
import logging

from langgraph.store.base import BaseStore

from agents.commons.schemas import CellReadings, CollatedRecordRisk, Colors
from agents.commons.state_types import StatusValue
from agents.supervisor.state import SupervisorState, RiskScore

logger = logging.getLogger(__name__)


# ── Conditional edge: dynamic fan-out ────────────────────────────────────────


def fan_out_to_clusters(state: SupervisorState) :
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
    clusters = state.clusters
    cluster_ids = list(clusters.keys())
    logger.info(
        "Supervisor looping for %d cluster(s): %s",
        len(cluster_ids),
        cluster_ids,
    )

    cluster_score: dict[str, RiskScore] = {}
    cluster_findings: dict[str, list[CollatedRecordRisk] ] = {}
    for cluster_id, readings in clusters.items():
        findings: list[CollatedRecordRisk] = []
        for reading in readings:
            f = CollatedRecordRisk(position=reading.position, risk_score=10, confidence=3, confidence_rationale='Dummy rationale', contributing_factors=['pass-thru stub'])
            findings.append(f)
        cluster_findings[cluster_id] =  findings
        cluster_score[cluster_id] = RiskScore(risk_score=10, confidence=3)

    return {
        "cluster_findings": cluster_findings,
        "cluster_score": cluster_score,
    }



# ── Stateful nodes (factories) ───────────────────────────────────────────────


# ── Stub nodes (the supervisor's own steps) ──────────────────────────────────


def assess_situation(state: SupervisorState) -> dict:
    """Stub assessor — produces a placeholder situation summary.

    A real implementation will read past incidents from the LangGraph
    Store, call an LLM to correlate findings across clusters, and detect
    cross-cluster patterns (e.g. one large event vs many isolated ones).
    """
    print(f"{Colors.GREEN} NODE:: assess_situation{Colors.RESET}")
    cluster_ids = list(state.clusters.keys())

    summary = f"""processed clusters:: {json.dumps(cluster_ids)}\n"""

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


