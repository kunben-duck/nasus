"""Public lifecycle uses PG metadata; it never starts or queries a provider."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.system_image.code_index_generation import CodeIndexGenerationPin, CodeIndexGenerationStatus, CodeIndexLeaseLost
from ...domain.system_image.source_access import SourceAccessDenied
from .source_access import SourceScopeAuthorizationPort


CODE_INDEX_LIST_TOOL = "query.system_image.code_indexes.list"
CODE_INDEX_STATUS_TOOL = "query.system_image.code_indexes.status"
CODE_INDEX_CANCEL_TOOL = "system_image.code_indexes.cancel"


class CodeIndexStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    generation_id: StrictStr = Field(min_length=1, max_length=128)


class CodeIndexListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    binding_id: StrictStr = Field(min_length=1, max_length=128)
    after_id: StrictStr = Field(default="", max_length=128)
    limit: int = Field(default=10, strict=True, ge=1, le=30)


class CodeIndexCancelInput(CodeIndexStatusInput):
    expected_generation_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class CodeIndexListPage:
    request: CodeIndexListInput
    items: tuple[CodeIndexGenerationPin, ...]
    next_after_id: Optional[str]
    scope: str = "source_authorized_generation_discovery_not_execution_authorization"


@dataclass(frozen=True)
class CodeIndexStatusReceipt:
    request: CodeIndexStatusInput
    status: CodeIndexGenerationStatus
    # Older metadata receipts never grant permission to cancel today's worker.
    can_cancel: bool = False


@dataclass(frozen=True)
class CodeIndexCancelReceipt:
    request: CodeIndexCancelInput
    outcome: Literal["cancel_requested", "cancelled", "already_committed", "already_terminal"]
    status: CodeIndexGenerationStatus


class CodeIndexLifecycleRepositoryPort(Protocol):
    def get(self, project_id: str, generation_id: str) -> CodeIndexGenerationPin: ...
    def list(self, request: CodeIndexListInput) -> CodeIndexListPage: ...
    def status(self, pin: CodeIndexGenerationPin) -> CodeIndexGenerationStatus: ...
    def cancel_confirmed(self, pin: CodeIndexGenerationPin, *, invocation_id: str,
                         require_current: Callable[[], None]) -> tuple[str, CodeIndexGenerationStatus]: ...


class CodeIndexLifecycleApplicationService:
    def __init__(self, repository: CodeIndexLifecycleRepositoryPort, authorization: SourceScopeAuthorizationPort):
        self.repository, self.authorization = repository, authorization

    def list(self, request: CodeIndexListInput):
        scope = self.authorization.scope(request.project_id)
        scope.require_binding(request.binding_id)
        result = self.repository.list(request)
        if result.request != request or any(pin.project_id != request.project_id or pin.binding_id != request.binding_id for pin in result.items):
            raise CodeIndexLeaseLost("code index discovery crosses its authorized source")
        self.authorization.require_current(scope)
        return result

    def _pin(self, request):
        scope = self.authorization.scope(request.project_id)
        pin = self.repository.get(request.project_id, request.generation_id)
        if pin.project_id != request.project_id or pin.generation_id != request.generation_id:
            raise CodeIndexLeaseLost("code index belongs to a different project")
        scope.require_binding(pin.binding_id)
        self.authorization.require_current(scope)
        return pin, scope

    def require_receipt_access(self, request: CodeIndexListInput | CodeIndexStatusInput) -> None:
        if isinstance(request, CodeIndexListInput):
            scope = self.authorization.scope(request.project_id)
            scope.require_binding(request.binding_id)
            self.authorization.require_current(scope)
        else:
            self._pin(request)

    def read(self, request: CodeIndexStatusInput):
        pin, scope = self._pin(request)
        status = self.repository.status(pin)
        if status.pin != pin:
            raise CodeIndexLeaseLost("code index status substituted its generation")
        self.authorization.require_current(scope)
        can_cancel = (scope.effective_project_role in {"qa_lead", "project_admin", "platform_admin"}
            and status.invocation_status == "running" and status.state not in {"cancel_requested", "cancelled", "failed"})
        return CodeIndexStatusReceipt(request, status, can_cancel)

    def cancel(self, request: CodeIndexCancelInput, *, invocation_id: str):
        pin, scope = self._pin(request)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("code index cancellation requires a project reviewer")
        if request.expected_generation_hash != pin.content_hash:
            raise CodeIndexLeaseLost("code index cancellation pin changed")
        outcome, status = self.repository.cancel_confirmed(pin, invocation_id=invocation_id,
            require_current=lambda: self.authorization.require_current(scope))
        if status.pin != pin or outcome not in {"cancel_requested", "cancelled", "already_committed", "already_terminal"}:
            raise CodeIndexLeaseLost("code index cancellation receipt is inconsistent")
        self.authorization.require_current(scope)
        return CodeIndexCancelReceipt(request, outcome, status)
