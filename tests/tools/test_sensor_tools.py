"""Tests for ogar.tools.sensor_tools — tools the LLM calls during classification."""

from tools.sensor_tools import (
    get_recent_readings,
    get_sensor_summary,
    check_threshold,
    get_cluster_status,
    set_tool_state,
    clear_tool_state,
    SENSOR_TOOLS,
)
from transport import SensorEvent


def _make_event(
    source_id: str = "temp-A1",
    source_type: str = "temperature",
    cluster_id: str = "cluster-north",
    payload: dict = None,
    confidence: float = 0.95,
    sim_tick: int = 0,
) -> SensorEvent:
    return SensorEvent.create(
        source_id=source_id,
        source_type=source_type,
        cluster_id=cluster_id,
        payload=payload or {"celsius": 42.0},
        confidence=confidence,
        sim_tick=sim_tick,
    )


def _load_state(events=None, cluster_id="cluster-north"):
    if events is None:
        events = [
            _make_event("temp-A1", "temperature", payload={"celsius": 42.0}, sim_tick=1),
            _make_event("temp-A1", "temperature", payload={"celsius": 44.0}, sim_tick=2),
            _make_event("hum-A1", "humidity", payload={"relative_humidity_pct": 15.0}, sim_tick=1),
            _make_event("smoke-A1", "smoke", payload={"pm25_ugm3": 120.0}, sim_tick=2),
        ]
    set_tool_state(events, cluster_id)
    return events


class TestToolStateManagement:
    def test_set_and_clear(self):
        events = _load_state()
        result = get_cluster_status.invoke({})
        assert result["total_events"] == 4
        clear_tool_state()
        result = get_cluster_status.invoke({})
        assert result["total_events"] == 0

    def test_sensor_tools_list(self):
        assert len(SENSOR_TOOLS) == 4


class TestGetRecentReadings:
    def test_returns_all(self):
        _load_state()
        result = get_recent_readings.invoke({})
        assert len(result) == 4

    def test_filter_by_source_type(self):
        _load_state()
        result = get_recent_readings.invoke({"source_type": "temperature"})
        assert len(result) == 2
        assert all(r["source_type"] == "temperature" for r in result)

    def test_limit(self):
        _load_state()
        result = get_recent_readings.invoke({"limit": 2})
        assert len(result) == 2

    def test_empty_state(self):
        set_tool_state([], "c1")
        result = get_recent_readings.invoke({})
        assert result == []

    def test_payload_included(self):
        _load_state()
        result = get_recent_readings.invoke({"source_type": "temperature", "limit": 1})
        assert "celsius" in result[0]["payload"]


class TestGetSensorSummary:
    def test_groups_by_type(self):
        _load_state()
        result = get_sensor_summary.invoke({})
        assert "temperature" in result
        assert "humidity" in result
        assert "smoke" in result

    def test_count_per_type(self):
        _load_state()
        result = get_sensor_summary.invoke({})
        assert result["temperature"]["count"] == 2
        assert result["humidity"]["count"] == 1

    def test_confidence_stats(self):
        _load_state()
        result = get_sensor_summary.invoke({})
        assert result["temperature"]["min_confidence"] == 0.95
        assert result["temperature"]["avg_confidence"] == 0.95

    def test_empty_state(self):
        set_tool_state([], "c1")
        result = get_sensor_summary.invoke({})
        assert result == {}


class TestCheckThreshold:
    def test_above_breach(self):
        _load_state()
        result = check_threshold.invoke({
            "source_type": "temperature",
            "payload_key": "celsius",
            "threshold": 43.0,
            "direction": "above",
        })
        assert result["breached"] is True
        assert result["breach_count"] == 1
        assert result["max_value"] == 44.0

    def test_no_breach(self):
        _load_state()
        result = check_threshold.invoke({
            "source_type": "temperature",
            "payload_key": "celsius",
            "threshold": 50.0,
            "direction": "above",
        })
        assert result["breached"] is False
        assert result["breach_count"] == 0

    def test_below_breach(self):
        _load_state()
        result = check_threshold.invoke({
            "source_type": "humidity",
            "payload_key": "relative_humidity_pct",
            "threshold": 20.0,
            "direction": "below",
        })
        assert result["breached"] is True
        assert result["breach_count"] == 1

    def test_missing_key(self):
        _load_state()
        result = check_threshold.invoke({
            "source_type": "temperature",
            "payload_key": "nonexistent",
            "threshold": 10.0,
        })
        assert result["breached"] is False
        assert result["total_readings"] == 0

    def test_wrong_source_type(self):
        _load_state()
        result = check_threshold.invoke({
            "source_type": "radar",
            "payload_key": "celsius",
            "threshold": 10.0,
        })
        assert result["total_readings"] == 0


class TestGetClusterStatus:
    def test_basic_status(self):
        _load_state()
        result = get_cluster_status.invoke({})
        assert result["cluster_id"] == "cluster-north"
        assert result["total_events"] == 4
        assert result["unique_sensors"] == 3
        assert set(result["unique_types"]) == {"temperature", "humidity", "smoke"}

    def test_tick_range(self):
        _load_state()
        result = get_cluster_status.invoke({})
        assert result["tick_range"] == [1, 2]

    def test_empty_state(self):
        set_tool_state([], "c1")
        result = get_cluster_status.invoke({})
        assert result["total_events"] == 0
        assert result["tick_range"] == []


