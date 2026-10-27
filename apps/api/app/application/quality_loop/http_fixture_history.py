"""Project-wide original-command discovery through current source/recipe ports."""
from typing import Literal, Optional, Protocol, Tuple

from pydantic import Field, StrictInt, model_serializer, model_validator

from ..platform.tool_handlers.query_input import query_payload
from .http_fixture_execution import HttpFixtureExecutionSelection
from .http_fixture_grants import HttpFixtureGrantRequest
from .test_design_output import Digest, GenerationValue, Id
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_command import FIXTURE_CANCEL_TOOL, FIXTURE_COMMAND_TOOL
from ...domain.quality_loop.http_fixture_grant import GRANT_TOOL
from ...domain.quality_loop.http_fixture_history import (
    FIXTURE_HISTORY_SCHEMA, FIXTURE_HISTORY_OBSERVATION, FIXTURE_HISTORY_STAGES, validate_history_inventory,
)
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid


class HttpFixtureHistoryQuery(GenerationValue):
    project_id: Id
    after_id: str = Field(default="", max_length=128, strict=True)
    limit: StrictInt = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def bounded_cursor(self):
        if any(ord(char) < 32 or ord(char) == 127 for char in self.after_id):
            raise ValueError("invalid original command cursor")
        return self


class HttpFixtureHistoryTarget(GenerationValue):
    project_id: Id
    invocation_id: Id


