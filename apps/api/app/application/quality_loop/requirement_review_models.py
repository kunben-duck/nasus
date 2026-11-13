from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .acceptance_specifications import OracleInput
from .requirement_revision_models import RequirementSelection

EVALUATE_REQUIREMENT = "quality.requirement.evaluate"
CONFIRM_REQUIREMENT = "quality.requirement.confirm"
READ_REQUIREMENT_REVIEW = "query.quality.requirement_review"
REVIEW_TOOLS = {EVALUATE_REQUIREMENT, CONFIRM_REQUIREMENT, READ_REQUIREMENT_REVIEW}


class ReviewSelection(RequirementSelection):
    revision_id: StrictStr = Field(min_length=1, max_length=128)


class EvaluateRequirement(ReviewSelection):
    input_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ConfirmRequirement(ReviewSelection):
    evaluation_id: StrictStr = Field(min_length=1, max_length=128)
    review_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: StrictStr = Field(min_length=1, max_length=2000)


class ReviewQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    question: StrictStr = Field(min_length=1, max_length=2000)
    blocking: bool
    rationale: StrictStr = Field(min_length=1, max_length=2000)
    refs: list[StrictStr] = Field(min_length=1, max_length=12)


class ReviewCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: StrictStr = Field(min_length=1, max_length=300)
    oracle: OracleInput
    refs: list[StrictStr] = Field(min_length=1, max_length=12)


class ReviewCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dimension: Literal["roles", "preconditions", "inputs_outputs", "errors", "verifiability", "conflicts"]
    assessment: StrictStr = Field(min_length=1, max_length=2000)
    refs: list[StrictStr] = Field(min_length=1, max_length=12)


class RequirementAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    summary: StrictStr = Field(min_length=1, max_length=3000)
    checks: list[ReviewCheck] = Field(min_length=6, max_length=6)
    questions: list[ReviewQuestion] = Field(max_length=16)
    suggestions: list[StrictStr] = Field(max_length=16)
    criteria: list[ReviewCriterion] = Field(max_length=24)

    def validate_refs(self, allowed):
        texts = [self.summary, *self.suggestions, *(item.assessment for item in self.checks),
            *(item.question for item in self.questions), *(item.rationale for item in self.questions),
            *(item.title for item in self.criteria)]
        if any(not text.strip() for text in texts):
            raise ValueError("Requirement assessment contains empty review content")
        if len({item.dimension for item in self.checks}) != 6:
            raise ValueError("Requirement assessment must cover all six review dimensions")
        for item in [*self.checks, *self.questions, *self.criteria]:
            if not set(item.refs) <= allowed:
                raise ValueError("Requirement assessment cites unknown evidence")
        if not self.criteria and not any(item.blocking for item in self.questions):
            raise ValueError("A review without acceptance criteria must request clarification")
        if len({item.question.strip() for item in self.questions}) != len(self.questions):
            raise ValueError("Requirement assessment repeats clarification questions")
        return self
