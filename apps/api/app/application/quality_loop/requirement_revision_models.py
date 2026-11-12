from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator, field_validator


REVISE_REQUIREMENT = "quality.requirement.revise"
READ_REQUIREMENTS = "query.quality.requirements"


class RequirementSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    version_id: StrictStr = Field(min_length=1, max_length=128)


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    question: StrictStr = Field(min_length=1, max_length=2000)
    answer: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("question", "answer")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("clarification must not be blank")
        return value


class RequirementRevisionInput(RequirementSelection):
    us_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    expected_revision_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    title: StrictStr = Field(min_length=1, max_length=200)
    text: StrictStr = Field(min_length=1, max_length=16000)
    clarification_answers: tuple[ClarificationAnswer, ...] = Field(default=(), max_length=32)

    @field_validator("title", "text")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("requirement must not be blank")
        return value

    @model_validator(mode="after")
    def exact_parent(self):
        if bool(self.us_id) != bool(self.expected_revision_id):
            raise ValueError("editing requires both us_id and expected_revision_id")
        questions = [answer.question.strip() for answer in self.clarification_answers]
        if len(set(questions)) != len(questions):
            raise ValueError("duplicate clarification questions")
        return self


class RequirementRevisionView(RequirementSelection):
    revision_id: str
    us_id: str
    sequence: int
    previous_revision_id: Optional[str]
    image_revision_id: str
    image_artifact_hash: str
    title: str
    text: str
    original_text: str
    clarification_answers: tuple[ClarificationAnswer, ...]
    actor_id: str
    invocation_id: str
    recorded_at: str
    content_hash: str
    status: Literal["draft"] = "draft"
    generation_authorized: Literal[False] = False


class RequirementRevisionPage(RequirementSelection):
    items: list[RequirementRevisionView]
    next_offset: Optional[int] = None
    # Intake is not a semantic evaluation, source projection, or human approval.
    blockers: list[str] = Field(default_factory=lambda: ["requirement_semantic_review_pending"])
