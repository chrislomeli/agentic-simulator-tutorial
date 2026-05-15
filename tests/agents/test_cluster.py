"""Tests for agents.cluster — state schema, node functions, graph."""

from langgraph.graph.state import CompiledStateGraph
from langgraph.store.memory import InMemoryStore

from agents.cluster.graph import build_cluster_agent_graph
from agents.cluster.nodes import make_evaluate_node, make_report_risk_node, route_after_evaluate
from agents.cluster.state import ClusterAgentState
from agents.commons.schemas import (
    CellReadings,
    CollatedRecordRisk,
    GridPosition,
)
from agents.commons.state_types import StatusValue

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_readings(
    cluster_id: str = "cluster-north",
    row: int = 0,
    col: int = 0,
) -> CellReadings:
    return CellReadings(
        cluster_id=cluster_id,
        position=GridPosition(row=row, col=col),
        metrics=[],
    )


def _make_state(**overrides) -> ClusterAgentState:
    base = ClusterAgentState(cluster_id="cluster-north", workflow_id="test-run-1")
    return base.model_copy(update=overrides) if overrides else base


# ── ClusterAgentState schema tests ───────────────────────────────────────────

class TestClusterAgentState:
    def test_defaults(self):
        state = ClusterAgentState(cluster_id="c1", workflow_id="w1")
        assert state.cluster_id == "c1"
        assert state.workflow_id == "w1"
        assert state.readings == []
        assert state.risk_assessments == []
        assert state.messages == []
        assert state.status == StatusValue.IDLE

    def test_cluster_id_has_uuid_default(self):
        state = ClusterAgentState(workflow_id="w1")
        assert state.cluster_id  # non-empty UUID string


# ── evaluate node tests ───────────────────────────────────────────────────────

class TestEvaluateNode:
    async def test_empty_cells_returns_empty_assessments(
        self, prompt_registry, llm_registry, engine
    ):
        evaluate = make_evaluate_node(
            prompt_registry=prompt_registry,
            llm_registry=llm_registry,
            world_engine=engine,
        )
        state = _make_state()
        result = await evaluate(state)
        assert result["risk_assessments"] == []
        assert result["status"] == StatusValue.PROCESSING

    async def test_stub_produces_one_risk_per_cell(
        self, prompt_registry, llm_registry, engine
    ):
        evaluate = make_evaluate_node(
            prompt_registry=prompt_registry,
            llm_registry=llm_registry,
            world_engine=engine,
        )
        cells = [{"row": 0, "col": 0}, {"row": 0, "col": 1}]
        state = _make_state(updated_cells=cells)
        result = await evaluate(state)
        assert len(result["risk_assessments"]) == 2
        for risk in result["risk_assessments"]:
            assert isinstance(risk, CollatedRecordRisk)
            assert 0 <= risk.risk_score <= 10
            assert 0 <= risk.confidence <= 3

    async def test_stub_writes_risk_to_cell(
        self, prompt_registry, llm_registry, engine
    ):
        """evaluate must write CellRiskAssessment onto the grid cell so
        sector_analysis can find hotspots."""
        from agents.commons.schemas import CellRiskAssessment
        evaluate = make_evaluate_node(
            prompt_registry=prompt_registry,
            llm_registry=llm_registry,
            world_engine=engine,
        )
        # heuristic_score must be >= HEURISTIC_EVALUATE_THRESHOLD to pass the gate
        state = _make_state(updated_cells=[{"row": 2, "col": 3, "heuristic_score": 5}])
        await evaluate(state)
        cell = engine.grid.get_cell(2, 3)
        assert isinstance(cell.risk_assessment, CellRiskAssessment)



# ── route_after_evaluate tests ────────────────────────────────────────────────

