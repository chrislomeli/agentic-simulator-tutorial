"""Tests for the graph entry-point seam: contract, facade, in-process port.

The contract now carries sensor events (not positions): the facade folds
them onto its seed-hydrated world. ``invoke_supervisor_for_trigger`` is
monkeypatched so these assert the facade's own behaviour — fold → readings
→ write seam → invoke — without depending on graph internals.
"""

from __future__ import annotations

from types import SimpleNamespace

from agents.supervisor.state import RiskScore
from runtime.contract import TriggerRequest, TriggerResult
from runtime.facade import GraphFacade
from runtime.graph_client import GraphClient, InProcessGraphClient
from runtime.orchestrator import SupervisorInvocation
from world.transport import SensorEvent


def _event(source_id: str = "s1") -> SensorEvent:
    return SensorEvent.create(
        source_id=source_id,
        source_type="temperature",
        cluster_id="c1",
        payload={"celsius": 42.1},
    )


# ── contract roundtrip ────────────────────────────────────────────────


def test_trigger_request_roundtrip():
    req = TriggerRequest(correlation_id="abc", events=[_event("a"), _event("b")])
    assert TriggerRequest.model_validate_json(req.model_dump_json()) == req


def test_trigger_result_roundtrip():
    res = TriggerResult(
        correlation_id="abc",
        cluster_ids=["c1"],
        cluster_score={"c1": RiskScore(risk_score=7, confidence=3)},
        assessments_produced=2,
    )
    assert TriggerResult.model_validate_json(res.model_dump_json()) == res


# ── fakes ─────────────────────────────────────────────────────────────


class FakeManager:
    """Stands in for the seed-hydrated CellStateManager the facade owns."""

    def __init__(self, *, triggered, payload):
        self._triggered = triggered  # list[(cluster_id, row, col)]
        self._payload = payload
        self.updated_events: list[SensorEvent] = []
        self.readings_for_called_with = None
        self.marked = None

    def update(self, event):
        self.updated_events.append(event)
        return self._triggered

    def readings_for(self, positions):
        self.readings_for_called_with = set(positions)
        return self._payload

    def mark_cells_evaluated(self, positions):
        self.marked = set(positions)


class FakeWriter:
    """Captures the WorldStateWriter seam calls (the 'end the flow' step)."""

    def __init__(self):
        self.calls: list[tuple[str, set]] = []

    def write(self, *, correlation_id, changed_cells):
        self.calls.append((correlation_id, set(changed_cells)))


def _readings(row, col):
    return SimpleNamespace(position=SimpleNamespace(row=row, col=col))


# ── facade: no readings → graph not invoked, but write seam still runs ─


async def test_run_trigger_empty_payload_skips_graph(monkeypatch):
    async def fake_invoke(graph, payload):
        raise AssertionError("invoke must not be called when nothing triggered")

    monkeypatch.setattr("runtime.facade.invoke_supervisor_for_trigger", fake_invoke)

    mgr = FakeManager(triggered=[], payload={})
    writer = FakeWriter()
    facade = GraphFacade(
        supervisor_graph=object(), cell_state_manager=mgr, world_state_writer=writer
    )
    req = TriggerRequest(correlation_id="cid", events=[_event()])

    res = await facade.run_trigger(req)

    assert res == TriggerResult(
        correlation_id="cid", cluster_ids=[], cluster_score={}, assessments_produced=0
    )
    assert len(mgr.updated_events) == 1  # event was folded
    assert mgr.marked == set()  # nothing included → nothing marked
    # CQRS: the write seam fires even on the short-circuit path.
    assert writer.calls == [("cid", set())]


# ── facade: events fold → readings → write seam → graph invoked ───────


async def test_run_trigger_folds_invokes_and_maps(monkeypatch):
    seen = {}

    async def fake_invoke(graph, payload):
        seen["payload"] = payload
        return SupervisorInvocation(
            cluster_ids=["c1"],
            cluster_score={"c1": RiskScore(risk_score=8, confidence=2)},
            assessments_produced=3,
        )

    monkeypatch.setattr("runtime.facade.invoke_supervisor_for_trigger", fake_invoke)

    payload = {"c1": [_readings(1, 2), _readings(3, 4)]}
    mgr = FakeManager(
        triggered=[("c1", 1, 2), ("c1", 3, 4)],
        payload=payload,
    )
    writer = FakeWriter()
    facade = GraphFacade(
        supervisor_graph=object(), cell_state_manager=mgr, world_state_writer=writer
    )
    req = TriggerRequest(correlation_id="cid", events=[_event()])

    res = await facade.run_trigger(req)

    assert seen["payload"] is payload
    assert res == TriggerResult(
        correlation_id="cid",
        cluster_ids=["c1"],
        cluster_score={"c1": RiskScore(risk_score=8, confidence=2)},
        assessments_produced=3,
    )
    assert mgr.readings_for_called_with == {(1, 2), (3, 4)}
    assert mgr.marked == {(1, 2), (3, 4)}  # included derived from payload
    assert writer.calls == [("cid", {(1, 2), (3, 4)})]


# ── in-process port delegates to the facade ───────────────────────────


async def test_in_process_client_delegates():
    sentinel = TriggerResult(
        correlation_id="z", cluster_ids=[], cluster_score={}, assessments_produced=0
    )

    class FakeFacade:
        def __init__(self):
            self.called_with = None

        async def run_trigger(self, request):
            self.called_with = request
            return sentinel

    ff = FakeFacade()
    client: GraphClient = InProcessGraphClient(ff)
    req = TriggerRequest(correlation_id="z", events=[])

    out = await client.invoke(req)

    assert out is sentinel
    assert ff.called_with is req
    assert isinstance(client, GraphClient)  # runtime_checkable protocol
