"""Tests for ogar.tools.supervisor_tools — state management and all four tools."""

import pytest

from tools.supervisor_tools import (
    _state,
    set_supervisor_tool_state,
    clear_supervisor_tool_state,
    get_all_findings,
    get_findings_by_cluster,
    get_finding_summary,
    check_cross_cluster,
    SUPERVISOR_TOOLS,
)


def _make_finding(
    finding_id: str = "f1",
    cluster_id: str = "cluster-north",
    anomaly_type: str = "temperature_spike",
    confidence: float = 0.8,
) -> dict:
    return {
        "finding_id": finding_id,
        "cluster_id": cluster_id,
        "anomaly_type": anomaly_type,
        "affected_sensors": ["s1", "s2"],
        "confidence": confidence,
        "summary": f"Test finding {finding_id}",
        "raw_context": {},
    }


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset tool state before and after each test."""
    clear_supervisor_tool_state()
    yield
    clear_supervisor_tool_state()


# ── State management ────────────────────────────────────────────────────────

class TestSupervisorToolState:
    def test_set_state(self):
        findings = [_make_finding()]
        set_supervisor_tool_state(findings, ["cluster-north"])
        assert len(_state.findings) == 1
        assert _state.active_cluster_ids == ["cluster-north"]

    def test_clear_state(self):
        set_supervisor_tool_state([_make_finding()], ["c1"])
        clear_supervisor_tool_state()
        assert _state.findings == []
        assert _state.active_cluster_ids == []

    def test_set_copies_lists(self):
        findings = [_make_finding()]
        set_supervisor_tool_state(findings, ["c1"])
        findings.append(_make_finding("f2"))
        assert len(_state.findings) == 1  # original not mutated


# ── get_all_findings ────────────────────────────────────────────────────────

class TestGetAllFindings:
    def test_returns_all(self):
        set_supervisor_tool_state(
            [_make_finding("f1"), _make_finding("f2")],
            ["c1"],
        )
        result = get_all_findings.invoke({"limit": 50})
        assert len(result) == 2
        assert result[0]["finding_id"] == "f1"

    def test_respects_limit(self):
        set_supervisor_tool_state(
            [_make_finding(f"f{i}") for i in range(10)],
            ["c1"],
        )
        result = get_all_findings.invoke({"limit": 3})
        assert len(result) == 3

    def test_empty_findings(self):
        result = get_all_findings.invoke({"limit": 50})
        assert result == []

    def test_returns_expected_keys(self):
        set_supervisor_tool_state([_make_finding()], ["c1"])
        result = get_all_findings.invoke({"limit": 50})
        keys = set(result[0].keys())
        assert keys == {
            "finding_id", "cluster_id", "anomaly_type",
            "affected_sensors", "confidence", "summary",
        }


# ── get_findings_by_cluster ────────────────────────────────────────────────

class TestGetFindingsByCluster:
    def test_filters_by_cluster(self):
        set_supervisor_tool_state(
            [
                _make_finding("f1", cluster_id="cluster-north"),
                _make_finding("f2", cluster_id="cluster-south"),
                _make_finding("f3", cluster_id="cluster-north"),
            ],
            ["cluster-north", "cluster-south"],
        )
        result = get_findings_by_cluster.invoke({"cluster_id": "cluster-north"})
        assert len(result) == 2
        assert all(r["cluster_id"] == "cluster-north" for r in result)

    def test_no_match(self):
        set_supervisor_tool_state([_make_finding()], ["cluster-north"])
        result = get_findings_by_cluster.invoke({"cluster_id": "cluster-east"})
        assert result == []


# ── get_finding_summary ─────────────────────────────────────────────────────

class TestGetFindingSummary:
    def test_empty_findings(self):
        result = get_finding_summary.invoke({})
        assert result["total_findings"] == 0
        assert result["avg_confidence"] == 0.0

    def test_aggregates_correctly(self):
        set_supervisor_tool_state(
            [
                _make_finding("f1", cluster_id="c1", anomaly_type="temp", confidence=0.8),
                _make_finding("f2", cluster_id="c2", anomaly_type="temp", confidence=0.6),
                _make_finding("f3", cluster_id="c1", anomaly_type="smoke", confidence=0.9),
            ],
            ["c1", "c2"],
        )
        result = get_finding_summary.invoke({})
        assert result["total_findings"] == 3
        assert result["by_cluster"] == {"c1": 2, "c2": 1}
        assert result["by_type"] == {"temp": 2, "smoke": 1}
        assert result["avg_confidence"] == pytest.approx(0.767, abs=0.001)
        assert result["high_confidence_count"] == 2  # 0.8 and 0.9
        assert set(result["affected_clusters"]) == {"c1", "c2"}


# ── check_cross_cluster ────────────────────────────────────────────────────

class TestCheckCrossCluster:
    def test_no_correlation(self):
        set_supervisor_tool_state(
            [
                _make_finding("f1", cluster_id="c1", anomaly_type="temp"),
                _make_finding("f2", cluster_id="c1", anomaly_type="smoke"),
            ],
            ["c1"],
        )
        result = check_cross_cluster.invoke({})
        assert result["correlated"] is False
        assert result["correlations"] == []

    def test_detects_correlation(self):
        set_supervisor_tool_state(
            [
                _make_finding("f1", cluster_id="c1", anomaly_type="temperature_spike"),
                _make_finding("f2", cluster_id="c2", anomaly_type="temperature_spike"),
                _make_finding("f3", cluster_id="c1", anomaly_type="smoke"),
            ],
            ["c1", "c2"],
        )
        result = check_cross_cluster.invoke({})
        assert result["correlated"] is True
        assert len(result["correlations"]) == 1
        corr = result["correlations"][0]
        assert corr["anomaly_type"] == "temperature_spike"
        assert set(corr["clusters"]) == {"c1", "c2"}
        assert corr["cluster_count"] == 2

    def test_filter_by_type(self):
        set_supervisor_tool_state(
            [
                _make_finding("f1", cluster_id="c1", anomaly_type="temp"),
                _make_finding("f2", cluster_id="c2", anomaly_type="temp"),
                _make_finding("f3", cluster_id="c1", anomaly_type="smoke"),
                _make_finding("f4", cluster_id="c2", anomaly_type="smoke"),
            ],
            ["c1", "c2"],
        )
        result = check_cross_cluster.invoke({"anomaly_type": "smoke"})
        assert result["correlated"] is True
        assert len(result["correlations"]) == 1
        assert result["correlations"][0]["anomaly_type"] == "smoke"

    def test_empty_findings(self):
        result = check_cross_cluster.invoke({})
        assert result["correlated"] is False
        assert result["total_clusters_checked"] == 0

    def test_multiple_correlations(self):
        set_supervisor_tool_state(
            [
                _make_finding("f1", cluster_id="c1", anomaly_type="temp"),
                _make_finding("f2", cluster_id="c2", anomaly_type="temp"),
                _make_finding("f3", cluster_id="c1", anomaly_type="smoke"),
                _make_finding("f4", cluster_id="c2", anomaly_type="smoke"),
                _make_finding("f5", cluster_id="c3", anomaly_type="smoke"),
            ],
            ["c1", "c2", "c3"],
        )
        result = check_cross_cluster.invoke({})
        assert result["correlated"] is True
        assert len(result["correlations"]) == 2


# ── Tool list ───────────────────────────────────────────────────────────────

class TestToolList:
    def test_tool_count(self):
        assert len(SUPERVISOR_TOOLS) == 4

    def test_tool_names(self):
        names = {t.name for t in SUPERVISOR_TOOLS}
        assert names == {
            "get_all_findings",
            "get_findings_by_cluster",
            "get_finding_summary",
            "check_cross_cluster",
        }
