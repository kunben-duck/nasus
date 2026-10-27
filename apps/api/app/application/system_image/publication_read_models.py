from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PublishedImagePin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    publication_id: str
    baseline_id: str
    image_revision_id: str
    image_artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_id: str
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sequence: int = Field(ge=1)
    quality_generation_authorized: Literal[False] = False
    release_authorized: Literal[False] = False


class ImageReadState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["legacy_draft", "working_draft", "published", "unpublished"] = "legacy_draft"
    pin: Optional[PublishedImagePin] = None
    version_id: Optional[str] = None

    @model_validator(mode="after")
    def require_exact_pin(self):
        if (self.mode == "published") != (self.pin is not None):
            raise ValueError("Only published reads have an exact publication pin")
        return self
