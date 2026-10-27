"""Canonical runtime port; never substitutes for a capability-specific grant."""
from typing import Protocol

from ..platform.tool_models import ToolInvocation


class BuildToolBudgetRepositoryPort(Protocol):
    def reserve(self, invocation: ToolInvocation) -> bool: ...


class BuildToolBudgetApplicationService:
    def __init__(self, repository: BuildToolBudgetRepositoryPort):
        self.repository = repository

    def reserve_tool_work(self, invocation: ToolInvocation) -> bool:
        return self.repository.reserve(invocation)
