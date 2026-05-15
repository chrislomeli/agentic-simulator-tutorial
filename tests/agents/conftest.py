"""Fixtures shared by tests/agents/.

Construction strategy
─────────────────────
``AgentDependencies`` is a wide collaborator container that the production
graph builders require *in full*. Hand-mirroring its constructor in every
test couples the suite to a moving contract: the moment a field becomes
required, every call site breaks at once (this is exactly the failure that
motivated this file's redesign).

Two construction seams instead of N call sites:

* ``make_agent_deps`` — a Test Data Builder (the "factory as fixture"
  idiom). It fills every required field with a stub-safe default and
  accepts ``**overrides`` for the one dependency a test actually
  exercises. Adding a required field to the model is *one* edit to
  ``defaults`` below — it can no longer fan out into many test failures.
  Graph / integration tests use this (via the ``agent_deps`` convenience
  fixture for the zero-override common case).

* Narrow fixtures (``prompt_registry``, ``llm_registry``) — node-level
  unit tests take only the dependency under test, never the container, so
  they are immune to deps-container churn entirely.

Stub mode (``STUB_RISK_SCORE=True``, forced below) short-circuits the LLM
and prompt registries, so none of these defaults need API credentials.
"""

import pytest

import agents.cluster.nodes as cluster_nodes
from agents.commons import CellReadings, RiskAssessment
from agents.commons.agent_dependencies import AgentDependencies
from llm.llm_registry import LLMRegistry
from prompts import PromptRegistry
from stores.mock import MockDataStore
from world.cell_state_manager import CellStateManager


@pytest.fixture(autouse=True)
def stub_evaluate():
    """Force stub mode for all agent tests."""
    original = cluster_nodes.STUB_RISK_SCORE
    cluster_nodes.STUB_RISK_SCORE = True
    yield
    cluster_nodes.STUB_RISK_SCORE = original


# ── Narrow fixtures (node-level unit tests) ──────────────────────────────────


@pytest.fixture
def prompt_registry() -> PromptRegistry:
    """A PromptRegistry with the cluster schemas registered.

    Stub mode never calls it; it exists only to satisfy node factories
    that take it as a parameter.
    """
    registry = PromptRegistry()
    registry.register_models(RiskAssessment, CellReadings)
    return registry


@pytest.fixture
def llm_registry() -> LLMRegistry:
    """A credential-free LLMRegistry — never invoked in stub mode."""
    return LLMRegistry({"classifier": None})


# ── Test Data Builder (graph / integration tests) ────────────────────────────


@pytest.fixture
def make_agent_deps(engine, prompt_registry, llm_registry):
    """Builder for a complete ``AgentDependencies``.

    The single construction seam: every required field has a stub-safe
    default here. Pass keyword overrides for the dependency a test wants
    to vary, e.g. ``make_agent_deps(store=InMemoryStore())``. A new
    required field on the model is one line in ``defaults`` — not a
    scavenger hunt through failing tests.
    """

    def _build(**overrides) -> AgentDependencies:
        defaults = dict(
            llm_registry=llm_registry,
            prompt_registry=prompt_registry,
            data_store=MockDataStore(),
            world_engine=engine,
            cell_state_manager=CellStateManager(engine.grid),
        )
        return AgentDependencies(**{**defaults, **overrides})

    return _build


@pytest.fixture
def agent_deps(make_agent_deps) -> AgentDependencies:
    """A fully-defaulted ``AgentDependencies`` for the zero-override case."""
    return make_agent_deps()
