"""
ogar.agents.supervisor.nodes

Node functions for the supervisor LangGraph (stub mode).

These are the stateful functions that orchestrate the workflow —
fan out, wait, assess, decide, dispatch. The graph builder
(add_node, add_edge, compile) lives in graph.py.

Stub mode produces dummy data end-to-end so prompts, observers, and
real logic can be layered on later without restructuring the graph.

Nodes that depend on long-lived resources (the compiled cluster
subgraph, a LangGraph BaseStore) are exposed as make_* factories so
the graph builder can thread dependencies in at compile time.
"""

import logging

from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Send

from agents.cluster.state import ClusterAgentState
from agents.routing import _route_base
from agents.state_types import StatusValue
from agents.supervisor.state import SupervisorState

logger = logging.getLogger(__name__)


# ── Conditional edge: dynamic fan-out ────────────────────────────────────────

def fan_out_to_clusters(state: SupervisorState) -> list[Send]:
    """
    Dynamic fan-out — one Send per active cluster.

    NOTE: This is NOT a regular node. It is a conditional-edge function
    attached to START. LangGraph interprets the returned list of Send()
    objects as: "run all of these targets in parallel, then merge their
    state updates."

    Each Send targets `run_cluster_agent` with a ClusterAgentState payload.
    After all parallel invocations complete (the synchronization barrier),
    LangGraph advances to assess_situation with the accumulated
    cluster_findings.
    """
    cluster_ids = state.active_cluster_ids
    events_by_cluster = state.events_by_cluster

    logger.info(
        "Supervisor fanning out to %d cluster(s): %s",
        len(cluster_ids),
        cluster_ids,
    )

    sends: list[Send] = []
    for cluster_id in cluster_ids:
        events = events_by_cluster.get(cluster_id, [])
        trigger = events[-1] if events else None
        cluster_state = ClusterAgentState(
            cluster_id=cluster_id,
            workflow_id=f"{cluster_id}::supervisor-fanout",
            sensor_events=events,
            trigger_event=trigger,
            error_message=None,
        )
        sends.append(Send("run_cluster_agent", cluster_state))

    return sends


# ── Wrapper node: invokes the cluster subgraph ───────────────────────────────

def make_run_cluster_agent(cluster_graph: CompiledStateGraph):
    """Factory that closes over the compiled cluster subgraph.

    The supervisor invokes the cluster subgraph once per Send emitted
    by fan_out_to_clusters and lifts its anomalies up into the
    supervisor's cluster_findings field via the aggregate_findings reducer.
    """
    def run_cluster_agent(state: ClusterAgentState) -> dict:
        cluster_id = state.cluster_id
        logger.info("Supervisor invoking cluster agent for cluster=%s", cluster_id)

        result = cluster_graph.invoke(state)
        anomalies = result.get("anomalies", [])

        return {"cluster_findings": anomalies}

    return run_cluster_agent


# ── Stub nodes (the supervisor's own steps) ──────────────────────────────────

def assess_situation(state: SupervisorState) -> dict:
    """
    Stub assessor — produces a placeholder summary.

    A real implementation will:
      - Read past incidents from the LangGraph Store
      - Call an LLM to correlate findings across clusters
      - Detect patterns (one large event vs many isolated ones)
    """
    findings = state.cluster_findings
    cluster_ids = state.active_cluster_ids

    summary = (
        f"[STUB] Received {len(findings)} finding(s) from "
        f"{len(cluster_ids)} cluster(s)."
    )

    return {
        "situation_summary": summary,
        "status": StatusValue.PROCESSING,
    }


def decide_actions(state: SupervisorState) -> dict:
    """
    Stub decider — returns no commands.

    A real implementation will use the situation summary and findings
    to choose actuator commands (alert, escalate, drone_task, etc.).
    """
    return {
        "pending_commands": [],
        "status": StatusValue.PROCESSING,
    }


def make_dispatch_commands(store: BaseStore | None = None):
    """Factory for the final dispatch node.

    Returned as a factory so a Store can be injected at compile time
    later (for writing situation summaries to memory). The store
    parameter is unused in stub mode.
    """

    def dispatch_commands(state: SupervisorState) -> dict:
        """Stub dispatcher — logs the commands instead of sending them."""
        commands = state.pending_commands
        logger.info("Supervisor dispatching %d command(s)", len(commands))
        return {"status": StatusValue.COMPLETED}

    return dispatch_commands


# ── Routers ──────────────────────────────────────────────────────────────────

def route_after_decide(state: SupervisorState) -> str:
    return _route_base(state, next_node="dispatch_commands")
