"""Fixtures shared by tests/agents/."""

import pytest

import agents.cluster.nodes as cluster_nodes
from agents.commons import CellReadings, RiskAssessment
from agents.commons.agent_dependencies import AgentDependencies
from agents.commons.llm_registry import LLMRegistry
from prompts import PromptRegistry


@pytest.fixture(autouse=True)
def stub_evaluate():
    """Force stub mode for all cluster tests."""
    original = cluster_nodes.STUB_RISK_SCORE
    cluster_nodes.STUB_RISK_SCORE = True
    yield
    cluster_nodes.STUB_RISK_SCORE = original


@pytest.fixture
def agent_deps(engine) -> AgentDependencies:
    """Lightweight AgentDependencies for stub-mode tests.

    The evaluate node is gated behind STUB_RISK_SCORE=True, so neither
    the LLM registry nor the prompt registry is ever called during tests.
    Both are constructed with minimal config — no API credentials needed.
    """
    registry = PromptRegistry()
    registry.register_models(RiskAssessment, CellReadings)
    return AgentDependencies(
        llm_registry=LLMRegistry({"classifier": None}),
        prompt_registry=registry,
        store=None,
        world_engine=engine,
    )
