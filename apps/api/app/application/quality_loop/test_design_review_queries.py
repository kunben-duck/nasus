from typing import Annotated, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


REVIEW_DRAFT_QUERY_TOOL = "query.quality.test_design_review_drafts"
ReviewId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]


class ReviewDraftListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str = Field(min_length=1, max_length=128)
    after_id: str = Field(default="", max_length=128)
    limit: int = Field(default=3, ge=1, le=5)


class ReviewDraftListReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: ReviewDraftListInput
    generation_ids: Tuple[ReviewId, ...] = Field(max_length=5)
    page_digest: Annotated[str, StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")]
    next_after_id: Optional[ReviewId]
    observation: Literal["review_draft_page_requires_revalidation"] = "review_draft_page_requires_revalidation"
    generation_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def page_boundaries(self):
        if (len(self.generation_ids) > self.request.limit or tuple(sorted(set(self.generation_ids))) != self.generation_ids
                or any(ident <= self.request.after_id for ident in self.generation_ids)
                or self.next_after_id is not None and
                    (len(self.generation_ids) != self.request.limit or self.next_after_id != self.generation_ids[-1])):
            raise ValueError("draft receipt must preserve the exact page and cursor")
        return self
