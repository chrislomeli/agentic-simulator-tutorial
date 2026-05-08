# """
# world-simiulator.agents
#
# LangGraph agents that turn sensor events into supervisor commands.
#
# Public API
# ──────────
#     from agents import (
#         AnomalyFinding,
#         ClusterAgentState,
#         SupervisorState,
#         build_cluster_agent_graph,
#         build_supervisor_graph,
#         StatusValue,
#     )
#
# Each sub-package owns its __init__.py as its public surface. This module
# re-exports from those for callers that want a single flat import.
#
# Composition root: register agent models with the PromptRegistry directly —
#     registry.register_model(AnomalyFinding)
# That call belongs in the composition root, not in a package helper.
# """
#
# from agents.cluster import ClusterAgentState, build_cluster_agent_graph
# from agents import AgentDependencies
# from agents.commons import AnomalyFinding, StatusValue
# from agents.supervisor import ActuatorCommand, SupervisorState, build_supervisor_graph
#
# __all__ = [
#     "ActuatorCommand",
#     "AgentDependencies",
#     "AnomalyFinding",
#     "ClusterAgentState",
#     "StatusValue",
#     "SupervisorState",
#     "build_cluster_agent_graph",
#     "build_supervisor_graph",
# ]