class TestRouteAfterEvaluate:
    def test_routes_to_report_risk_when_processing(self):
        state = _make_state(status=StatusValue.PROCESSING)
        assert route_after_evaluate(state) == "report_risk"

    def test_routes_to_report_risk_when_idle(self):
        state = _make_state()  # default status: IDLE
        assert route_after_evaluate(state) == "report_risk"

    def test_routes_to_end_on_error(self):
        from langgraph.graph import END
        state = _make_state(status=StatusValue.ERROR)
        assert route_after_evaluate(state) == END

    def test_routes_to_end_on_completed(self):
        from langgraph.graph import END
        state = _make_state(status=StatusValue.COMPLETED)
        assert route_after_evaluate(state) == END


# ── report_risk node tests ────────────────────────────────────────────────────

class TestReportRiskNode:
    def test_sets_completed_status(self, engine):
        report_risk = make_report_risk_node(world_engine=engine, store=None)
        state = _make_state()
        result = report_risk(state)
        assert result["status"] == StatusValue.COMPLETED

    def test_no_store_does_not_raise(self, engine):
        report_risk = make_report_risk_node(world_engine=engine, store=None)
        state = _make_state(risk_assessments=[])
        result = report_risk(state)
        assert result["status"] == StatusValue.COMPLETED

    def test_writes_to_store_when_provided(self, engine):
        store = InMemoryStore()
        report_risk = make_report_risk_node(world_engine=engine, store=store)
        assessment = CollatedRecordRisk(
            position=GridPosition(row=1, col=2),
            risk_score=7,
            confidence=3,
            confidence_rationale="test",
            contributing_factors=["high temp"],
        )
        state = _make_state(
            cluster_id="cluster-north",
            risk_assessments=[assessment],
        )
        report_risk(state)
        items = store.search(("risk_assessments", "cluster-north"))
        assert len(items) == 1
        assert items[0].value["risk_score"] == 7

    def test_empty_assessments_writes_nothing_to_store(self, engine):
        store = InMemoryStore()
        report_risk = make_report_risk_node(world_engine=engine, store=store)
        state = _make_state(cluster_id="cluster-north", risk_assessments=[])
        report_risk(state)
        items = store.search(("risk_assessments", "cluster-north"))
        assert len(items) == 0

    def test_multiple_assessments_stored_by_position(self, engine):
        store = InMemoryStore()
        report_risk = make_report_risk_node(world_engine=engine, store=store)
        assessments = [
            CollatedRecordRisk(
                position=GridPosition(row=r, col=c),
                risk_score=5,
                confidence=2,
                confidence_rationale="test",
                contributing_factors=[],
            )
            for r, c in [(0, 0), (1, 1), (2, 2)]
        ]
        state = _make_state(cluster_id="cluster-north", risk_assessments=assessments)
        report_risk(state)
        items = store.search(("risk_assessments", "cluster-north"))
        assert len(items) == 3


# ── graph integration tests ───────────────────────────────────────────────────

class TestClusterAgentGraph:
    def test_build_returns_compiled_graph(self, agent_deps):
        graph = build_cluster_agent_graph(agent_deps=agent_deps)
        assert isinstance(graph, CompiledStateGraph)

    def test_graph_nodes_are_evaluate_and_report_risk(self, agent_deps):
        graph = build_cluster_agent_graph(agent_deps=agent_deps)
        node_names = set(graph.get_graph().nodes.keys())
        assert "evaluate" in node_names
        assert "report_risk" in node_names

    async def test_invoke_with_readings_produces_risk_assessments(self, agent_deps):
        graph = build_cluster_agent_graph(agent_deps=agent_deps)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test-graph-1",
            readings=[_make_readings()],
        )
        result = await graph.ainvoke(state)
        assert result["status"] == StatusValue.COMPLETED

    async def test_invoke_empty_readings_completes_cleanly(self, agent_deps):
        graph = build_cluster_agent_graph(agent_deps=agent_deps)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test-empty",
        )
        result = await graph.ainvoke(state)
        assert result["status"] == StatusValue.COMPLETED
        assert result["risk_assessments"] == []
