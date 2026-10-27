"""Receipt reads and broadcasts through the original RunPlan application port."""
from __future__ import annotations

from typing import Protocol, Sequence
from pydantic import ValidationError

from ..quality_loop.run_plan_inputs import RunPlanCommandScope
from ...domain.quality_loop.run_plan import RUN_PLAN_TOOL, RUN_PLAN_PREVIEW_TOOL
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from .errors import PlatformApplicationError
from .tool_models import ToolInvocation


RUN_PLAN_RECEIPT_TOOLS = frozenset({RUN_PLAN_TOOL, RUN_PLAN_PREVIEW_TOOL})


class RunPlanReceiptAuthorizationPort(Protocol):
    def require_command_inputs_access(self, scope: RunPlanCommandScope) -> None: ...
    def require_command_inputs_access_many(self, scopes: Sequence[RunPlanCommandScope]) -> None: ...


class RunPlanReceiptAccess:
    def __init__(self, plans: RunPlanReceiptAuthorizationPort):
        self.plans = plans

    @staticmethod
    def applies(invocation: ToolInvocation) -> bool:
        return invocation.tool_id in RUN_PLAN_RECEIPT_TOOLS

    @staticmethod
    def _scope(invocation: ToolInvocation) -> RunPlanCommandScope:
        try:
            return RunPlanCommandScope.model_validate({key: invocation.input_payload.get(key)
                for key in RunPlanCommandScope.model_fields})
        except ValidationError as exc:
            raise PlatformApplicationError("run_plan_receipt_scope_invalid", "Original plan receipt scope cannot be verified.", 409) from exc

    @staticmethod
    def _authorize(operation, *args):
        try:
            operation(*args)
        except (SourceAccessDenied, StaleSourceAccessScope, KeyError) as exc:
            raise PlatformApplicationError("run_plan_receipt_access_denied", "Original plan receipt is not available.", 403) from exc
        except PlatformApplicationError:
            raise
        except ValueError as exc:
            raise PlatformApplicationError("run_plan_receipt_integrity_failed", "Original plan receipt provenance cannot be verified.", 502) from exc
        except Exception as exc:
            raise PlatformApplicationError("run_plan_receipt_access_unavailable", "Original plan receipt authorization is unavailable.", 503) from exc

    def require_access(self, invocation: ToolInvocation) -> None:
        if self.applies(invocation):
            scope = self._scope(invocation)
            operation = getattr(self.plans, "require_command_inputs_access", None)
            if not callable(operation):
                raise PlatformApplicationError("run_plan_receipt_access_unavailable", "Original plan receipt authorization is unavailable.", 503)
            self._authorize(operation, scope)

    def require_batch_access(self, invocations: Sequence[ToolInvocation]) -> None:
        scopes = {}
        for invocation in invocations:
            if self.applies(invocation):
                scope = self._scope(invocation)
                key = tuple(scope.model_dump(mode="json").values())
                scopes[key] = scope
        if not scopes:
            return
        operation = getattr(self.plans, "require_command_inputs_access_many", None)
        if len(scopes) > 128 or not callable(operation):
            raise PlatformApplicationError("run_plan_receipt_access_unavailable", "Original plan receipt authorization is unavailable.", 503)
        self._authorize(operation, tuple(scopes.values()))

    def broadcast_view(self, invocation: ToolInvocation) -> ToolInvocation:
        if not self.applies(invocation):
            return invocation
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "summary": f"Execution plan command status: {invocation.status}.",
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)
