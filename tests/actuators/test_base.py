"""Tests for ogar.actuators.base — ActuatorCommand, ActuatorResult, ActuatorBase."""

import pytest

from actuators.base import ActuatorCommand, ActuatorResult, ActuatorBase


# ── ActuatorCommand ──────────────────────────────────────────────────────────

class TestActuatorCommand:
    def test_create_sets_id_and_timestamp(self):
        cmd = ActuatorCommand.create(
            command_type="alert",
            source_agent="supervisor",
            cluster_id="c1",
            payload={"msg": "fire detected"},
        )
        assert isinstance(cmd.command_id, str)
        assert len(cmd.command_id) > 0
        assert cmd.timestamp is not None

    def test_create_unique_ids(self):
        c1 = ActuatorCommand.create(
            command_type="a", source_agent="s", cluster_id="c", payload={}
        )
        c2 = ActuatorCommand.create(
            command_type="a", source_agent="s", cluster_id="c", payload={}
        )
        assert c1.command_id != c2.command_id

    def test_create_fields(self):
        cmd = ActuatorCommand.create(
            command_type="suppress",
            source_agent="supervisor-1",
            cluster_id="cluster-south",
            payload={"target": "C4"},
            priority=5,
            metadata={"reason": "high confidence"},
        )
        assert cmd.command_type == "suppress"
        assert cmd.source_agent == "supervisor-1"
        assert cmd.cluster_id == "cluster-south"
        assert cmd.payload == {"target": "C4"}
        assert cmd.priority == 5
        assert cmd.metadata == {"reason": "high confidence"}

    def test_default_priority(self):
        cmd = ActuatorCommand.create(
            command_type="a", source_agent="s", cluster_id="c", payload={}
        )
        assert cmd.priority == 3

    def test_default_metadata_empty(self):
        cmd = ActuatorCommand.create(
            command_type="a", source_agent="s", cluster_id="c", payload={}
        )
        assert cmd.metadata == {}


# ── ActuatorResult ───────────────────────────────────────────────────────────

class TestActuatorResult:
    def test_success_result(self):
        r = ActuatorResult.success_result("cmd-123", payload={"sent": True})
        assert r.success is True
        assert r.command_id == "cmd-123"
        assert r.payload == {"sent": True}
        assert r.error is None
        assert isinstance(r.result_id, str)

    def test_failure_result(self):
        r = ActuatorResult.failure_result("cmd-456", error="connection refused")
        assert r.success is False
        assert r.command_id == "cmd-456"
        assert r.error == "connection refused"

    def test_success_result_default_payload(self):
        r = ActuatorResult.success_result("cmd-789")
        assert r.payload == {}


# ── ActuatorBase ─────────────────────────────────────────────────────────────

class _TestActuator(ActuatorBase):
    command_type = "test_action"

    async def execute(self, command: ActuatorCommand) -> ActuatorResult:
        return ActuatorResult.success_result(
            command.command_id, payload={"executed": True}
        )


class _FailingActuator(ActuatorBase):
    command_type = "fail_action"

    async def execute(self, command: ActuatorCommand) -> ActuatorResult:
        return ActuatorResult.failure_result(command.command_id, "boom")


class TestActuatorBase:
    @pytest.mark.asyncio
    async def test_handle_correct_type(self):
        actuator = _TestActuator()
        cmd = ActuatorCommand.create(
            command_type="test_action",
            source_agent="s",
            cluster_id="c1",
            payload={},
        )
        result = await actuator.handle(cmd)
        assert result.success is True
        assert result.payload == {"executed": True}

    @pytest.mark.asyncio
    async def test_handle_wrong_type_rejected(self):
        actuator = _TestActuator()
        cmd = ActuatorCommand.create(
            command_type="wrong_type",
            source_agent="s",
            cluster_id="c1",
            payload={},
        )
        result = await actuator.handle(cmd)
        assert result.success is False
        assert "wrong_type" in result.error

    @pytest.mark.asyncio
    async def test_handle_failing_actuator(self):
        actuator = _FailingActuator()
        cmd = ActuatorCommand.create(
            command_type="fail_action",
            source_agent="s",
            cluster_id="c1",
            payload={},
        )
        result = await actuator.handle(cmd)
        assert result.success is False
        assert result.error == "boom"

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ActuatorBase()
