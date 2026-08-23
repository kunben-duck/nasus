"""Execution runner adapters."""

from .adapters import (
    FailClosedAutomationRunner,
    HttpAutomationRunner,
    ProtocolStubAutomationRunner,
    build_automation_runner_from_env,
)
from .readiness import AutomationRunnerReadinessProbe
from .run_orchestrator import RunExecutionOutcome, RunOrchestrator, RunTaskContextProvider

__all__ = [
    "AutomationRunnerReadinessProbe",
    "FailClosedAutomationRunner",
    "HttpAutomationRunner",
    "ProtocolStubAutomationRunner",
    "RunExecutionOutcome",
    "RunOrchestrator",
    "RunTaskContextProvider",
    "build_automation_runner_from_env",
]
