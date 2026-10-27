from typing import Literal, Optional, Tuple

from pydantic import Field, StrictInt, model_validator

from .test_design_output import GenerationValue, Id, Digest, Text


class ScriptReviewQuery(GenerationValue):
    project_id: Id
    script_revision_id: Id
    script_artifact_hash: Digest


class ScriptActionDecision(GenerationValue):
    case_id: Id
    action_index: StrictInt = Field(ge=0, le=255)
    action_digest: Digest
    decision: Literal["accept", "reject", "defer"]
    reason: Text


class ScriptOracleDecision(GenerationValue):
    case_id: Id
    row_id: Id
    action_index: StrictInt = Field(ge=0, le=255)
    source_step_index: StrictInt = Field(ge=0, le=63)
    oracle_digest: Digest
    decision: Literal["accept", "reject", "defer"]
    reason: Text


class ScriptReviewRequest(ScriptReviewQuery):
    expected_previous_revision_id: Optional[Id]
    decision: Literal["review", "withdraw"]
    actions: Optional[Tuple[ScriptActionDecision, ...]] = Field(max_length=131072)
    assertions: Optional[Tuple[ScriptOracleDecision, ...]] = Field(max_length=131072)
    reason: Text
    policy_revision: Literal["nasus.automation-script-review.v1"] = "nasus.automation-script-review.v1"

    @model_validator(mode="after")
    def complete_decisions(self):
        if ((self.decision == "review") != (self.actions is not None)
                or (self.decision == "review") != (self.assertions is not None)):
            raise ValueError("review requires complete decisions; withdrawal must omit them")
        return self
