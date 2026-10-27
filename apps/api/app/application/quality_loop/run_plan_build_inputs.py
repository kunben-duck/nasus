from typing import Literal, Tuple

from pydantic import Field, model_validator

from .test_design_output import GenerationValue, Id, Digest, Text


class RunPlanNativeBuildReference(GenerationValue):
    invocation_id: Id
    build_id: Id
    receipt_digest: Digest
    artifact_hash: Digest


class RunPlanBuildSelection(GenerationValue):
    project_id: Id
    run_plan_id: Id
    run_plan_artifact_hash: Digest
    native_builds: Tuple[RunPlanNativeBuildReference, ...] = Field(min_length=1, max_length=1000)
    target_build_invocation_id: Id
    reason: Text
    policy_revision: Literal["nasus.run-plan-build.v1"] = "nasus.run-plan-build.v1"

    @model_validator(mode="after")
    def distinct_builds(self):
        if (len({item.invocation_id for item in self.native_builds}) != len(self.native_builds)
                or len({item.build_id for item in self.native_builds}) != len(self.native_builds)
                or self.target_build_invocation_id not in {item.invocation_id for item in self.native_builds}):
            raise ValueError("distinct original builds and an explicit member target are required")
        return self


class RunPlanBuildRequest(RunPlanBuildSelection):
    binding_digest: Digest
    source_scope_digest: Digest

    def selection(self):
        return RunPlanBuildSelection(**{key: getattr(self, key) for key in RunPlanBuildSelection.model_fields})


class RunPlanBuildQuery(GenerationValue):
    project_id: Id
    binding_id: Id
