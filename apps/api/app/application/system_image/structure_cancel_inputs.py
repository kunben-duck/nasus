"""Independent cancellation pins; original build consent never authorizes stop."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


STRUCTURE_CANCEL_TOOL = "system_image.build.structure.cancel"


class StructureCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    original_invocation_id: StrictStr = Field(min_length=1, max_length=128)
    plan_id: StrictStr = Field(min_length=1, max_length=128)
    plan_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target_baseline_id: StrictStr = Field(min_length=1, max_length=128)


class StructureCancelReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: StructureCancelInput
    outcome: Literal["cancel_requested", "cancelled", "already_requested", "already_committed", "already_terminal"]
    original_status: Literal["pending", "running", "waiting_confirmation", "waiting_approval", "completed", "failed", "cancelled"]


class StructureCancelStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: StructureCancelInput
    original_status: Literal["pending", "running", "waiting_confirmation", "waiting_approval", "completed", "failed", "cancelled"]
    cancellation_requested: bool
    candidate_committed: bool
    can_cancel: bool
