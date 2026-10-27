from typing import Callable, Protocol

from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied
from .build_plans import BuildPlanApplicationService
from .structure_cancel_inputs import StructureCancelInput, StructureCancelReceipt, StructureCancelStatus


class StructureCancellationRepositoryPort(Protocol):
    def require_origin(self, request: StructureCancelInput) -> None: ...
    def inspect(self, request: StructureCancelInput) -> tuple[str, bool, bool]: ...
    def cancel_confirmed(self, request: StructureCancelInput, *, invocation_id: str,
                         actor_id: str, require_current: Callable[[], None]) -> StructureCancelReceipt: ...


class StructureCancellationApplicationService:
    def __init__(self, plans: BuildPlanApplicationService, repository: StructureCancellationRepositoryPort):
        self.plans, self.repository = plans, repository

    def require_access(self, request: StructureCancelInput):
        scope = self.plans.authorization.scope(request.project_id)
        plan = self.plans.read(request.project_id, request.plan_id)
        if plan.plan_digest != request.plan_digest:
            raise BuildPlanIntegrityError("Structural cancellation plan digest changed.")
        self.repository.require_origin(request)
        self.plans.authorization.require_current(scope)
        return scope

    def cancel(self, request: StructureCancelInput, *, invocation_id: str):
        scope = self.require_access(request)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("Structural cancellation requires a current project reviewer.")
        receipt = self.repository.cancel_confirmed(request, invocation_id=invocation_id, actor_id=scope.actor_id,
            require_current=lambda: self.plans.authorization.require_current(scope))
        if receipt.request != request:
            raise BuildPlanIntegrityError("Structural cancellation receipt changed its command pins.")
        self.plans.authorization.require_current(scope)
        return receipt

    def inspect(self, request: StructureCancelInput):
        scope = self.require_access(request)
        status, requested, committed = self.repository.inspect(request)
        self.plans.authorization.require_current(scope)
        return StructureCancelStatus(request=request, original_status=status, cancellation_requested=requested,
            candidate_committed=committed, can_cancel=scope.effective_project_role in {"qa_lead", "project_admin", "platform_admin"}
                and status in {"pending", "running", "waiting_confirmation", "waiting_approval"} and not requested and not committed)
