"""Native generation lifecycle contracts, independent of Temporal and SQL."""
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .test_design_output import Digest, Id
from .test_design_generation import GenerationSelection


GENERATION_RECOVER_TOOL = "quality.test_design.recover"
GENERATION_CANCEL_TOOL = "quality.test_design.cancel"
GENERATION_JOB_QUERY_TOOL = "query.quality.test_design_job"
GENERATION_HISTORY_QUERY_TOOL = "query.quality.test_design_jobs"


class GenerationJobTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: Id
    invocation_id: Id


class GenerationRecoveryRequest(GenerationJobTarget):
    request_hash: Digest
    reply_artifact_hash: Digest
    response_hash: Digest


def parse_generation_recovery(value):
    # Preserve the single-reply contract; versioned batches must never be
    # silently coerced into it or accepted with an unknown schema.
    if isinstance(value, dict) and "schema_version" in value:
        from .generation_batch_recovery import GenerationBatchRecoveryRequest
        return GenerationBatchRecoveryRequest.model_validate(value)
    return GenerationRecoveryRequest.model_validate(value)


class GenerationHistoryRequest(GenerationSelection):
    after_id: str = Field(default="", max_length=128, strict=True)
    limit: int = Field(default=20, ge=1, le=50, strict=True)


class GenerationJobWorkflowPort(Protocol):
    async def start(self, invocation_id: str) -> bool: ...
    async def cancel(self, invocation_id: str) -> None: ...


class GenerationJobRepositoryPort(Protocol):
    def claim_lease(self, project_id, invocation_id, owner_id): ...
    def require_lease(self, lease): ...
    def renew_lease(self, lease): ...
    def release_lease(self, lease): ...
    def history(self, request): ...
    def command(self, invocation_id): ...
    def execution(self, invocation_id): ...
    def inspection(self, invocation_id): ...
    def require_running(self, request, invocation_id, actor_id): ...
    def finish(self, project_id, invocation_id, status, summary, *, control_id=None, actor_id=None, require_current=None, lease=None): ...
    def pending(self, *, after_id=None, limit=100): ...
    def pending_cancellations(self, *, after_id=None, limit=100): ...
    def cancellation_delivered(self, project_id, invocation_id): ...
