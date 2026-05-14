"""Tests for agents.supervisor — state reducers, node functions, graph."""

import pytest
from langgraph.graph import END
from langgraph.store.memory import InMemoryStore

from agents.cluster.graph import build_cluster_agent_graph
from agents.cluster.state import ClusterAgentState
from agents.commons.agent_dependencies import AgentDependencies
from agents.commons.schemas import (
    CellReadings,
    CollatedRecordRisk,
    GridPosition,
)
from agents.commons.state_types import StatusValue
from agents.supervisor.graph import build_supervisor_graph
from langgraph.graph.state import CompiledStateGraph
from agents.supervisor.nodes import (
    assess_situation,
    decide_actions,
    fan_out_to_clusters,
    make_dispatch_commands,
    make_run_cluster_agent,
    route_after_assess,
    route_after_decide,
    LOGISTICS_RISK_THRESHOLD,
)
from agents.supervisor.state import (
    ActuatorCommand,
    SupervisorGraph,
    SupervisorState,
    max_cluster_score,
    merge_cluster_findings, RiskScore,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_readings(cluster_id: str = "cluster-north", row: int = 0, col: int = 0) -> CellReadings:
    return CellReadings(
        cluster_id=cluster_id,
        position=GridPosition(row=row, col=col),
        metrics=[],
    )


def _make_risk(row: int = 0, col: int = 0, score: int = 5) -> CollatedRecordRisk:
    return CollatedRecordRisk(
        position=GridPosition(row=row, col=col),
        risk_score=score,
        confidence=3,
        confidence_rationale="test",
        contributing_factors=["test factor"],
    )


def _make_state(**overrides) -> SupervisorState:
    base = SupervisorState()
    return base.model_copy(update=overrides) if overrides else base


# ── max_cluster_score reducer tests ──────────────────────────────────────────

class TestMaxClusterScoreReducer:
    def test_adds_new_cluster(self):
        result = max_cluster_score({}, {"cluster-north": RiskScore(risk_score=7, confidence=4)})
        assert result == {"cluster-north": RiskScore(risk_score=7, confidence=4)}

    def test_keeps_higher_score(self):
        result = max_cluster_score({"cluster-north": RiskScore(risk_score=5, confidence=4)}, {"cluster-north": RiskScore(risk_score=8, confidence=4)})
        assert result["cluster-north"].risk_score == 8

    def test_keeps_existing_if_higher(self):
        result = max_cluster_score({"cluster-north": RiskScore(risk_score=9, confidence=4)}, {"cluster-north": RiskScore(risk_score=3, confidence=4)})
        assert result["cluster-north"].risk_score == 9

    def test_equal_scores_preserved(self):
        result = max_cluster_score({"cluster-north": RiskScore(risk_score=5, confidence=4)}, {"cluster-north": RiskScore(risk_score=5, confidence=4)})
        assert result["cluster-north"].risk_score == 5

    def test_merges_disjoint_clusters(self):
        result = max_cluster_score({"cluster-north": RiskScore(risk_score=5, confidence=4)}, {"cluster-south": RiskScore(risk_score=7, confidence=4)})
        assert result == {"cluster-north": RiskScore(risk_score=5, confidence=4), "cluster-south": RiskScore(risk_score=7, confidence=4)}

    def test_empty_incoming(self):
        assert max_cluster_score({"cluster-north": RiskScore(risk_score=4, confidence=4)}, {}) == {"cluster-north": RiskScore(risk_score=4, confidence=4)}

    def test_empty_existing(self):
        assert max_cluster_score({}, {"cluster-north": RiskScore(risk_score=5, confidence=4)}) == {"cluster-north": RiskScore(risk_score=5, confidence=4)}

    def test_both_empty(self):
        assert max_cluster_score({}, {}) == {}


# ── merge_cluster_findings reducer tests ─────────────────────────────────────

class TestMergeClusterFindingsReducer:
    def test_adds_new_cluster(self):
        risk = _make_risk(score=5)
        result = merge_cluster_findings({}, {"cluster-north": [risk]})
        assert "cluster-north" in result
        assert len(result["cluster-north"]) == 1

    def test_overwrites_existing_cluster(self):
        """Each cluster is fanned-out exactly once per tick — last write wins."""
        old = _make_risk(score=3)
        new = _make_risk(score=7)
        result = merge_cluster_findings(
            {"cluster-north": [old]}, {"cluster-north": [new]}
        )
        assert result["cluster-north"][0].risk_score == 7

    def test_merges_disjoint_clusters(self):
        result = merge_cluster_findings(
            {"cluster-north": [_make_risk()]},
            {"cluster-south": [_make_risk()]},
        )
        assert "cluster-north" in result
        assert "cluster-south" in result

    def test_empty_list_value_allowed(self):
        result = merge_cluster_findings({}, {"cluster-north": []})
        assert result["cluster-north"] == []


# ── fan_out_to_clusters tests ─────────────────────────────────────────────────

class TestFanOutToClusters:
    def test_returns_one_send_per_cluster(self):
        state = _make_state(clusters={
            "cluster-north": [_make_readings("cluster-north")],
            "cluster-south": [_make_readings("cluster-south")],
        })
        sends = fan_out_to_clusters(state)
        assert len(sends) == 2

    def test_empty_clusters_returns_empty(self):
        state = _make_state(clusters={})
        sends = fan_out_to_clusters(state)
        assert sends == []

    def test_send_targets_run_cluster_agent(self):
        state = _make_state(clusters={"cluster-north": [_make_readings()]})
        sends = fan_out_to_clusters(state)
        assert sends[0].node == "run_cluster_agent"

    def test_send_payload_is_cluster_agent_state_with_readings(self):
        readings = [_make_readings(row=0), _make_readings(row=1)]
        state = _make_state(clusters={"cluster-north": readings})
        sends = fan_out_to_clusters(state)
        payload = sends[0].arg
        assert isinstance(payload, ClusterAgentState)
        assert payload.cluster_id == "cluster-north"
        assert len(payload.readings) == 2


# ── make_run_cluster_agent tests ──────────────────────────────────────────────


class TestRunClusterAgent:
    async def test_returns_cluster_findings_and_score(self, agent_deps):
        cluster_graph = build_cluster_agent_graph(agent_deps=agent_deps)
        run_node = make_run_cluster_agent(cluster_graph)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test",
            readings=[_make_readings()],
        )
        result = await run_node(state)
        assert "cluster_findings" in result
        assert "cluster_score" in result
        assert "cluster-north" in result["cluster_findings"]
        assert "cluster-north" in result["cluster_score"]
        assert isinstance(result["cluster_score"]["cluster-north"], RiskScore)

    async def test_score_is_within_valid_range(self, agent_deps):
        cluster_graph = build_cluster_agent_graph(agent_deps=agent_deps)
        run_node = make_run_cluster_agent(cluster_graph)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test",
            readings=[_make_readings()],
        )
        result = await run_node(state)
        score = result["cluster_score"]["cluster-north"].risk_score
        assert 0 <= score <= 10

    async def test_empty_readings_produces_score_zero(self, agent_deps):
        """Guards against ValueError from max() on empty assessments."""
        cluster_graph = build_cluster_agent_graph(agent_deps=agent_deps)
        run_node = make_run_cluster_agent(cluster_graph)
        state = ClusterAgentState(
            cluster_id="cluster-north",
            workflow_id="test",
            readings=[],
        )
        result = await run_node(state)
        assert result["cluster_score"]["cluster-north"].risk_score == 0
        assert result["cluster_findings"]["cluster-north"] == []


