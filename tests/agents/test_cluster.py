"""Tests for ogar.agents.cluster — state reducers, node functions, graph."""

from agents.cluster.state import (
    append_events,
    AnomalyFinding,
)
from langgraph.store.memory import InMemoryStore

from agents.cluster.graph import (
    ingest_events,
    classify,
    report_findings,
    route_after_classify,
    build_cluster_agent_graph,
)
from transport import SensorEvent


def _make_event(source_id: str = "s1") -> SensorEvent:
    return SensorEvent.create(
        source_id=source_id, source_type="temp", cluster_id="c1", payload={"v": 1}
    )


def _make_state(**overrides) -> dict:
    """Build a minimal ClusterAgentState-shaped dict."""
    base = {
        "cluster_id": "cluster-north",
        "workflow_id": "test-run-1",
        "sensor_events": [],
        "trigger_event": _make_event("trigger"),
        "messages": [],
        "anomalies": [],
        "status": "idle",
        "error_message": None,
    }
    base.update(overrides)
    return base


# ── Reducer tests ────────────────────────────────────────────────────────────

class TestAppendEventsReducer:
    def test_appends_new_events(self):
        existing = [_make_event("a")]
        new = [_make_event("b")]
        result = append_events(existing, new)
        assert len(result) == 2
        assert result[0].source_id == "a"
        assert result[1].source_id == "b"

    def test_caps_at_max_window(self):
        existing = [_make_event(f"e{i}") for i in range(50)]
        new = [_make_event("new")]
        result = append_events(existing, new)
        assert len(result) == 50
        assert result[-1].source_id == "new"
        assert result[0].source_id == "e1"

    def test_empty_lists(self):
        assert append_events([], []) == []

    def test_empty_existing(self):
        new = [_make_event("x")]
        result = append_events([], new)
        assert len(result) == 1


# ── AnomalyFinding ──────────────────────────────────────────────────────────

class TestAnomalyFinding:
    def test_can_create(self):
        f: AnomalyFinding = {
            "finding_id": "f1",
            "cluster_id": "c1",
            "anomaly_type": "threshold_breach",
            "affected_sensors": ["s1", "s2"],
            "confidence": 0.8,
            "summary": "Temperature spike",
            "raw_context": {"max_temp": 95.0},
        }
        assert f["finding_id"] == "f1"
        assert f["confidence"] == 0.8


# ── Node function tests ─────────────────────────────────────────────────────

class TestIngestEvents:
    def test_sets_processing(self):
        state = _make_state()
        result = ingest_events(state)
        assert result["status"] == "processing"
        assert result["error_message"] is None

    def test_handles_no_trigger(self):
        state = _make_state(trigger_event=None)
        result = ingest_events(state)
        assert result["status"] == "processing"


class TestClassify:
    def test_produces_stub_finding(self):
        state = _make_state()
        result = classify(state)
        assert result["status"] == "complete"
        assert len(result["anomalies"]) == 1
        finding = result["anomalies"][0]
        assert finding["anomaly_type"] == "stub_placeholder"
        assert finding["cluster_id"] == "cluster-north"

    def test_finding_references_trigger(self):
        trigger = _make_event("trigger-sensor")
        state = _make_state(trigger_event=trigger)
        result = classify(state)
        finding = result["anomalies"][0]
        assert "trigger-sensor" in finding["affected_sensors"]

    def test_no_trigger_still_works(self):
        state = _make_state(trigger_event=None)
        result = classify(state)
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["affected_sensors"] == []


class TestReportFindings:
    def test_returns_empty_update(self):
        state = _make_state(anomalies=[{
            "finding_id": "f1",
            "cluster_id": "c1",
            "anomaly_type": "test",
            "affected_sensors": [],
            "confidence": 0.5,
            "summary": "test",
            "raw_context": {},
        }])
        result = report_findings(state)
        assert result == {}

    def test_writes_findings_to_store(self):
        store = InMemoryStore()
        finding = {
            "finding_id": "f-store-1",
            "cluster_id": "cluster-north",
            "anomaly_type": "threshold_breach",
            "affected_sensors": ["temp-1"],
            "confidence": 0.8,
            "summary": "Temperature spike",
            "raw_context": {},
        }
        state = _make_state(cluster_id="cluster-north", anomalies=[finding])
        report_findings(state, store=store)

        items = store.search(("incidents", "cluster-north"))
        assert len(items) == 1
        assert items[0].key == "f-store-1"
        assert items[0].value["anomaly_type"] == "threshold_breach"

    def test_no_store_is_safe(self):
        # store=None should not raise
        state = _make_state(anomalies=[{
            "finding_id": "f2", "cluster_id": "c1",
            "anomaly_type": "test", "affected_sensors": [],
            "confidence": 0.5, "summary": "test", "raw_context": {},
        }])
        result = report_findings(state, store=None)
        assert result == {}

    def test_empty_anomalies_writes_nothing(self):
        store = InMemoryStore()
        state = _make_state(cluster_id="cluster-north", anomalies=[])
        report_findings(state, store=store)
        items = store.search(("incidents", "cluster-north"))
        assert len(items) == 0


class TestRouteAfterClassify:
    def test_routes_to_report_on_complete(self):
        state = _make_state(status="complete")
        assert route_after_classify(state) == "report_findings"

    def test_routes_to_end_on_error(self):
        state = _make_state(status="error", error_message="boom")
        assert route_after_classify(state) == "__end__"


# ── Graph integration tests ──────────────────────────────────────────────────

class TestClusterAgentGraph:
    def test_build_returns_compiled_graph(self):
        graph = build_cluster_agent_graph()
        assert graph is not None
        assert hasattr(graph, "invoke")

    def test_invoke_happy_path(self):
        graph = build_cluster_agent_graph()
        state = _make_state()
        result = graph.invoke(state)
        assert result["status"] == "complete"
        assert len(result["anomalies"]) >= 1

    def test_invoke_with_sensor_events(self):
        graph = build_cluster_agent_graph()
        events = [_make_event(f"s{i}") for i in range(3)]
        state = _make_state(sensor_events=events)
        result = graph.invoke(state)
        assert result["status"] == "complete"
        assert len(result["sensor_events"]) == 3

    def test_invoke_no_trigger(self):
        graph = build_cluster_agent_graph()
        state = _make_state(trigger_event=None)
        result = graph.invoke(state)
        assert result["status"] == "complete"

    def test_invoke_with_store_writes_findings(self):
        store = InMemoryStore()
        graph = build_cluster_agent_graph(store=store)
        state = _make_state(cluster_id="cluster-north")
        graph.invoke(state)

        # Stub classify always produces one finding — it should land in the store
        items = store.search(("incidents", "cluster-north"))
        assert len(items) == 1
