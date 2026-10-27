from dataclasses import asdict
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.system_image.context_invalidation import (
    INVALIDATION_POLICY, ContextInvalidationChanged, ContextInvalidationIntegrityError, invalidation_metadata,
)
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest


def context_invalidation_query_keys(project_id):
    # Current-use changes apply to every pack of the exact image, not only the
    # preview root. Refresh project-scoped consumers; never rewrite history.
    return [[kind, project_id] for kind in (
        "context-packs", "test-design-scope", "generation-jobs", "test-design-mapping",
        "test-design-review-drafts", "test-design-review-draft", "mapping-staging",
        "mapping-part-editor", "mapping-final-preview", "automation-input", "automation-script-input",
        "automation-script-revisions", "automation-script-reviews",
    )]


class ContextInvalidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    context_id: StrictStr = Field(min_length=1, max_length=128)
    context_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    before_revision_id: StrictStr = Field(min_length=1, max_length=128)
    after_revision_id: StrictStr = Field(min_length=1, max_length=128)
    expected_impact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: StrictStr = Field(min_length=1, max_length=1500, pattern=r"\S")
    policy_revision: Literal[INVALIDATION_POLICY] = INVALIDATION_POLICY
    invalidation_scope: Literal["image_current_use"] = "image_current_use"


class ContextInvalidationRepositoryPort(Protocol):
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, metadata, nodes, *, require_current, require_access): ...
    def get(self, project_id, invalidation_id): ...


class ContextInvalidationApplicationService:
    def __init__(self, impacts, authorization, repository: ContextInvalidationRepositoryPort):
        self.impacts, self.authorization, self.repository = impacts, authorization, repository

    def invalidate(self, request: ContextInvalidateInput, *, invocation_id, recorded_at):
        request = ContextInvalidateInput.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("context invalidation requires an independent project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id,
            invocation_id=invocation_id, require_access=require_access)
        if prior is not None:
            stored = self.read(request.project_id, prior["invalidation_id"])
            if stored["metadata"] != prior:
                raise ContextInvalidationIntegrityError("invalidation recovery metadata mismatch")
            require_access()
            return prior
        def prepare():
            try:
                impact = self.impacts.read(request.project_id, request.context_id, request.context_artifact_hash,
                    request.before_revision_id, request.after_revision_id)
            except Exception:
                require_access()
                raise
            require_access()
            return impact
        impact = prepare()
        metadata = invalidation_metadata(request, impact, invalidation_id=str(uuid4()),
            actor_id=access.actor_id, invocation_id=invocation_id, recorded_at=recorded_at)
        def require_current():
            current = prepare()
            if snapshot_digest(asdict(current)) != request.expected_impact_hash:
                raise ContextInvalidationChanged("dependency inventory changed before invalidation commit")
            require_access()
        result = self.repository.record(request, metadata, impact.dependencies,
            require_current=require_current, require_access=require_access)
        require_access()
        return result

    def read(self, project_id, invalidation_id):
        access = self.authorization.scope(project_id)
        try:
            value = self.repository.get(project_id, invalidation_id)
        except Exception:
            self.authorization.require_current(access)
            raise
        self.authorization.require_current(access)
        request = ContextInvalidateInput.model_validate(value["metadata"]["request"])
        selected = tuple((node.kind, node.artifact_id) for node in value["dependencies"]
            if node.kind in {"scope", "generation", "mapping"})
        impact = self.impacts.read(project_id, request.context_id, request.context_artifact_hash,
            request.before_revision_id, request.after_revision_id, pinned=selected)
        self.authorization.require_current(access)
        expected = invalidation_metadata(request, impact,
            **{key: value["metadata"][key] for key in ("invalidation_id", "invocation_id", "recorded_at")},
            actor_id=value["metadata"]["authority_actor"])
        if expected != value["metadata"] or impact.dependencies != value["dependencies"]:
            raise ContextInvalidationIntegrityError("stored invalidation differs from its complete fixed derivation")
        self.authorization.require_current(access)
        return {"metadata": expected, "dependencies": [asdict(node) for node in value["dependencies"]],
            "historical_not_live": True}
