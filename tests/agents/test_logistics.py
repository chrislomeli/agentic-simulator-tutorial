"""Tests for agents.logistics — graph topology, node functions, routing."""

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.graph.state import CompiledStateGraph

from agents.commons.schemas import CellRiskAssessment
from agents.commons.state_types import StatusValue
from agents.logistics.graph import build_logistics_agent_graph
from agents.logistics.nodes import (
    make_extract_plan_node,
    make_logistics_agent_node,
    route_after_logistics_agent,
)
from agents.logistics.state import LogisticsAgentState

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> LogisticsAgentState:
    base = LogisticsAgentState(workflow_id="test-logistics")
    return base.model_copy(update=overrides) if overrides else base


def _plant_hotspot(engine, row: int, col: int, risk_score: int = 7) -> None:
    cell = engine.grid.get_cell(row, col)
    cell.risk_assessment = CellRiskAssessment(
        risk_score=risk_score,
        confidence=2,
        confidence_rationale="planted for test",
    )


# ── graph build tests ─────────────────────────────────────────────────────────


class TestBuildLogisticsGraph:
    def test_returns_compiled_graph(self, agent_deps):
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        assert isinstance(graph, CompiledStateGraph)

    def test_graph_contains_sector_analysis_node(self, agent_deps):
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        nodes = set(graph.get_graph().nodes.keys())
        assert "sector_analysis" in nodes

    def test_graph_contains_logistics_agent_node(self, agent_deps):
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        nodes = set(graph.get_graph().nodes.keys())
        assert "logistics_agent" in nodes

    def test_graph_contains_extract_plan_node(self, agent_deps):
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        nodes = set(graph.get_graph().nodes.keys())
        assert "extract_plan" in nodes

    def test_no_world_engine_skips_sector_analysis(self, agent_deps):
        """When world_engine is None the graph should still compile without sector_analysis."""
        from agents.commons.agent_dependencies import AgentDependencies
        deps = AgentDependencies(
            llm_registry=agent_deps.llm_registry,
            prompt_registry=agent_deps.prompt_registry,
            store=None,
            world_engine=None,
        )
        graph = build_logistics_agent_graph(agent_deps=deps)
        nodes = set(graph.get_graph().nodes.keys())
        assert "sector_analysis" not in nodes
        assert "logistics_agent" in nodes


# ── route_after_logistics_agent tests ────────────────────────────────────────


class TestRouteAfterLogisticsAgent:
    def test_no_messages_routes_to_extract_plan(self):
        state = _make_state()
        assert route_after_logistics_agent(state) == "extract_plan"

    def test_plain_ai_message_routes_to_extract_plan(self):
        msg = AIMessage(content="Here is the plan.")
        state = _make_state(messages=[msg], status=StatusValue.PROCESSING)
        assert route_after_logistics_agent(state) == "extract_plan"

    def test_ai_message_with_tool_calls_routes_to_tools(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "1", "name": "get_resources_within", "args": {"cell_row": 0, "cell_col": 0, "max_distance_mi": 15}}],
        )
        state = _make_state(messages=[msg], status=StatusValue.PROCESSING)
        assert route_after_logistics_agent(state) == "tools"

    def test_error_status_routes_to_end(self):
        state = _make_state(status=StatusValue.ERROR)
        assert route_after_logistics_agent(state) == END


# ── extract_logistics_plan tests ──────────────────────────────────────────────


class TestExtractLogisticsPlan:
    def test_lifts_last_message_content_as_plan(self):
        node = make_extract_plan_node()
        msg = AIMessage(content="Deploy 3 engines to sector NE.")
        state = _make_state(messages=[msg])
        result = node(state)
        assert result["logistics_plan"] == "Deploy 3 engines to sector NE."

    def test_sets_completed_status(self):
        node = make_extract_plan_node()
        msg = AIMessage(content="Monitor only.")
        state = _make_state(messages=[msg])
        result = node(state)
        assert result["status"] == StatusValue.COMPLETED

    def test_no_messages_produces_fallback_plan(self):
        node = make_extract_plan_node()
        state = _make_state()
        result = node(state)
        assert result["logistics_plan"] == "[No plan produced]"
        assert result["status"] == StatusValue.COMPLETED

    def test_uses_last_message_not_first(self):
        node = make_extract_plan_node()
        msgs = [
            AIMessage(content="Initial thinking."),
            AIMessage(content="Final recommendation."),
        ]
        state = _make_state(messages=msgs)
        result = node(state)
        assert result["logistics_plan"] == "Final recommendation."

    def test_no_llm_assessment_is_none(self):
        node = make_extract_plan_node()
        msg = AIMessage(content="Plan text.")
        state = _make_state(messages=[msg])
        result = node(state)
        assert result["logistics_assessment"] is None


# ── make_logistics_agent_node stub tests ──────────────────────────────────────


class TestLogisticsAgentNodeStub:
    def test_stub_returns_ai_message(self, agent_deps):
        node = make_logistics_agent_node(
            tools=[],
            prompt_registry=agent_deps.prompt_registry,
            llm_registry=agent_deps.llm_registry,
        )
        state = _make_state()
        result = node(state)
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)

    def test_stub_message_has_no_tool_calls(self, agent_deps):
        node = make_logistics_agent_node(
            tools=[],
            prompt_registry=agent_deps.prompt_registry,
            llm_registry=agent_deps.llm_registry,
        )
        state = _make_state()
        result = node(state)
        msg = result["messages"][0]
        assert not getattr(msg, "tool_calls", None)

    def test_stub_sets_processing_status(self, agent_deps):
        node = make_logistics_agent_node(
            tools=[],
            prompt_registry=agent_deps.prompt_registry,
            llm_registry=agent_deps.llm_registry,
        )
        state = _make_state()
        result = node(state)
        assert result["status"] == StatusValue.PROCESSING


# ── full graph integration tests ──────────────────────────────────────────────


class TestLogisticsGraphIntegration:
    async def test_invoke_no_hotspots_completes(self, agent_deps):
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        state = LogisticsAgentState(workflow_id="test-no-hotspots")
        result = await graph.ainvoke(state)
        assert result["status"] == StatusValue.COMPLETED

    async def test_invoke_no_hotspots_produces_plan(self, agent_deps):
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        state = LogisticsAgentState(workflow_id="test-no-hotspots")
        result = await graph.ainvoke(state)
        assert result["logistics_plan"] is not None

    async def test_invoke_with_hotspot_completes(self, agent_deps):
        _plant_hotspot(agent_deps.world_engine, row=2, col=2, risk_score=8)
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        state = LogisticsAgentState(workflow_id="test-with-hotspot")
        result = await graph.ainvoke(state)
        assert result["status"] == StatusValue.COMPLETED

    async def test_invoke_with_hotspot_situation_summary_populated(self, agent_deps):
        """sector_analysis must write situation_summary before logistics_agent runs."""
        _plant_hotspot(agent_deps.world_engine, row=2, col=2, risk_score=8)
        graph = build_logistics_agent_graph(agent_deps=agent_deps)
        state = LogisticsAgentState(workflow_id="test-summary")
        result = await graph.ainvoke(state)
        assert result["situation_summary"]
        assert "hotspot" in result["situation_summary"].lower() or "2" in result["situation_summary"]
