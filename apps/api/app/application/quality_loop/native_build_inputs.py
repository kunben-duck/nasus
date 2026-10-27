from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...domain.shared.native_build_source import build_path

NATIVE_BUILD_TOOL = "quality.native_build.prepare"
NATIVE_BUILD_PREVIEW_TOOL = "query.quality.native_build_preview"
NATIVE_BUILD_QUERY_TOOL = "query.quality.native_build"
NATIVE_BUILD_CANCEL_TOOL = "quality.native_build.cancel"
ID = Field(min_length=1, max_length=128, pattern=r"^[^\x00-\x20\x7f]+$")
HASH = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class NativeBuildSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = ID
    image_revision_id: str = ID
    image_artifact_hash: str = HASH
    binding_id: str = ID
    source_revision_id: str = ID
    artifact_path: str = Field(min_length=1, max_length=1024)
    expected_artifact_hash: Optional[str] = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("artifact_path")
    @classmethod
    def safe_artifact(cls, value):
        build_path(value)
        if not value.startswith("target/") or not value.endswith(".jar"):
            raise ValueError("native artifact must be a target JAR")
        return value


class NativeBuildCommand(NativeBuildSelection):
    request_digest: str = HASH
    operator_policy_digest: str = HASH
    source_scope_digest: str = HASH

    def selection(self):
        return NativeBuildSelection(**{name: getattr(self, name) for name in NativeBuildSelection.model_fields})


class NativeBuildTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = ID
    invocation_id: str = ID


class NativeBuildOutcomeUnknown(ValueError):
    pass