# ── assess_situation tests ────────────────────────────────────────────────────

class TestAssessSituation:
    def test_produces_situation_summary(self):
        state = _make_state(
            clusters={"cluster-north": []},
            cluster_findings={"cluster-north": [_make_risk()]},
        )
        result = assess_situation(state)
        assert result["situation_summary"] is not None
        assert len(result["situation_summary"]) > 0

    def test_summary_contains_stub_marker(self):
        state = _make_state(clusters={"cluster-north": []})
        result = assess_situation(state)
        assert "[STUB]" in result["situation_summary"]

    def test_status_is_processing(self):
        state = _make_state()
        result = assess_situation(state)
        assert result["status"] == StatusValue.PROCESSING

    def test_summary_reflects_cluster_count(self):
        state = _make_state(
            clusters={"cluster-north": [], "cluster-south": []},
            cluster_findings={
                "cluster-north": [_make_risk()],
                "cluster-south": [_make_risk()],
            },
        )
        result = assess_situation(state)
        assert "2" in result["situation_summary"]


# ── decide_actions tests ──────────────────────────────────────────────────────

class TestDecideActions:
    def test_returns_empty_command_list(self):
        state = _make_state()
        result = decide_actions(state)
        assert result["pending_commands"] == []

    def test_status_is_processing(self):
        state = _make_state()
        result = decide_actions(state)
        assert result["status"] == StatusValue.PROCESSING


