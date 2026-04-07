"""Tests for ogar.workflow — WorkflowRunner interface + AsyncioWorkflowRunner."""

import asyncio

import pytest

from workflow.runner import WorkflowRunner, WorkflowStatus
from workflow.stub import AsyncioWorkflowRunner


@pytest.fixture
def runner():
    return AsyncioWorkflowRunner()


async def _simple_workflow(workflow_id, signal_queue):
    """A minimal workflow that completes immediately."""
    pass


async def _signal_workflow(workflow_id, signal_queue):
    """A workflow that waits for one signal then exits."""
    sig = await signal_queue.get()
    return sig


async def _long_workflow(workflow_id, signal_queue):
    """A workflow that sleeps, can be cancelled."""
    await asyncio.sleep(60)


async def _failing_workflow(workflow_id, signal_queue):
    """A workflow that raises."""
    raise ValueError("intentional failure")


class TestWorkflowStatus:
    def test_enum_values(self):
        assert WorkflowStatus.RUNNING == "RUNNING"
        assert WorkflowStatus.COMPLETED == "COMPLETED"
        assert WorkflowStatus.FAILED == "FAILED"
        assert WorkflowStatus.UNKNOWN == "UNKNOWN"

    def test_runner_is_abstract(self):
        with pytest.raises(TypeError):
            WorkflowRunner()


class TestAsyncioWorkflowRunnerStart:
    @pytest.mark.asyncio
    async def test_start_simple_workflow(self, runner):
        await runner.start("wf-1", _simple_workflow)
        await asyncio.sleep(0.05)
        status = await runner.get_status("wf-1")
        assert status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_start_deduplication(self, runner):
        await runner.start("wf-dup", _long_workflow)
        await asyncio.sleep(0.02)
        await runner.start("wf-dup", _long_workflow)
        status = await runner.get_status("wf-dup")
        assert status == WorkflowStatus.RUNNING
        await runner.shutdown()

    @pytest.mark.asyncio
    async def test_unknown_status(self, runner):
        status = await runner.get_status("never-started")
        assert status == WorkflowStatus.UNKNOWN


class TestAsyncioWorkflowRunnerSignal:
    @pytest.mark.asyncio
    async def test_signal_delivery(self, runner):
        await runner.start("wf-sig", _signal_workflow)
        await asyncio.sleep(0.02)
        await runner.signal("wf-sig", "go", {"data": 1})
        await asyncio.sleep(0.1)
        status = await runner.get_status("wf-sig")
        assert status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_signal_to_nonexistent_workflow(self, runner):
        """Should not raise, just log warning and discard."""
        await runner.signal("no-such-wf", "test", None)

    @pytest.mark.asyncio
    async def test_signal_to_completed_workflow(self, runner):
        await runner.start("wf-done", _simple_workflow)
        await asyncio.sleep(0.05)
        await runner.signal("wf-done", "late", None)


class TestAsyncioWorkflowRunnerReceiveSignal:
    @pytest.mark.asyncio
    async def test_receive_signal_returns_tuple(self, runner):
        await runner.start("wf-recv", _long_workflow)
        await asyncio.sleep(0.02)
        await runner.signal("wf-recv", "event", {"x": 1})
        result = await runner.receive_signal("wf-recv", timeout_seconds=1.0)
        assert result == ("event", {"x": 1})
        await runner.shutdown()

    @pytest.mark.asyncio
    async def test_receive_signal_timeout(self, runner):
        await runner.start("wf-timeout", _long_workflow)
        await asyncio.sleep(0.02)
        result = await runner.receive_signal("wf-timeout", timeout_seconds=0.05)
        assert result is None
        await runner.shutdown()

    @pytest.mark.asyncio
    async def test_receive_signal_unknown_workflow(self, runner):
        result = await runner.receive_signal("ghost", timeout_seconds=0.01)
        assert result is None


class TestAsyncioWorkflowRunnerFailure:
    @pytest.mark.asyncio
    async def test_failed_workflow_status(self, runner):
        await runner.start("wf-fail", _failing_workflow)
        await asyncio.sleep(0.1)
        status = await runner.get_status("wf-fail")
        assert status == WorkflowStatus.FAILED


class TestAsyncioWorkflowRunnerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_cancels_running_tasks(self, runner):
        await runner.start("wf-long-1", _long_workflow)
        await runner.start("wf-long-2", _long_workflow)
        await asyncio.sleep(0.02)
        await runner.shutdown()
        s1 = await runner.get_status("wf-long-1")
        s2 = await runner.get_status("wf-long-2")
        assert s1 == WorkflowStatus.FAILED
        assert s2 == WorkflowStatus.FAILED

    @pytest.mark.asyncio
    async def test_shutdown_empty_is_safe(self, runner):
        await runner.shutdown()
