"""Tests for ogar.transport.schemas — SensorEvent envelope."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from transport import SensorEvent


class TestSensorEventCreate:
    def test_create_sets_event_id(self):
        event = SensorEvent.create(
            source_id="s1", source_type="temp", cluster_id="c1", payload={"v": 1}
        )
        assert isinstance(event.event_id, str)
        assert len(event.event_id) > 0

    def test_create_unique_ids(self):
        e1 = SensorEvent.create(source_id="s1", source_type="t", cluster_id="c1", payload={})
        e2 = SensorEvent.create(source_id="s1", source_type="t", cluster_id="c1", payload={})
        assert e1.event_id != e2.event_id

    def test_create_sets_timestamp(self):
        event = SensorEvent.create(
            source_id="s1", source_type="t", cluster_id="c1", payload={}
        )
        assert isinstance(event.timestamp, datetime)
        assert event.timestamp.tzinfo is not None

    def test_create_passes_fields(self):
        event = SensorEvent.create(
            source_id="temp-A1",
            source_type="temperature",
            cluster_id="cluster-north",
            payload={"celsius": 42.1},
            confidence=0.85,
            sim_tick=7,
            metadata={"hw": "v2"},
        )
        assert event.source_id == "temp-A1"
        assert event.source_type == "temperature"
        assert event.cluster_id == "cluster-north"
        assert event.payload == {"celsius": 42.1}
        assert event.confidence == 0.85
        assert event.sim_tick == 7
        assert event.metadata == {"hw": "v2"}

    def test_default_confidence(self):
        event = SensorEvent.create(
            source_id="s1", source_type="t", cluster_id="c1", payload={}
        )
        assert event.confidence == 1.0

    def test_default_sim_tick(self):
        event = SensorEvent.create(
            source_id="s1", source_type="t", cluster_id="c1", payload={}
        )
        assert event.sim_tick == 0

    def test_default_metadata_empty(self):
        event = SensorEvent.create(
            source_id="s1", source_type="t", cluster_id="c1", payload={}
        )
        assert event.metadata == {}


class TestSensorEventConfidence:
    def test_confidence_rejects_above_1(self):
        with pytest.raises(ValidationError):
            SensorEvent(
                event_id="x",
                source_id="s1",
                source_type="t",
                cluster_id="c1",
                timestamp=datetime.now(timezone.utc),
                confidence=1.5,
                payload={},
            )

    def test_confidence_rejects_below_0(self):
        with pytest.raises(ValidationError):
            SensorEvent(
                event_id="x",
                source_id="s1",
                source_type="t",
                cluster_id="c1",
                timestamp=datetime.now(timezone.utc),
                confidence=-0.5,
                payload={},
            )

    def test_confidence_at_bounds(self):
        e0 = SensorEvent(
            event_id="a", source_id="s", source_type="t", cluster_id="c",
            timestamp=datetime.now(timezone.utc), confidence=0.0, payload={},
        )
        e1 = SensorEvent(
            event_id="b", source_id="s", source_type="t", cluster_id="c",
            timestamp=datetime.now(timezone.utc), confidence=1.0, payload={},
        )
        assert e0.confidence == 0.0
        assert e1.confidence == 1.0


class TestSensorEventSerialization:
    def test_model_dump(self, sample_event):
        d = sample_event.model_dump()
        assert d["source_id"] == "temp-A1"
        assert d["source_type"] == "temperature"
        assert "payload" in d
        assert "event_id" in d