# ── make_dispatch_commands tests ──────────────────────────────────────────────

class TestDispatchCommands:
    def test_sets_completed_status(self):
        dispatch = make_dispatch_commands(store=None)
        state = _make_state()
        result = dispatch(state)
        assert result["status"] == StatusValue.COMPLETED

    def test_handles_empty_commands(self):
        dispatch = make_dispatch_commands(store=None)
        state = _make_state(pending_commands=[])
        result = dispatch(state)
        assert result["status"] == StatusValue.COMPLETED


# ── route_after_assess tests ─────────────────────────────────────────────────


class TestRouteAfterAssess:
    def test_no_scores_skips_logistics(self):
        state = _make_state(cluster_score={})
        assert route_after_assess(state) == "dispatch_commands"

    def test_score_at_threshold_invokes_logistics(self):
        state = _make_state(cluster_score={"c1": RiskScore(risk_score=LOGISTICS_RISK_THRESHOLD, confidence=2)})
        assert route_after_assess(state) == "run_logistics_agent"

    def test_score_above_threshold_invokes_logistics(self):
        state = _make_state(cluster_score={"c1": RiskScore(risk_score=8, confidence=3)})
        assert route_after_assess(state) == "run_logistics_agent"

    def test_score_below_threshold_skips_logistics(self):
        state = _make_state(cluster_score={"c1": RiskScore(risk_score=LOGISTICS_RISK_THRESHOLD - 1, confidence=2)})
        assert route_after_assess(state) == "dispatch_commands"

    def test_uses_max_across_clusters(self):
        """One cluster below threshold, one above — should invoke logistics."""
        state = _make_state(cluster_score={
            "c1": RiskScore(risk_score=2, confidence=1),
            "c2": RiskScore(risk_score=7, confidence=2),
        })
        assert route_after_assess(state) == "run_logistics_agent"

    def test_all_clusters_below_threshold_skips_logistics(self):
        state = _make_state(cluster_score={
            "c1": RiskScore(risk_score=2, confidence=1),
            "c2": RiskScore(risk_score=3, confidence=2),
        })
        assert route_after_assess(state) == "dispatch_commands"


# ── route_after_decide tests ──────────────────────────────────────────────────

class TestRouteAfterDecide:
    def test_routes_to_dispatch_commands_when_processing(self):
        state = _make_state(status=StatusValue.PROCESSING)
        assert route_after_decide(state) == "dispatch_commands"

    def test_routes_to_dispatch_commands_when_idle(self):
        state = _make_state()  # default: IDLE
        assert route_after_decide(state) == "dispatch_commands"

    def test_routes_to_end_on_error(self):
        state = _make_state(status=StatusValue.ERROR)
        assert route_after_decide(state) == END

    def test_routes_to_end_on_completed(self):
        state = _make_state(status=StatusValue.COMPLETED)
        assert route_after_decide(state) == END
