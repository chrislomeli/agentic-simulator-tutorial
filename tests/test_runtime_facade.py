"""Tests for the graph entry-point seam: contract, facade, in-process port.

The facade is isolated by monkeypatching ``invoke_supervisor_for_trigger``
so these assert the facade's own behaviour (mirrors the streaming
orchestrator's invoke path) without depending on graph internals.
"""

from __future__ import annotations

from types import SimpleNamespace

from agents.commons.schemas import GridPosition
from agents.supervisor.state import RiskScore
from runtime.contract import TriggerRequest, TriggerResult
from runtime.facade import GraphFacade
from runtime.graph_client import GraphClient, InProcessGraphClient
from runtime.orchestrator import SupervisorInvocation


# ── contract roundtrip ────────────────────────────────────────────────


def test_trigger_request_roundtrip():
    req = TriggerRequest(
        correlation_id="abc",
        cells=[GridPosition(row=1, col=2), GridPosition(row=3, col=4)],
    )
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
    def __init__(self, payload):
        self._payload = payload
        self.readings_for_called_with = None
        self.marked = None

    def readings_for(self, positions):
        self.readings_for_called_with = set(positions)
        return self._payload

    def mark_cells_evaluated(self, positions):
        self.marked = set(positions)


def _readings(row, col):
    return SimpleNamespace(position=SimpleNamespace(row=row, col=col))


# ── facade: empty payload short-circuits, graph not invoked ───────────


async def test_run_trigger_empty_payload_skips_graph(monkeypatch):
    async def fake_invoke(graph, payload):
        raise AssertionError("invoke must not be called on empty payload")

    monkeypatch.setattr("runtime.facade.invoke_supervisor_for_trigger", fake_invoke)

    mgr = FakeManager(payload={})
    facade = GraphFacade(supervisor_graph=object(), cell_state_manager=mgr)
    req = TriggerRequest(correlation_id="cid", cells=[GridPosition(row=5, col=6)])

    res = await facade.run_trigger(req)

    assert res == TriggerResult(
        correlation_id="cid", cluster_ids=[], cluster_score={}, assessments_produced=0
    )
    assert mgr.readings_for_called_with == {(5, 6)}
    assert mgr.marked == set()  # nothing included → nothing marked


# ── facade: non-empty payload invokes graph and maps the outcome ──────


async def test_run_trigger_invokes_and_maps(monkeypatch):
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
    mgr = FakeManager(payload=payload)
    facade = GraphFacade(supervisor_graph=object(), cell_state_manager=mgr)
    req = TriggerRequest(
        correlation_id="cid",
        cells=[GridPosition(row=1, col=2), GridPosition(row=3, col=4)],
    )

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
    req = TriggerRequest(correlation_id="z", cells=[])

    out = await client.invoke(req)

    assert out is sentinel
    assert ff.called_with is req
    assert isinstance(client, GraphClient)  # runtime_checkable protocol
