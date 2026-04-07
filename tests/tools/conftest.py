"""Shared fixtures for tools tests."""

import pytest

from transport import SensorEvent


@pytest.fixture
def sample_event() -> SensorEvent:
    """A pre-built SensorEvent for transport/agent tests."""
    return SensorEvent.create(
        source_id="temp-A1",
        source_type="temperature",
        cluster_id="cluster-north",
        payload={"celsius": 42.1},
        confidence=0.95,
    )