class HttpFixtureHistoryItem(GenerationValue):
    project_id: Id
    invocation_id: Id
    tool_id: Literal["quality.http_fixture.authorize", "quality.http_fixture.execute", "quality.http_fixture.cancel"]
    stage: Literal["grant", "execute", "cancel"]
    status: Literal["pending", "running", "waiting_confirmation", "waiting_approval", "completed", "failed", "cancelled"]
    request_digest: Digest
    recipe_id: Id
    recipe_artifact_hash: Digest
    run_plan_id: Id
    run_plan_artifact_hash: Digest
    case_id: Id
    attempt_id: Id
    operation: Literal["setup", "cleanup"]
    original_execution_id: Optional[Id] = None
    grant_id: Optional[Id] = None
    grant_digest: Optional[Digest] = None
    observation: Literal["original_command_metadata_not_target_observation"] = FIXTURE_HISTORY_OBSERVATION
    execution_authorized: Literal[False] = False
    canonical_execution_committed: Literal[False] = False
    business_coverage_verified: Literal[False] = False
    baseline_restored: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def no_authority(cls, value):
        if isinstance(value, dict) and any(value.get(key, False) is not False for key in
                ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored")):
            raise ValueError("command discovery cannot convey operation authority")
        return value

    @model_validator(mode="after")
    def exact_stage(self):
        if (FIXTURE_HISTORY_STAGES[self.tool_id] != self.stage
                or self.stage == "grant" and any(value is not None for value in
                    (self.original_execution_id, self.grant_id, self.grant_digest))
                or self.stage != "grant" and any(value is None for value in
                    (self.original_execution_id, self.grant_id, self.grant_digest))
                or self.stage == "execute" and self.original_execution_id != self.invocation_id):
            raise ValueError("fixture history must retain its original command stage and ancestry")
        return self


class HttpFixtureHistoryPage(GenerationValue):
    schema_version: Literal["nasus.http-fixture-operation-history.v1"] = Field(default=FIXTURE_HISTORY_SCHEMA, alias="schema")
    request: HttpFixtureHistoryQuery
    items: Tuple[HttpFixtureHistoryItem, ...] = Field(max_length=5)
    total: StrictInt = Field(ge=0)
    next_after_id: Optional[Id]
    source_scope_digest: Digest
    observation: Literal["original_command_metadata_not_target_observation"] = FIXTURE_HISTORY_OBSERVATION
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
    def exact_page(self):
        validate_history_inventory([item.model_dump(mode="json") for item in self.items], self.total,
            self.request.after_id, self.request.limit, self.next_after_id)
        return self


class HttpFixtureHistoryRepositoryPort(Protocol):
    def list_history(self, request, *, binding_ids): ...
    def read_history(self, project_id, invocation_id, *, binding_ids): ...


class HttpFixtureHistoryApplicationService:
    def __init__(self, jobs, repository: HttpFixtureHistoryRepositoryPort):
        self.jobs, self.repository, self.grants = jobs, repository, jobs.grants

    @staticmethod
    def _selection(command):
        if (type(command) is not dict or set(command) != {"id", "tool_id", "status", "input_payload"}
                or type(command["input_payload"]) is not dict):
            raise HttpFixtureInvalid("fixture history requires an exact original command snapshot")
        payload = query_payload(command["input_payload"])
        return {key: value for key, value in payload.items() if key not in {"confirmed_by_user", "confirmed_at"}}

    def _item(self, project_id, row):
        from .http_fixture_jobs import HttpFixtureJobTarget

        if type(row) is not dict or set(row) != {"command", "execution", "recipe_id", "recipe_artifact_hash"}:
            raise HttpFixtureInvalid("fixture history lost its original parent inventory")
        command = row["command"]
        self._selection(command)
        stage = FIXTURE_HISTORY_STAGES.get(command.get("tool_id"))
        if stage is None:
            raise HttpFixtureInvalid("fixture history cannot adopt another tool")
        value = self._selection(command)
        grant_id = grant_digest = original_id = None
        if stage == "grant":
            request = HttpFixtureGrantRequest.model_validate(value)
            if row["execution"] is not None:
                raise HttpFixtureInvalid("grant discovery cannot invent an execution")
            # Resolve historical inputs without renewing consent or requiring a live target.
            self.grants.inspect_history_request(request)
        else:
            execution = command if stage == "execute" else row["execution"]
            if stage == "execute" and row["execution"] is not None:
                raise HttpFixtureInvalid("execution discovery cannot replace its command")
            if stage == "cancel":
                target = HttpFixtureJobTarget.model_validate(value)
                if target.project_id != project_id or execution is None or execution.get("id") != target.invocation_id:
                    raise HttpFixtureInvalid("cancellation discovery lost its exact original execution")
            if execution.get("tool_id") != FIXTURE_COMMAND_TOOL:
                raise HttpFixtureInvalid("fixture history target is not an original execution")
            selected = HttpFixtureExecutionSelection.model_validate(self._selection(execution))
            if selected.project_id != project_id:
                raise HttpFixtureInvalid("fixture history cannot read another project's original selection")
            inputs = self.grants.execution_inputs(selected, live=False)
            grant_id, grant_digest, original_id = selected.grant_id, selected.grant_digest, execution["id"]
            request = self.grants.history_request(project_id, grant_id)
            if inputs.selection != selected:
                raise HttpFixtureInvalid("fixture history changed its original selection")
        if (request.project_id != project_id or request.recipe_id != row["recipe_id"]
                or request.recipe_artifact_hash != row["recipe_artifact_hash"]):
            raise HttpFixtureInvalid("fixture history scope or original recipe differs")
        recipe = self.grants.recipes.read(project_id, request.recipe_id)["metadata"]
        if (recipe["project_id"] != project_id or recipe["record_id"] != request.recipe_id
                or recipe["artifact_hash"] != request.recipe_artifact_hash):
            raise HttpFixtureInvalid("fixture history needs its complete original recipe archive")
        return HttpFixtureHistoryItem(project_id=project_id, invocation_id=command["id"], tool_id=command["tool_id"], stage=stage,
            status=command["status"], request_digest=acceptance_digest({"tool_id": command["tool_id"], "input_payload": command["input_payload"]}),
            recipe_id=request.recipe_id, recipe_artifact_hash=request.recipe_artifact_hash,
            run_plan_id=recipe["run_plan_id"], run_plan_artifact_hash=recipe["run_plan_artifact_hash"], case_id=recipe["case_id"],
            attempt_id=request.attempt_id, operation=request.operation, original_execution_id=original_id,
            grant_id=grant_id, grant_digest=grant_digest)

    def list(self, request: HttpFixtureHistoryQuery):
        request = HttpFixtureHistoryQuery.model_validate(request.model_dump(mode="json"))
        with self.grants.recipes.verified_read_session():
            access = self.jobs._access(request.project_id)
            raw = self.repository.list_history(request, binding_ids=tuple(sorted(access.binding_ids)))
            if (type(raw) is not dict or set(raw) != {"items", "total", "next_after_id", "lookahead"}
                    or type(raw["items"]) is not list or type(raw["lookahead"]) is not list
                    or len(raw["items"]) > request.limit or len(raw["lookahead"]) > 1):
                raise HttpFixtureInvalid("fixture history repository must preserve its exact page")
            items = tuple(self._item(request.project_id, row) for row in raw["items"])
            if raw["lookahead"]:
                lookahead = self._item(request.project_id, raw["lookahead"][0])
                if (len(items) != request.limit or lookahead.invocation_id <= items[-1].invocation_id
                        or type(raw["total"]) is not int or raw["total"] < len(items) + 1
                        or raw["next_after_id"] != items[-1].invocation_id):
                    raise HttpFixtureInvalid("fixture history look-ahead is not its exact next original command")
            elif raw["next_after_id"] is not None:
                raise HttpFixtureInvalid("fixture history cannot invent another page")
            page = HttpFixtureHistoryPage(request=request, items=items, total=raw["total"], next_after_id=raw["next_after_id"],
                source_scope_digest=access.fingerprint)
            self.grants.authorization.require_current(access)
            return page

    def read(self, target: HttpFixtureHistoryTarget):
        target = HttpFixtureHistoryTarget.model_validate(target.model_dump(mode="json"))
        with self.grants.recipes.verified_read_session():
            access = self.jobs._access(target.project_id)
            row = self.repository.read_history(target.project_id, target.invocation_id, binding_ids=tuple(sorted(access.binding_ids)))
            item = self._item(target.project_id, row)
            if item.invocation_id != target.invocation_id:
                raise HttpFixtureInvalid("fixture history cannot replace the requested original command")
            self.grants.authorization.require_current(access)
            return item

    def verify_receipt(self, request, receipt):
        expected = HttpFixtureHistoryPage if isinstance(request, HttpFixtureHistoryQuery) else HttpFixtureHistoryItem
        if type(receipt) is not dict or set(receipt) != {field.alias or key for key, field in expected.model_fields.items()}:
            raise HttpFixtureInvalid("fixture history receipt must preserve every original metadata field")
        if isinstance(request, HttpFixtureHistoryQuery):
            value = HttpFixtureHistoryPage.model_validate(receipt)
            original = self.list(request)
        else:
            value = HttpFixtureHistoryItem.model_validate(receipt)
            original = self.read(request)
        if original != value:
            raise HttpFixtureInvalid("fixture history observation changed; inspect the original commands again")
