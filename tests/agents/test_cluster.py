"""Tests for agents.cluster — state schema, node functions, graph."""

from datetime import datetime, timezone

import pytest
from langgraph.store.memory import InMemoryStore

from agents.cluster.graph import build_cluster_agent_graph
from agents.cluster.nodes import make_evaluate_node, make_report_risk_node, route_after_evaluate
from agents.cluster.state import ClusterAgentState
from langgraph.graph.state import CompiledStateGraph
from agents.commons.agent_dependencies import AgentDependencies
from agents.commons.schemas import (
    CollatedRecord,
    CollatedRecordRisk,
    CoverageSummary,
    GridPosition,
    TerrainContext,
    TimeWindow,
)
from agents.commons.state_types import StatusValue


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_record(
    cluster_id: str = "cluster-north",
    row: int = 0,
    col: int = 0,
) -> CollatedRecord:
    now = _now()
    return CollatedRecord(
        cluster_id=cluster_id,
        position=GridPosition(row=row, col=col),
        window=TimeWindow(start=now, end=now),
        coverage=CoverageSummary(),
        terrain=TerrainContext(
            terrain_type="grassland",
            vegetation=0.7,
            fuel_moisture=0.2,
            slope=5.0,
        ),
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
        assert state.collated_records == []
        assert state.risk_assessments == []
        assert state.messages == []
        assert state.status == StatusValue.IDLE

    def test_cluster_id_has_uuid_default(self):
        state = ClusterAgentState(workflow_id="w1")
        assert state.cluster_id  # non-empty UUID string


# ── evaluate node tests ───────────────────────────────────────────────────────

class TestEvaluateNode:
    def test_empty_records_returns_empty_assessments(self, agent_deps):
        evaluate = make_evaluate_node(
            prompt_registry=agent_deps.prompt_registry,
            llm_registry=agent_deps.llm_registry,
            heat_map=agent_deps.heat_map,
        )
        state = _make_state()
        result = evaluate(state)
        assert result["risk_assessments"] == []
        assert result["status"] == StatusValue.PROCESSING

    def test_stub_produces_one_risk_per_record(self, agent_deps):
        evaluate = make_evaluate_node(
            prompt_registry=agent_deps.prompt_registry,
            llm_registry=agent_deps.llm_registry,
            heat_map=agent_deps.heat_map,
        )
        records = [_make_record(row=0, col=0), _make_record(row=0, col=1)]
        state = _make_state(collated_records=records)
        result = evaluate(state)
        assert len(result["risk_assessments"]) == 2
        for risk in result["risk_assessments"]:
            assert isinstance(risk, CollatedRecordRisk)
            assert 0 <= risk.risk_score <= 10
            assert 0 <= risk.confidence <= 4

    def test_stub_positions_match_records(self, agent_deps):
        evaluate = make_evaluate_node(
            prompt_registry=agent_deps.prompt_registry,
            llm_registry=agent_deps.llm_registry,
            heat_map=agent_deps.heat_map,
        )
        state = _make_state(collated_records=[_make_record(row=3, col=7)])
        result = evaluate(state)
        risk = result["risk_assessments"][0]
        assert risk.position.row == 3
        assert risk.position.col == 7


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
    def test_sets_completed_status(self):
        report_risk = make_report_risk_node(store=None)
        state = _make_state()
        result = report_risk(state)
        assert result["status"] == StatusValue.COMPLETED

    def test_no_store_does_not_raise(self):
        report_risk = make_report_risk_node(store=None)
        state = _make_state(risk_assessments=[])
        result = report_risk(state)
        assert result["status"] == StatusValue.COMPLETED

    def test_writes_to_store_when_provided(self):
        store = InMemoryStore()
        report_risk = make_report_risk_node(store=store)
        assessment = CollatedRecordRisk(
            position=GridPosition(row=1, col=2),
            risk_score=7,
            confidence=3.0,
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

    def test_empty_assessments_writes_nothing_to_store(self):
        store = InMemoryStore()
        report_risk = make_report_risk_node(store=store)
        state = _make_state(cluster_id="cluster-north", risk_assessments=[])
        report_risk(state)
        items = store.search(("risk_assessments", "cluster-north"))
        assert len(items) == 0

    def test_multiple_assessments_stored_by_position(self):
        store = InMemoryStore()
        report_risk = make_report_risk_node(store=store)
        assessments = [
            CollatedRecordRisk(
                position=GridPosition(row=r, col=c),
                risk_score=5,
                confidence=2.0,
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

    def test_invoke_with_records_produces_risk_assessments(self, agent_deps):
        graph = build_cluster_agent_graph(agent_deps=agent_deps)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test-graph-1",
            collated_records=[_make_record()],
        )
        result = graph.invoke(state)
        assert result["status"] == StatusValue.COMPLETED
        assert len(result["risk_assessments"]) == 1

    def test_invoke_empty_records_completes_cleanly(self, agent_deps):
        graph = build_cluster_agent_graph(agent_deps=agent_deps)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test-empty",
        )
        result = graph.invoke(state)
        assert result["status"] == StatusValue.COMPLETED
        assert result["risk_assessments"] == []

    def test_invoke_with_store_persists_assessments(self, agent_deps):
        store = InMemoryStore()
        deps = AgentDependencies(
            llm_registry=agent_deps.llm_registry,
            prompt_registry=agent_deps.prompt_registry,
            store=store,
            heat_map=agent_deps.heat_map,
        )
        graph = build_cluster_agent_graph(agent_deps=deps)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test-store",
            collated_records=[_make_record(row=2, col=3)],
        )
        graph.invoke(state)
        items = store.search(("risk_assessments", "cluster-north"))
        assert len(items) == 1

    def test_invoke_multi_record_produces_one_risk_each(self, agent_deps):
        graph = build_cluster_agent_graph(agent_deps=agent_deps)
        records = [_make_record(row=i, col=0) for i in range(4)]
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test-multi",
            collated_records=records,
        )
        result = graph.invoke(state)
        assert len(result["risk_assessments"]) == 4
