"""
world-simulator.agents.commons.deps

Dependency injection container for agent graphs.

Lives in its own module so that domain schemas (``schemas.py``) and node
infrastructure (``node_types.py``) remain free of heavy framework imports.
"""

from __future__ import annotations

from langgraph.store.base import BaseStore
from pydantic import BaseModel

from prompts import PromptRegistry
from stores.base import DataStore
from world import GenericWorldEngine
from world.cell_state_manager import CellStateManager


class AgentDependencies(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    prompt_registry: PromptRegistry
    data_store: DataStore | None = None
    world_engine: GenericWorldEngine | None
    cell_state_manager: CellStateManager | None = None
    store: BaseStore | None = None