class TestClusterGraphStubMode:
    """Verify the cluster agent graph still works in stub mode after refactor."""

    def test_stub_mode_invoke(self, sample_event):
        from agents.cluster.graph import build_cluster_agent_graph

        graph = build_cluster_agent_graph()  # no llm = stub
        result = graph.invoke({
            "cluster_id": "cluster-north",
            "workflow_id": "test",
            "sensor_events": [sample_event],
            "trigger_event": sample_event,
            "messages": [],
            "anomalies": [],
            "status": "idle",
            "error_message": None,
        })
        assert result["status"] == "complete"
        assert len(result["anomalies"]) >= 1
        assert result["anomalies"][0]["anomaly_type"] == "stub_placeholder"

    def test_stub_mode_graph_nodes(self):
        from agents.cluster.graph import build_cluster_agent_graph

        graph = build_cluster_agent_graph()
        node_names = set(graph.get_graph().nodes.keys())
        assert "ingest_events" in node_names
        assert "classify" in node_names
        assert "report_findings" in node_names
        # No LLM-mode nodes.
        assert "tool_node" not in node_names
        assert "parse_findings" not in node_names


class TestClusterGraphLLMMode:
    """Verify the LLM-mode graph compiles and has the right topology."""

    def test_llm_mode_has_tool_node(self):
        from unittest.mock import MagicMock
        from agents.cluster.graph import build_cluster_agent_graph

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        graph = build_cluster_agent_graph(llm=mock_llm)

        node_names = set(graph.get_graph().nodes.keys())
        assert "classify" in node_names
        assert "tool_node" in node_names
        assert "parse_findings" in node_names
        assert "report_findings" in node_names


class TestRouteAfterClassifyLLM:
    """Test the LLM-mode router logic directly."""

    def test_routes_to_tool_node_on_tool_calls(self):
        from langchain_core.messages import AIMessage
        from agents.cluster.graph import route_after_classify_llm

        ai_msg = AIMessage(content="", tool_calls=[{"name": "get_recent_readings", "args": {}, "id": "1"}])
        state = {"status": "processing", "messages": [ai_msg]}
        assert route_after_classify_llm(state) == "tool_node"

    def test_routes_to_parse_on_no_tool_calls(self):
        from langchain_core.messages import AIMessage
        from agents.cluster.graph import route_after_classify_llm

        ai_msg = AIMessage(content='{"anomaly_detected": false}')
        state = {"status": "processing", "messages": [ai_msg]}
        assert route_after_classify_llm(state) == "parse_findings"

    def test_routes_to_end_on_error(self):
        from agents.cluster.graph import route_after_classify_llm

        state = {"status": "error", "messages": []}
        assert route_after_classify_llm(state) == "__end__"


class TestParseLLMFindings:
    """Test the parse_findings node directly."""

    def test_parses_valid_json(self):
        from langchain_core.messages import AIMessage
        from agents.cluster.graph import _parse_llm_findings

        ai_msg = AIMessage(content='{"anomaly_detected": true, "anomaly_type": "threshold_breach", "affected_sensors": ["temp-A1"], "confidence": 0.9, "summary": "High temperature"}')
        state = {
            "cluster_id": "cluster-north",
            "messages": [ai_msg],
            "trigger_event": None,
            "sensor_events": [],
        }
        result = _parse_llm_findings(state)
        assert result["status"] == "complete"
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["anomaly_type"] == "threshold_breach"
        assert result["anomalies"][0]["confidence"] == 0.9

    def test_parses_no_anomaly(self):
        from langchain_core.messages import AIMessage
        from agents.cluster.graph import _parse_llm_findings

        ai_msg = AIMessage(content='{"anomaly_detected": false, "anomaly_type": "none", "affected_sensors": [], "confidence": 0.1, "summary": "Normal"}')
        state = {
            "cluster_id": "c1",
            "messages": [ai_msg],
            "trigger_event": None,
            "sensor_events": [],
        }
        result = _parse_llm_findings(state)
        assert result["status"] == "complete"
        assert len(result["anomalies"]) == 0

    def test_handles_markdown_fence(self):
        from langchain_core.messages import AIMessage
        from agents.cluster.graph import _parse_llm_findings

        content = '```json\n{"anomaly_detected": true, "anomaly_type": "sensor_fault", "affected_sensors": ["s1"], "confidence": 0.8, "summary": "Fault"}\n```'
        ai_msg = AIMessage(content=content)
        state = {
            "cluster_id": "c1",
            "messages": [ai_msg],
            "trigger_event": None,
            "sensor_events": [],
        }
        result = _parse_llm_findings(state)
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["anomaly_type"] == "sensor_fault"

    def test_handles_unparseable_response(self):
        from langchain_core.messages import AIMessage
        from agents.cluster.graph import _parse_llm_findings

        ai_msg = AIMessage(content="I think there might be an anomaly but I'm not sure.")
        state = {
            "cluster_id": "c1",
            "messages": [ai_msg],
            "trigger_event": None,
            "sensor_events": [],
        }
        result = _parse_llm_findings(state)
        assert result["status"] == "complete"
        # Falls back to a finding with llm_parse_fallback type.
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["anomaly_type"] == "llm_parse_fallback"

    def test_no_ai_message(self):
        from agents.cluster.graph import _parse_llm_findings

        state = {
            "cluster_id": "c1",
            "messages": [],
            "trigger_event": None,
            "sensor_events": [],
        }
        result = _parse_llm_findings(state)
        assert result["anomalies"] == []
