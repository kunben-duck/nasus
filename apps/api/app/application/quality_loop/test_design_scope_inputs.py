from typing import Annotated, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .acceptance_specifications import OracleInput
from ...domain.quality_loop.test_design_scope import SCOPE_POLICY


Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class ScopeValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Obligation(ScopeValue):
    obligation_id: Id
    constraint_ids: Tuple[Id, ...] = Field(min_length=1, max_length=256)
    evidence_ids: Tuple[Id, ...] = Field(max_length=256)
    oracle: OracleInput

    @model_validator(mode="after")
    def unique_references(self):
        if len(self.constraint_ids) != len(set(self.constraint_ids)) or len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("duplicate obligation source reference")
        return self


class Risk(Obligation):
    boundary: Text


class Permission(Obligation):
    actor: Text
    operation: Text
    resource: Text
    expected: Literal["allowed", "denied"]


class Transition(Obligation):
    from_state: Text
    event: Text
    to_state: Text


class Invariant(Obligation):
    invariant: Text


class Assessment(ScopeValue):
    applicability: Literal["applicable", "not_applicable"]
    rationale: Text


class Risks(Assessment):
    items: Tuple[Risk, ...] = Field(max_length=256)


class Permissions(Assessment):
    items: Tuple[Permission, ...] = Field(max_length=256)


class Transitions(Assessment):
    items: Tuple[Transition, ...] = Field(max_length=256)


class Invariants(Assessment):
    items: Tuple[Invariant, ...] = Field(max_length=256)


class Examples(ScopeValue):
    constraint_id: Id
    positive: OracleInput
    negative: Optional[OracleInput]
    negative_not_applicable_reason: Optional[Text]
    negative_gap_id: Optional[Id] = None

    @model_validator(mode="after")
    def require_negative_assessment(self):
        if sum(value is not None for value in (self.negative, self.negative_not_applicable_reason, self.negative_gap_id)) != 1:
            raise ValueError("provide a negative oracle, a not-applicable reason or a linked explicit gap")
        return self


class ScopeGap(ScopeValue):
    id: Id
    constraint_ids: Tuple[Id, ...] = Field(min_length=1, max_length=256)
    description: Text


class Conflict(ScopeGap):
    resolution: Optional[Text]


class TestDesignContract(ScopeValue):
    __test__ = False
    authority_basis: Literal["user_confirmed_test_design_scope"]
    risks: Risks
    permissions: Permissions
    transitions: Transitions
    invariants: Invariants
    examples: Tuple[Examples, ...] = Field(min_length=1, max_length=256)
    reused_case_ids: Tuple[Id, ...] = Field(max_length=256)
    reuse_assessment: Text
    conflicts: Tuple[Conflict, ...] = Field(max_length=256)
    conflict_assessment: Text
    gaps: Tuple[ScopeGap, ...] = Field(max_length=256)

    @model_validator(mode="after")
    def unique_references(self):
        for items in (self.conflicts, self.gaps):
            if len(items) != len({item.id for item in items}):
                raise ValueError("duplicate gap or conflict identifier")
        if len(self.reused_case_ids) != len(set(self.reused_case_ids)):
            raise ValueError("duplicate reused case")
        return self


class ScopeQueryInput(ScopeValue):
    project_id: Id
    context_id: Id


class ScopeReceipt(ScopeQueryInput):
    scope_id: Id
    context_artifact_hash: Digest
    head_revision_id: Optional[Id]
    head_artifact_hash: Optional[Digest]
    status: Literal["unreviewed", "approved", "withdrawn"]
    context_stale: bool
    scope_current: bool
    scope_complete: bool
    blocker_count: int = Field(ge=0, le=512)
    observation: Literal["query_time_requires_revalidation"] = "query_time_requires_revalidation"
    generation_authorized: Literal[False] = False


class ScopeReviewInput(ScopeQueryInput):
    context_artifact_hash: Digest
    expected_previous_revision_id: Optional[Id]
    decision: Literal["approve", "withdraw"]
    contract: Optional[TestDesignContract]
    reason: Text
    policy_revision: Literal["nasus.test-design-scope.v1"] = SCOPE_POLICY

    @model_validator(mode="after")
    def match_decision(self):
        if (self.decision == "approve") != (self.contract is not None):
            raise ValueError("approval requires a contract; withdrawal must omit it")
        return self
