from typing import Protocol, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .test_design_generation import GenerationSelection
from .test_design_output import Digest, Id
from ...domain.quality_loop.automation_input import (
    AutomationInputChanged, AutomationInputInvalid, MAX_AUTOMATION_CASES, compile_automation_input, replay_automation_input,
)


class AutomationInputSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: Id
    mapping_revision_id: Id
    mapping_artifact_hash: Digest
    case_ids: Tuple[Id, ...] = Field(min_length=1, max_length=MAX_AUTOMATION_CASES)

    @model_validator(mode="after")
    def distinct_cases(self):
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("select each automation case exactly once")
        return self


class AutomationMappingPort(Protocol):
    def resolve(self, project_id, revision_id, artifact_hash): ...
    def read(self, project_id, revision_id): ...
    def resolve_with_result(self, project_id, revision_id, artifact_hash): ...
    def read_with_result(self, project_id, revision_id): ...


class AutomationCaseResultPort(Protocol):
    def read(self, project_id, generation_id): ...


class AutomationGenerationInputPort(Protocol):
    def prepare(self, selection: GenerationSelection): ...
    def replay(self, selection: GenerationSelection): ...


class AutomationInputApplicationService:
    """Read verified application ports, never mutable workspace or ORM facts."""

    def __init__(self, mappings: AutomationMappingPort, results: AutomationCaseResultPort,
                 generation: AutomationGenerationInputPort, authorization):
        self.mappings, self.results, self.generation, self.authorization = mappings, results, generation, authorization

    def _compile(self, request, *, historical=False):
        parent_reader = getattr(self.mappings, "read_with_result" if historical else "resolve_with_result", None)
        if callable(parent_reader):
            mapping, result = (parent_reader(request.project_id, request.mapping_revision_id) if historical else
                parent_reader(request.project_id, request.mapping_revision_id, request.mapping_artifact_hash))
        else:
            mapping = (self.mappings.read(request.project_id, request.mapping_revision_id) if historical else
                self.mappings.resolve(request.project_id, request.mapping_revision_id, request.mapping_artifact_hash))
        if mapping["revision"]["artifact_hash"] != request.mapping_artifact_hash:
            raise AutomationInputInvalid("automation mapping archive pin mismatch")
        pin = mapping["generation_pin"]
        if not callable(parent_reader):
            result = self.results.read(request.project_id, pin["generation_id"])
        scope = pin["scope_pin"]
        selection = GenerationSelection(project_id=request.project_id,
            scope_revision_id=scope["revision_id"], scope_artifact_hash=scope["artifact_hash"])
        prepared = self.generation.replay(selection) if historical else self.generation.prepare(selection)
        compile_input = replay_automation_input if historical else compile_automation_input
        return compile_input(prepared, result, mapping, request.case_ids)

    def replay(self, request: AutomationInputSelection):
        request = AutomationInputSelection.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        value = self._compile(request, historical=True)
        self.authorization.require_current(access)
        return value

    def prepare(self, request: AutomationInputSelection):
        request = AutomationInputSelection.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        value = self._compile(request)
        # Re-read current heads and source authority after collecting every case.
        # A preview is not an authorization lease for a later model or runner.
        if self._compile(request)["input_digest"] != value["input_digest"]:
            raise AutomationInputChanged("automation input changed during preparation")
        self.authorization.require_current(access)
        return value
