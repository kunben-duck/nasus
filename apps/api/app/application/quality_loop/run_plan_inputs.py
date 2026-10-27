from typing import Annotated, Literal, Tuple
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, model_validator

from .test_design_output import GenerationValue, Id, Digest, Text


class RunPlanCodeSource(GenerationValue):
    binding_id: Id
    source_revision_id: Id


class TargetBuildDeclaration(GenerationValue):
    code_sources: Tuple[RunPlanCodeSource, ...] = Field(min_length=1, max_length=1000)
    artifact_name: Id
    artifact_hash: Digest
    build_definition_hash: Digest
    runtime: Id
    runtime_version: Id
    build_tool: Id
    build_tool_version: Id

    @model_validator(mode="after")
    def distinct_sources(self):
        if len({pin.binding_id for pin in self.code_sources}) != len(self.code_sources):
            raise ValueError("duplicate target code source")
        return self


class TargetEnvironmentDeclaration(GenerationValue):
    environment_id: Id
    kind: Literal["local", "test", "staging"]
    base_url: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)]
    inventory_hash: Digest
    isolation: Text

    @model_validator(mode="after")
    def secretless_origin(self):
        try:
            parsed = urlsplit(self.base_url)
            port = parsed.port
        except ValueError:
            raise ValueError("invalid target origin") from None
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or port is not None and not 1 <= port <= 65535 or any(ord(char) <= 32 for char in self.base_url)
                or "\\" in self.base_url):
            raise ValueError("target declaration requires a credential-free HTTP origin; no request is executed")
        return self


class CaseFixtureDeclaration(GenerationValue):
    case_id: Id
    preconditions_digest: Digest
    data_manifest_hash: Digest
    setup: Tuple[Text, ...] = Field(min_length=1, max_length=64)
    cleanup: Tuple[Text, ...] = Field(min_length=1, max_length=64)


class RunPlanCommandScope(GenerationValue):
    project_id: Id
    script_revision_id: Id
    script_artifact_hash: Digest
    review_revision_id: Id
    review_artifact_hash: Digest


class RunPlanSelection(RunPlanCommandScope):
    target_build: TargetBuildDeclaration
    environment: TargetEnvironmentDeclaration
    fixtures: Tuple[CaseFixtureDeclaration, ...] = Field(min_length=1, max_length=512)
    reason: Text
    policy_revision: Literal["nasus.run-plan.v1", "nasus.run-plan.v2", "nasus.run-plan.v3"] = "nasus.run-plan.v1"

    @model_validator(mode="after")
    def distinct_fixtures(self):
        if len({item.case_id for item in self.fixtures}) != len(self.fixtures):
            raise ValueError("each selected case needs exactly one fixture declaration")
        return self


class RunPlanRequest(RunPlanSelection):
    plan_digest: Digest
    source_scope_digest: Digest

    def selection(self):
        return RunPlanSelection(**{key: getattr(self, key) for key in RunPlanSelection.model_fields})
