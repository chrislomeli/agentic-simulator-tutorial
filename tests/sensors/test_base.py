"""Tests for ogar.sensors.base — SensorBase, FailureMode, emit."""

from sensors.base import SensorBase, FailureMode
from transport import SensorEvent


# ── Concrete test sensor ─────────────────────────────────────────────────────

class _StubSensor(SensorBase):
    """Minimal sensor for testing the base class."""
    source_type = "stub"

    def __init__(self, reading=None, **kwargs):
        super().__init__(**kwargs)
        self._reading = reading or {"value": 42}

    def read(self):
        return dict(self._reading)


# ── FailureMode enum ─────────────────────────────────────────────────────────

class TestFailureMode:
    def test_values(self):
        assert FailureMode.NORMAL == "NORMAL"
        assert FailureMode.STUCK == "STUCK"
        assert FailureMode.DROPOUT == "DROPOUT"
        assert FailureMode.DRIFT == "DRIFT"
        assert FailureMode.SPIKE == "SPIKE"

    def test_count(self):
        assert len(FailureMode) == 5


# ── SensorBase construction ──────────────────────────────────────────────────

class TestSensorBaseInit:
    def test_required_fields(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        assert s.source_id == "s1"
        assert s.cluster_id == "c1"
        assert s.metadata == {}

    def test_metadata(self):
        s = _StubSensor(source_id="s1", cluster_id="c1", metadata={"loc": "ridge"})
        assert s.metadata == {"loc": "ridge"}

    def test_initial_state(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        assert s._tick == 0
        assert s._failure_mode == FailureMode.NORMAL

    def test_repr(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        r = repr(s)
        assert "_StubSensor" in r
        assert "s1" in r
        assert "c1" in r


# ── emit() normal mode ───────────────────────────────────────────────────────

class TestEmitNormal:
    def test_returns_sensor_event(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        event = s.emit()
        assert isinstance(event, SensorEvent)

    def test_event_fields(self):
        s = _StubSensor(source_id="s1", cluster_id="c1", metadata={"hw": "v1"})
        event = s.emit()
        assert event.source_id == "s1"
        assert event.source_type == "stub"
        assert event.cluster_id == "c1"
        assert event.payload == {"value": 42}
        assert event.metadata == {"hw": "v1"}

    def test_tick_increments(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        e0 = s.emit()
        e1 = s.emit()
        assert e0.sim_tick == 0
        assert e1.sim_tick == 1

    def test_confidence_is_1_in_normal(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        event = s.emit()
        assert event.confidence == 1.0


# ── emit() DROPOUT mode ─────────────────────────────────────────────────────

class TestEmitDropout:
    def test_returns_none(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.DROPOUT)
        assert s.emit() is None

    def test_tick_still_increments(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.DROPOUT)
        s.emit()
        s.emit()
        s.set_failure_mode(FailureMode.NORMAL)
        event = s.emit()
        assert event.sim_tick == 2


# ── emit() STUCK mode ───────────────────────────────────────────────────────

class TestEmitStuck:
    def test_returns_same_payload(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.STUCK)
        e1 = s.emit()
        e2 = s.emit()
        assert e1.payload == e2.payload

    def test_confidence_is_low(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.STUCK)
        event = s.emit()
        assert event.confidence == 0.3

    def test_recovery_clears_stuck_cache(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.STUCK)
        s.emit()
        s.set_failure_mode(FailureMode.NORMAL)
        assert s._stuck_payload is None


# ── health() ─────────────────────────────────────────────────────────────────

class TestHealth:
    def test_normal_health(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        assert s.health() == 1.0

    def test_drift_health(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.DRIFT)
        assert s.health() == 0.7

    def test_stuck_health(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.STUCK)
        assert s.health() == 0.3

    def test_spike_health(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.SPIKE)
        assert s.health() == 0.5

    def test_dropout_health(self):
        s = _StubSensor(source_id="s1", cluster_id="c1")
        s.set_failure_mode(FailureMode.DROPOUT)
        assert s.health() == 0.0
