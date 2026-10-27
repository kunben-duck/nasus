from typing import Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_serializer, model_validator

from ...domain.system_image.context_pack import CONTEXT_POLICY
from ...domain.system_image.context_partition import PARTITION_POLICY, RULE_AUTHORITY_POLICY, PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY, MAX_CONSTRAINTS
from ...domain.system_image.context_authorities import CONTEXT_AUTHORITY_POLICY


class ContextPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    purpose: Literal["test_design"] = "test_design"
    # Omitted-policy commands and their historical hashes retain v1 semantics.
    policy_revision: Literal[CONTEXT_POLICY, PARTITION_POLICY, RULE_AUTHORITY_POLICY, PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY] = CONTEXT_POLICY
    publication_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    retrieval_bindings: Optional[dict[StrictStr, StrictStr]] = None
    max_tokens: StrictInt = Field(default=12000, ge=512, le=32768)
    candidate_limit: StrictInt = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def publication_scope(self):
        if (self.policy_revision in {PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY}) != (self.publication_id is not None):
            raise ValueError("Published context v4/v5 requires a publication_id")
        if (self.policy_revision == INDEXED_CONTEXT_POLICY) != (self.retrieval_bindings is not None):
            raise ValueError("Only indexed context v5 requires explicit AC-to-retrieval bindings")
        if self.retrieval_bindings is not None and (len(self.retrieval_bindings) > MAX_CONSTRAINTS
                or any(not 1 <= len(key) <= 128 or not 1 <= len(value) <= 128 for key, value in self.retrieval_bindings.items())):
            raise ValueError("Invalid context retrieval bindings")
        return self

    @model_serializer(mode="wrap")
    def compatible_payload(self, handler):
        value = handler(self)
        if self.policy_revision not in {PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY}:
            value.pop("publication_id", None)
        if self.policy_revision != INDEXED_CONTEXT_POLICY:
            value.pop("retrieval_bindings", None)
        return value


class ContextCompileInput(ContextPreviewInput):
    expected_input_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ContextReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    context_id: StrictStr = Field(min_length=1, max_length=128)


class ContextAuthorityRegistrationInput(ContextReadInput):
    artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_revision: Literal[CONTEXT_AUTHORITY_POLICY] = CONTEXT_AUTHORITY_POLICY


CONTEXT_AUTHORITY_BACKFILL_TOOL = "query.system_image.context.authority_backfill"


class ContextAuthorityBackfillInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    after_id: StrictStr = Field(default="", max_length=128)
    limit: StrictInt = Field(default=3, ge=1, le=5)


class ContextAuthorityBackfillItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    registration_request: ContextAuthorityRegistrationInput
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: Literal["requires_independent_confirmation"]


class ContextAuthorityBackfillReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ContextAuthorityBackfillInput
    items: Tuple[ContextAuthorityBackfillItem, ...] = Field(max_length=5)
    page_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    next_after_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    observation: Literal["historical_dependency_page_requires_revalidation"] = "historical_dependency_page_requires_revalidation"
    generation_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def page_boundaries(self):
        ids = tuple(item.registration_request.context_id for item in self.items)
        if (len(ids) > self.request.limit or tuple(sorted(set(ids))) != ids
                or any(ident <= self.request.after_id for ident in ids)
                or any(item.registration_request.project_id != self.request.project_id for item in self.items)
                or self.next_after_id is not None and
                    (len(ids) != self.request.limit or self.next_after_id != ids[-1])):
            raise ValueError("historical dependency receipt must preserve its project, page and cursor")
        return self


class ContextListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    after_id: StrictStr = Field(default="", max_length=128)
    limit: StrictInt = Field(default=20, ge=1, le=50)


class ContextListReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ContextListInput
    context_ids: list[StrictStr]
    page_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    next_after_id: Optional[StrictStr]
    observation: Literal["history_index_requires_revalidation"] = "history_index_requires_revalidation"
    generation_authorized: Literal[False] = False


def preview_request(request):
    return ContextPreviewInput.model_validate(request.model_dump(exclude={"expected_input_digest"}))


class ContextPackReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: Union[ContextPreviewInput, ContextReadInput]
    input_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    image_revision_id: StrictStr
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    context_id: Optional[StrictStr] = None
    artifact_hash: Optional[StrictStr] = None
    readiness: Literal["partial", "blocked"]
    mandatory_count: StrictInt = Field(ge=0, le=MAX_CONSTRAINTS)
    observation: Literal["preview_requires_revalidation", "historical_not_live"]
    generation_authorized: Literal[False] = False
