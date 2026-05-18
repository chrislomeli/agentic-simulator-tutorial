"""
world-simulator.agents.commons.deps

Dependency injection container for agent graphs.

Lives in its own module so that domain schemas (``schemas.py``) and node
infrastructure (``node_types.py``) remain free of heavy framework imports.
"""

from __future__ import annotations

from langgraph.store.base import BaseStore
from pydantic import BaseModel

from llm.llm_registry import LLMRegistry
from prompts import PromptRegistry
from stores.base import DataStore
from world import GenericWorldEngine
from world.cell_state_manager import CellStateManager


class AgentDependencies(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    llm_registry: LLMRegistry
    prompt_registry: PromptRegistry
    world_engine: GenericWorldEngine
    # Optional because every consumer already guards for absence
    # (logistics graph: `data_store is not None`; cluster graph passes
    # cell_state_manager into a `| None` factory). Stub-mode tests build
    # partial deps; production always supplies them via composition.
    data_store: DataStore | None = None
    cell_state_manager: CellStateManager | None = None
    store: BaseStore | None = None
