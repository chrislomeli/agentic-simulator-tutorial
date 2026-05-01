"""Tests for ogar.transport.topics — topic names and helpers."""

import pytest

from transport import (
    sensor_topic,
    all_sensor_topic_pattern,
    EVENTS_ANOMALY,
    AGENTS_DECISIONS,
    COMMANDS_ACTUATORS,
    RESULTS_ACTUATORS,
)


class TestStaticTopics:
    def test_events_anomaly(self):
        assert EVENTS_ANOMALY == "events.anomaly"

    def test_agents_decisions(self):
        assert AGENTS_DECISIONS == "agents.decisions"

    def test_commands_actuators(self):
        assert COMMANDS_ACTUATORS == "commands.actuators"

    def test_results_actuators(self):
        assert RESULTS_ACTUATORS == "results.actuators"


class TestSensorTopic:
    def test_builds_topic_name(self):
        assert sensor_topic("cluster-north") == "sensors.raw.cluster-north"

    def test_different_clusters(self):
        assert sensor_topic("alpha") == "sensors.raw.alpha"
        assert sensor_topic("beta") == "sensors.raw.beta"

    def test_empty_cluster_raises(self):
        with pytest.raises(ValueError):
            sensor_topic("")


class TestAllSensorTopicPattern:
    def test_returns_regex_pattern(self):
        pattern = all_sensor_topic_pattern()
        assert pattern == r"sensors\.raw\..*"
