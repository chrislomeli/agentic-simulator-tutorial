"""
world-simulator.agents.commons.deps

Dependency injection container for agent graphs.

Lives in its own module so that domain schemas (``schemas.py``) and node
infrastructure (``node_types.py``) remain free of heavy framework imports.
``AgentDependencies`` is the only class here because it is the only type
that needs ``LLMRegistry``, ``PromptRegistry``, and ``BaseStore`` all at once.
"""

from __future__ import annotations

from langgraph.store.base import BaseStore
from pydantic import BaseModel

from agents.commons.llm_registry import LLMRegistry
from prompts import PromptRegistry

# Imported at runtime for Pydantic model validation
from world.risk_heat_map import RiskHeatMap


class AgentDependencies(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    llm_registry: LLMRegistry | None
    prompt_registry: PromptRegistry
    store: BaseStore | None = None
    heat_map: RiskHeatMap | None = None  # Shared risk layer for supervisor queries
