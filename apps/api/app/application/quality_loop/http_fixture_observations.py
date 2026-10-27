"""Read an original operation by project command ID, never a browser recovery key."""
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import Field, model_serializer, model_validator

from .http_fixture_execution import HttpFixtureExecutionSelection
from .http_fixture_history import HttpFixtureHistoryItem, HttpFixtureHistoryTarget
from .test_design_output import Digest, GenerationValue
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_observation import (
    FIXTURE_OBSERVATION_SCHEMA, FIXTURE_OBSERVATION_KIND, HttpFixtureObservationChanged, classify_original_observation,
)
from ...domain.quality_loop.http_fixtures import fixture_bindings


class HttpFixturePhasePin(GenerationValue):
    phase: str = Field(strict=True, min_length=1, max_length=136)
    claim_id: str = Field(strict=True, pattern=r"^fixture_[0-9a-f]{64}$")


class HttpFixtureOriginalObservation(GenerationValue):
    schema_version: Literal["nasus.http-fixture-original-observation.v1"] = Field(default=FIXTURE_OBSERVATION_SCHEMA, alias="schema")
    selected: HttpFixtureHistoryItem
    execution: Optional[HttpFixtureHistoryItem]
    expected_phases: Tuple[HttpFixturePhasePin, ...] = Field(max_length=16)
    job: Optional[Dict[str, Any]]
    state: Literal["not_execution", "not_confirmed", "preparing", "preparation_failed", "preparation_cancelled",
        "not_dispatched", "outcome_unknown", "observed", "partially_observed"]
    source_scope_digest: Digest
    observation: Literal["original_persisted_journal_not_live_target"] = FIXTURE_OBSERVATION_KIND
    execution_authorized: Literal[False] = False
    canonical_execution_committed: Literal[False] = False
    business_coverage_verified: Literal[False] = False
    baseline_restored: Literal[False] = False

    @model_serializer(mode="wrap")
    def wire_schema(self, handler):
        value = handler(self)
        if "schema_version" in value:
            value["schema"] = value.pop("schema_version")
        return value

    @model_validator(mode="before")
    @classmethod
    def no_authority(cls, value):
        return HttpFixtureHistoryItem.no_authority(value)

    @model_validator(mode="after")
    def complete_journal(self):
        state = classify_original_observation(self.selected.model_dump(mode="json"),
            self.execution.model_dump(mode="json") if self.execution else None,
            [pin.model_dump(mode="json") for pin in self.expected_phases], self.job)
        if state != self.state:
            raise ValueError("original journal classification differs")
        return self


class HttpFixtureObservationApplicationService:
    def __init__(self, jobs):
        self.jobs, self.history, self.grants = jobs, jobs.history, jobs.grants

    def read(self, target: HttpFixtureHistoryTarget):
        from .http_fixture_jobs import HttpFixtureJobTarget

        target = HttpFixtureHistoryTarget.model_validate(target.model_dump(mode="json"))
        with self.grants.recipes.verified_read_session():
            access = self.jobs._access(target.project_id)
            selected = self.history.read(target)
            execution = None if selected.stage == "grant" else self.history.read(
                HttpFixtureHistoryTarget(project_id=target.project_id, invocation_id=selected.original_execution_id))
            phases, job = [], None
            if execution and execution.status not in {"pending", "waiting_confirmation", "waiting_approval"}:
                selection = HttpFixtureExecutionSelection(project_id=execution.project_id,
                    grant_id=execution.grant_id, grant_digest=execution.grant_digest, operation=execution.operation)
                inputs = self.grants.execution_inputs(selection, live=False)
                names = ("setup",) if selection.operation == "setup" else tuple(
                    "cleanup:" + binding for binding in fixture_bindings(inputs.manifest))
                phases = [{"phase": phase, "claim_id": "fixture_" + acceptance_digest(
                    [target.project_id, inputs.scope.attempt_id, inputs.scope.case_id, phase]).removeprefix("sha256:")}
                    for phase in names]
                job = self.jobs.read(HttpFixtureJobTarget(project_id=target.project_id, invocation_id=execution.invocation_id))
            # A concurrent confirmation or terminal transition requires a fresh
            # explicit read of this same ID, never another dispatch/attempt.
            if self.history.read(target) != selected or execution and self.history.read(
                    HttpFixtureHistoryTarget(project_id=target.project_id, invocation_id=execution.invocation_id)) != execution:
                raise HttpFixtureObservationChanged("original command changed during journal inspection")
            state = classify_original_observation(selected.model_dump(mode="json"),
                execution.model_dump(mode="json") if execution else None, phases, job)
            result = HttpFixtureOriginalObservation(selected=selected, execution=execution,
                expected_phases=phases, job=job, state=state, source_scope_digest=access.fingerprint)
            self.grants.authorization.require_current(access)
            return result

    def verify_receipt(self, target, receipt):
        fields = {field.alias or key for key, field in HttpFixtureOriginalObservation.model_fields.items()}
        if type(receipt) is not dict or set(receipt) != fields:
            raise ValueError("original journal receipt omitted or added metadata")
        original = self.read(target)
        if original != HttpFixtureOriginalObservation.model_validate(receipt):
            raise HttpFixtureObservationChanged("original journal changed; inspect the same command again")
