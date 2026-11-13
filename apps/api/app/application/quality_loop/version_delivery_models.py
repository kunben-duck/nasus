from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ..system_image.publication_read_models import PublishedImagePin


class VersionImageBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    publication_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_head_id: StrictStr = Field(min_length=1, max_length=128)


class DeliveryCodeRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: str
    source_id: str
    source_revision_id: str
    repository: str
    tracked_ref: Optional[str]
    external_revision: str
    commit_sha: Optional[str]
    content_hash: str
    manifest_hash: str


class IterationImagePin(PublishedImagePin):
    publication_id: Optional[str] = None
    review_event_id: Optional[str] = None


class VersionDeliveryReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: str
    version_id: str
    name: str
    enabled: bool
    stage: Literal["legacy", "image_pinned", "requirement_review", "requirements_confirmed"]
    baseline: Optional[PublishedImagePin] = None
    iteration_image: Optional[Union[PublishedImagePin, IterationImagePin]] = None
    code_revisions: list[DeliveryCodeRevision] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    pending_confirmations: list[str] = Field(default_factory=list)
    available_actions: list[Literal["view_pinned_image"]] = Field(default_factory=list)


def delivery_view(project_id, version, binding):
    return VersionDeliveryReadModel(project_id=project_id, version_id=version.id, name=version.name,
        enabled=binding is not None, stage="image_pinned" if binding else "legacy",
        **(binding or {}), blockers=["requirement_input_required"] if binding else [],
        available_actions=["view_pinned_image"] if binding else [])
