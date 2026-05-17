"""runtime.composition — deployment-agnostic assembly of agent
dependencies and the supervisor graph.

Why this module exists
──────────────────────
``main.py`` is the *local* entrypoint: it owns the Postgres bootstrap,
scenario load, and the asyncio run loop. None of that is relevant to a
different deployment target (e.g. a Bedrock AgentCore handler), yet the
dependency/graph assembly is identical across targets.

Splitting that assembly out here means every entrypoint builds the exact
same graph through one seam — the local loop and any remote handler differ
only in transport and lifecycle, never in how the agent graph is wired.
There is deliberately no module-level singleton: dependencies are built
per call at the composition root and threaded down.
"""

from __future__ import annotations

from agents.commons.agent_dependencies import AgentDependencies
from agents.commons.schemas import CellReadings, CollatedRecordRisk
from agents.logistics.state import LogisticsAssessment
from agents.supervisor.graph import build_supervisor_graph
from agents.supervisor.state import SupervisorGraph
from config import get_settings
from llm.llm_registry import LLM_ROLE_CONFIG, build_llm_registry, models
from prompts import PromptRegistry
from stores.base import DataStore
from world import GenericWorldEngine
from world.cell_state_manager import CellStateManager


def build_agent_dependencies(
    engine: GenericWorldEngine,
    cell_state_manager: CellStateManager,
    data_store: DataStore | None = None,
) -> AgentDependencies:
    """Assemble the LLM/prompt/store dependencies for graph compilation.

    Deployment-agnostic: no Postgres bootstrap, no scenario load, no run
    loop. Both the local entrypoint and any remote entrypoint build
    dependencies through here so the compiled graph is identical across
    deployments.
    """
    settings = get_settings()
    settings.apply_langsmith()

    llm_registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)

    prompt_registry = PromptRegistry()
    prompt_registry.register_models(CellReadings, CollatedRecordRisk, LogisticsAssessment)

    return AgentDependencies(
        prompt_registry=prompt_registry,
        llm_registry=llm_registry,
        world_engine=engine,
        cell_state_manager=cell_state_manager,
        store=None,
        data_store=data_store,
    )


def build_supervisor(agent_deps: AgentDependencies) -> SupervisorGraph:
    """Compile the supervisor graph from assembled dependencies.

    The single place any entrypoint turns dependencies into a runnable
    graph. Kept thin on purpose — it is a seam, not a layer.
    """
    return build_supervisor_graph(agent_dependencies=agent_deps)
