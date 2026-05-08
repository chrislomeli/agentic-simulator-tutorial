"""
world-simulator.agents.cluster

Public API for the cluster agent — one subgraph per sensor cluster.

The cluster agent receives sensor events, classifies anomalies via LLM,
and reports findings upward to the supervisor. This module exposes the
state schema, graph builder, and the AgentDependencies container used
by both cluster and supervisor agents.

Quick reference:
  - ClusterAgentState       → Pydantic state schema with reducers for event accumulation
  - build_cluster_agent_graph → Factory that compiles the LangGraph subgraph
  - AgentDependencies       → DI container (from commons.deps)
"""

from agents.cluster.graph import build_cluster_agent_graph
from agents.cluster.state import ClusterAgentState

__all__ = [
    "ClusterAgentState",
    "build_cluster_agent_graph",
]
