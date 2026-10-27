"""Resolve an existing authorized snapshot and target without capturing or writing."""
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.system_image.build_plan import BuildPlanIntegrityError, BuildTarget
from ...domain.system_image.image_revision import require_frozen_inputs
from .build_plans import BuildPlanApplicationService, BuildPlanInput, BuildTargetInput


class BuildPreparationRequired(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


class BuildPreparationInputPort(Protocol):
    def prepare(self, project_id, version_id, objective, mode) -> BuildPlanInput: ...
    def waiting_request(self, project_id, version_id, objective, mode): ...
    def prepare_fixed(self, request): ...


class BuildSourceWaitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    objective: StrictStr = Field(min_length=1, max_length=2000)
    mode: Literal["initialize", "enrich", "refresh", "repair"]
    target: BuildTargetInput


class BuildPreparationApplicationService:
    def __init__(self, plans: BuildPlanApplicationService, snapshots):
        self.plans, self.snapshots = plans, snapshots

    def prepare(self, project_id, version_id, objective, mode):
        return self.prepare_fixed(self.waiting_request(project_id, version_id, objective, mode))

    def waiting_request(self, project_id, version_id, objective, mode):
        scope = self.plans.authorization.scope(project_id)
        image = self.snapshots.get_system_image(project_id, working=True)
        choices = [baseline for baseline in image.baselines if baseline.project_id == project_id
            and (baseline.kind == "official" if version_id is None else
                 baseline.kind == "version_working" and baseline.source_version_id == version_id)]
        if len(choices) != 1:
            raise BuildPreparationRequired("target_baseline", "Select one image target in this project's Knowledge page before building; I will not guess a baseline or another version.")
        target = self.plans.target(project_id, choices[0].id)
        if target.target_version_id != version_id:
            raise BuildPreparationRequired("target_version", "The image target no longer matches this conversation's version. Reload the project before building.")
        self.plans.authorization.require_current(scope)
        return BuildSourceWaitInput(project_id=project_id, objective=objective, mode=mode,
            target=BuildTargetInput(**target.__dict__))

    def prepare_fixed(self, request: BuildSourceWaitInput):
        project_id = request.project_id
        scope = self.plans.authorization.scope(project_id)
        if request.target.project_id != project_id:
            raise BuildPlanIntegrityError("Waiting request target project mismatch.")
        self.plans.require_target_current(BuildTarget(**request.target.model_dump()))
        manifest = self.plans.manifests.latest_manifest(project_id)
        if manifest is None:
            raise BuildPreparationRequired("captured_code", "Add and capture a code source in this project's Knowledge page first. Requirements and historical tests are optional.")
        if manifest.project_id != project_id:
            raise BuildPlanIntegrityError("Build preparation manifest project mismatch.")
        for source in manifest.members:
            scope.require_binding(source.binding_id)
        code = [source for source in manifest.members if source.source_type == "code"]
        if not code or any(source.status != "captured" for source in code):
            raise BuildPreparationRequired("captured_code", "Capture the required code sources before continuing this goal. Requirements and historical tests are optional.")
        require_frozen_inputs(manifest)
        self.plans.authorization.require_current(scope)
        return BuildPlanInput(project_id=project_id, source_manifest_id=manifest.manifest_id,
            objective=request.objective, mode=request.mode, target=request.target)
