import asyncio
from types import SimpleNamespace

from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.workflow.conversation_memory_runtime import TemporalConversationMemoryRuntime
from apps.api.app.infrastructure.workflow.nasus_memory_workflow import NasusConversationMemoryWorkflow


def test_memory_runtime_uses_dedicated_queue_and_stable_identity(monkeypatch):
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    class Client:
        async def start_workflow(self, workflow, job_id, **kwargs):
            self.workflow, self.job_id, self.options = workflow, job_id, kwargs
    client = Client()
    runtime = TemporalConversationMemoryRuntime(TemporalGatewayConfig(task_queue="unit-goals"), client)
    assert asyncio.run(runtime.start("job-1")) is True
    assert client.workflow == NasusConversationMemoryWorkflow.run
    assert client.options["task_queue"] == "unit-goals-conversation-memory"
    assert client.options["id"] == "nasus-conversation-memory:job-1"
    assert client.options["rpc_timeout"].total_seconds() == 10


def test_ended_workflow_is_not_silently_treated_as_running(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.exceptions import WorkflowAlreadyStartedError
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    class Client:
        async def start_workflow(self, *args, **kwargs):
            raise WorkflowAlreadyStartedError("job-1", "NasusConversationMemoryWorkflow")
        def get_workflow_handle(self, ident):
            return self
        async def describe(self, **kwargs):
            return SimpleNamespace(status=WorkflowExecutionStatus.FAILED)
    runtime = TemporalConversationMemoryRuntime(TemporalGatewayConfig(), Client())
    assert asyncio.run(runtime.start("job-1")) is False


def test_cancellation_targets_the_memory_workflow(monkeypatch):
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    class Client:
        def get_workflow_handle(self, ident):
            self.ident = ident
            return self
        async def cancel(self, **kwargs):
            self.cancelled = True
    client = Client()
    runtime = TemporalConversationMemoryRuntime(TemporalGatewayConfig(), client)
    asyncio.run(runtime.cancel("job-1"))
    assert client.cancelled and client.ident == "nasus-conversation-memory:job-1"
