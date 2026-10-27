from typing import Literal, Optional, Tuple

from pydantic import Field, StrictInt, model_validator

from .test_design_output import GenerationValue, Id, Digest, Text
from ...domain.quality_loop.test_design_mapping import MAPPING_POLICY
from ...domain.quality_loop.mapping_partitions import MAX_ASSERTIONS


class MappingQueryInput(GenerationValue):
    project_id: Id
    generation_id: Id
    generation_artifact_hash: Digest


class AssertionReview(GenerationValue):
    case_id: Id
    row_id: Id
    step_index: StrictInt = Field(ge=0, le=63)
    oracle_digest: Digest
    decision: Literal["accept", "reject", "defer"]
    reason: Text


class MappingReviewInput(MappingQueryInput):
    expected_previous_revision_id: Optional[Id]
    decision: Literal["review", "withdraw"]
    mappings: Optional[Tuple[AssertionReview, ...]] = Field(max_length=8192)
    reason: Text
    policy_revision: Literal["nasus.test-design-mapping.v1"] = MAPPING_POLICY

    @model_validator(mode="after")
    def match_decision(self):
        if (self.decision == "review") != (self.mappings is not None):
            raise ValueError("review requires mappings; withdrawal must omit them")
        return self


class MappingReceipt(MappingQueryInput):
    head_revision_id: Optional[Id]
    head_artifact_hash: Optional[Digest]
    status: Literal["unreviewed", "reviewed", "withdrawn"]
    scope_current: bool
    mapping_current: bool
    mapping_complete: bool
    accepted_assertion_count: StrictInt = Field(ge=0, le=8192)
    rejected_assertion_count: StrictInt = Field(ge=0, le=8192)
    deferred_assertion_count: StrictInt = Field(ge=0, le=8192)
    observation: Literal["query_time_requires_revalidation"] = "query_time_requires_revalidation"
    execution_authorized: Literal[False] = False


class PartitionedMappingReceipt(MappingQueryInput):
    schema_version: Literal["nasus.test-design-mapping-receipt.v2"] = "nasus.test-design-mapping-receipt.v2"
    head_revision_id: Id
    head_artifact_hash: Digest
    status: Literal["reviewed"]
    scope_current: bool
    mapping_current: bool
    mapping_complete: bool
    accepted_assertion_count: StrictInt = Field(ge=0, le=MAX_ASSERTIONS)
    rejected_assertion_count: StrictInt = Field(ge=0, le=MAX_ASSERTIONS)
    deferred_assertion_count: StrictInt = Field(ge=0, le=MAX_ASSERTIONS)
    observation: Literal["query_time_requires_revalidation"] = "query_time_requires_revalidation"
    execution_authorized: Literal[False] = False
