"""Fenced HTTP case worker; public command/Temporal orchestration is separate."""
import base64
from copy import deepcopy
from dataclasses import asdict, fields
import json
from threading import Event
from typing import Protocol
from uuid import uuid4

from .generation_work_lease import run_with_generation_lease
from .runner_port import AutomationRunnerCommand, FixtureBoundHttpCommand, AutomationRunnerResult, RunnerArtifact, OwnedTargetHttpExecution
from .worker_threads import run_worker_thread
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_bindings import HTTP_FIXTURE_RECEIPT_SCHEMA
from ...domain.quality_loop.http_fixture_binding_input import fixture_input_parts
from ...domain.quality_loop.run_plan_case_execution import (
    RunPlanCaseExecutionInvalid, RunPlanCaseWorkLost, RunPlanCaseAlreadyClaimed,
    RunPlanCaseScope, FixtureBoundRunPlanCaseScope, restore_case_scope, case_execution_jobs, case_job_digest,
    execution_roster, execution_state,
)
from ...domain.quality_loop.run_plan_observations import map_case_observation


CASE_ARCHIVE_SCHEMA = "nasus.run-plan-case-native-archive.v1"
CASE_FIXTURE_ARCHIVE_SCHEMA = "nasus.run-plan-case-native-archive.v2"
MAX_CASE_ARCHIVE_BYTES = 80 * 1024 * 1024


class RunPlanCaseJournalPort(Protocol):
    def acquire(self, scope, roster, owner_id, *, require_current): ...
    def require(self, lease, *, require_current): ...
    def renew(self, lease, *, require_current): ...
    def inspect(self, scope, roster, *, require_access): ...
    def claim(self, lease, case, *, require_current): ...
    def complete(self, lease, claim, *, artifact_ref, artifact_hash, observation, require_current): ...


class RunPlanCaseArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, artifact_ref, artifact_hash): ...


class RunPlanCaseNativeVerifierPort(Protocol):
    def verify(self, command, execution, *, environment_id, inventory_hash): ...
    def verify_input(self, command): ...


class RunPlanCaseExecutionApplicationService:
    """Independent authority/current ancestry guard is mandatory, not a worker lease."""
    def __init__(self, runner, verifier: RunPlanCaseNativeVerifierPort,
                 journal: RunPlanCaseJournalPort, artifacts: RunPlanCaseArtifactPort):
        self.runner, self.verifier, self.journal, self.artifacts = runner, verifier, journal, artifacts

    @staticmethod
    def _commands(plan, scope, fixture_inputs=None):
        jobs = case_execution_jobs(plan, scope)
        bound = isinstance(scope, FixtureBoundRunPlanCaseScope)
        if not bound and any(item["receipt_protocol"] == HTTP_FIXTURE_RECEIPT_SCHEMA for item in jobs):
            raise RunPlanCaseExecutionInvalid("fixture-bound case execution requires original setup handoff before claim")
        if (bound and (type(fixture_inputs) is not tuple or len(fixture_inputs) != len(jobs))
                or not bound and fixture_inputs is not None):
            raise RunPlanCaseExecutionInvalid("case worker requires the complete original protocol-specific handoff")
        commands = {}
        for index, item in enumerate(jobs):
            args = dict(job_id=item["job_id"], project_id=item["project_id"], us_id=item["us_id"], base_url=item["base_url"],
                steps=tuple(item["steps"]), timeout_ms=item["timeout_ms"], metadata=deepcopy(item["metadata"]),
                kind="http", http_protocol=item["receipt_protocol"])
            if bound:
                value = deepcopy(fixture_inputs[index])
                pin = scope.fixture_input_pins[index]
                if acceptance_digest(value) != pin["fixture_input_digest"]:
                    raise RunPlanCaseExecutionInvalid("case worker cannot replace original fixture bytes or values")
                capsule = fixture_input_parts(value, project_id=scope.project_id, case_id=item["us_id"],
                    base_url=item["base_url"], metadata=item["metadata"])[0]
                if (capsule.digest != pin["capture_set_digest"] or capsule.scope_digest != scope.base_scope.digest
                        or capsule.setup_invocation_id != scope.selection["fixture_setups"][index]["invocation_id"]
                        or any(getattr(capsule, key) != getattr(scope, key) for key in
                            ("run_plan_id", "run_plan_artifact_hash", "plan_digest", "environment_id", "target_artifact_hash", "inventory_hash"))):
                    raise RunPlanCaseExecutionInvalid("case worker cannot substitute original setup or native target ancestry")
                command = FixtureBoundHttpCommand(**args, fixture_input=value)
            else:
                command = AutomationRunnerCommand(**args)
            commands[item["metadata"]["case_id"]] = (item, command)
        return commands

    def _verified_commands(self, plan, scope, fixture_inputs):
        commands = self._commands(plan, scope, fixture_inputs)
        if isinstance(scope, FixtureBoundRunPlanCaseScope):
            for _, command in commands.values():
                self.verifier.verify_input(command)
        return commands

    def _observation(self, plan, scope, job, command, execution):
        if not isinstance(execution, OwnedTargetHttpExecution):
            raise RunPlanCaseExecutionInvalid("case worker requires the original typed native wire output")
        receipt = self.verifier.verify(command, execution, environment_id=scope.environment_id,
            inventory_hash=scope.inventory_hash)
        return map_case_observation(plan, job, receipt,
            **({"fixture_input": command.fixture_input} if isinstance(command, FixtureBoundHttpCommand) else {}))

    def _archive(self, plan, scope, job, command, execution):
        observed = self._observation(plan, scope, job, command, execution)
        bound = isinstance(scope, FixtureBoundRunPlanCaseScope)
        value = {"schema": CASE_FIXTURE_ARCHIVE_SCHEMA if bound else CASE_ARCHIVE_SCHEMA, "scope_digest": scope.digest,
            **({"fixture_input": deepcopy(command.fixture_input)} if bound else {}),
            "command_digest": case_job_digest(job, scope), "result": asdict(execution.result),
            "request_body": base64.b64encode(execution.request_body).decode("ascii"),
            "result_body": base64.b64encode(execution.result_body).decode("ascii"),
            "environment_id": execution.environment_id, "inventory_hash": execution.inventory_hash,
            "observation": observed}
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_CASE_ARCHIVE_BYTES:
            raise RunPlanCaseExecutionInvalid("complete native case archive exceeds its byte budget")
        return value

    def _read_archive(self, plan, scope, job, command, outcome):
        value = self.artifacts.read(scope.project_id, outcome["artifact_ref"], outcome["artifact_hash"])
        try:
            bound = isinstance(scope, FixtureBoundRunPlanCaseScope)
            if (type(value) is not dict or set(value) != {"schema", "scope_digest", "command_digest", "result",
                    "request_body", "result_body", "environment_id", "inventory_hash", "observation", *({"fixture_input"} if bound else set())}
                    or value["schema"] != (CASE_FIXTURE_ARCHIVE_SCHEMA if bound else CASE_ARCHIVE_SCHEMA)
                    or bound and value["fixture_input"] != command.fixture_input
                    or acceptance_digest(value) != outcome["artifact_hash"]
                    or value["scope_digest"] != scope.digest or value["command_digest"] != case_job_digest(job, scope)
                    or len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_CASE_ARCHIVE_BYTES):
                raise RunPlanCaseExecutionInvalid("case archive lost its exact original scope or bytes")
            result = value["result"]
            if type(result) is not dict or set(result) != {item.name for item in fields(AutomationRunnerResult)}:
                raise RunPlanCaseExecutionInvalid("case archive result contains unverified fields")
            if type(result["artifacts"]) not in {tuple, list} or type(result["timeline"]) not in {tuple, list}:
                raise RunPlanCaseExecutionInvalid("case archive requires complete native artifact and timeline arrays")
            original = AutomationRunnerResult(**{**result, "timeline": tuple(result["timeline"]),
                "artifacts": tuple(RunnerArtifact(**item) for item in result["artifacts"])})
            execution = OwnedTargetHttpExecution(original,
                base64.b64decode(value["request_body"], validate=True),
                base64.b64decode(value["result_body"], validate=True), value["environment_id"], value["inventory_hash"])
            observed = self._observation(plan, scope, job, command, execution)
            if (observed != value["observation"] or observed["observation_digest"] != outcome["observation_digest"]
                    or observed["status"] != outcome["status"]):
                raise RunPlanCaseExecutionInvalid("case archive differs from original actions or oracles")
            return observed
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
            raise RunPlanCaseExecutionInvalid("case native archive cannot be completely reverified") from None

    def read(self, plan, scope, *, require_access, fixture_inputs=None):
        roster = execution_roster(plan, scope)
        require_access()
        history = self.journal.inspect(scope, roster, require_access=require_access)
        state = execution_state(scope, roster, history["claims"], history["outcomes"], cancelled=history["cancelled"])
        commands, observations = self._verified_commands(plan, scope, fixture_inputs), []
        for outcome in history["outcomes"]:
            require_access()
            job, command = commands[outcome["case_id"]]
            observations.append(self._read_archive(plan, scope, job, command, outcome))
        # A changing journal is not a stable receipt; repeat the same original read.
        if self.journal.inspect(scope, roster, require_access=require_access) != history:
            raise RunPlanCaseWorkLost("original case history changed during verification; read the same run again")
        require_access()
        return {"state": state, "observations": observations, "historical_not_live": True}

    def _execute(self, plan, scope, lease, require_work, require_current, fixture_inputs=None):
        roster, commands = execution_roster(plan, scope), self._verified_commands(plan, scope, fixture_inputs)
        initial = self.read(plan, scope, require_access=require_work, fixture_inputs=fixture_inputs)
        if initial["state"]["state"] in {"outcome_unknown", "cancelled", "observed"}:
            return initial
        observed_ids = {item["case_id"] for item in initial["observations"]}
        for case in roster:
            if case["case_id"] in observed_ids:
                continue
            require_work()
            try:
                # The journal owns its transaction/lease fence; do not reenter it from its guard.
                claim = self.journal.claim(lease, case, require_current=require_current)
            except RunPlanCaseAlreadyClaimed:
                return self.read(plan, scope, require_access=require_work, fixture_inputs=fixture_inputs)
            require_work()
            job, command = commands[case["case_id"]]
            try:
                execution = self.runner.execute_owned_http(command, environment_id=scope.environment_id,
                    artifact_hash=scope.target_artifact_hash, inventory_hash=scope.inventory_hash,
                    require_work=require_work)
                archive = self._archive(plan, scope, job, command, execution)
            except Exception:
                # No fake Runner result or automatic retry after a committed claim.
                require_work()
                return self.read(plan, scope, require_access=require_work, fixture_inputs=fixture_inputs)
            require_work()
            ref, digest = self.artifacts.put(scope.project_id, archive)
            require_work()
            if digest != acceptance_digest(archive):
                raise RunPlanCaseExecutionInvalid("native case archive write returned a different digest")
            provisional = {"artifact_ref": ref, "artifact_hash": digest,
                "observation_digest": archive["observation"]["observation_digest"], "status": archive["observation"]["status"]}
            observed = self._read_archive(plan, scope, job, command, provisional)
            require_work()
            self.journal.complete(lease, claim, artifact_ref=ref, artifact_hash=digest,
                observation=observed, require_current=require_current)
        return self.read(plan, scope, require_access=require_work, fixture_inputs=fixture_inputs)

    async def execute(self, plan, scope: RunPlanCaseScope, *, require_current, renew_seconds=15, fixture_inputs=None):
        """The caller verifies the exact independently confirmed command and prerequisites."""
        plan, scope, fixture_inputs = deepcopy(plan), restore_case_scope(asdict(scope)), deepcopy(fixture_inputs)
        roster, stopped = execution_roster(plan, scope), Event()
        self._verified_commands(plan, scope, fixture_inputs)
        if type(renew_seconds) not in {int, float} or not 0 < renew_seconds < 45:
            raise RunPlanCaseExecutionInvalid("case worker heartbeat must be bounded below the lease lifetime")

        def current():
            if stopped.is_set():
                raise RunPlanCaseWorkLost("original case worker stopped; no more dispatch or commit")
            require_current()
            if stopped.is_set():
                raise RunPlanCaseWorkLost("original case worker stopped during authorization")

        journal = self.journal

        class Heartbeat:
            def require_lease(self, lease):
                current()
                journal.require(lease, require_current=current)
                current()

            def renew_lease(self, lease):
                journal.renew(lease, require_current=current)

        try:
            lease = await run_worker_thread(lambda: journal.acquire(scope, roster, uuid4().hex,
                require_current=current), on_cancel=stopped.set)

            async def operation(require_work):
                return await run_worker_thread(lambda: self._execute(plan, scope, lease, require_work, current,
                    **({"fixture_inputs": fixture_inputs} if fixture_inputs is not None else {})),
                    on_cancel=stopped.set)

            return await run_with_generation_lease(Heartbeat(), lease, operation, renew_seconds=renew_seconds)
        finally:
            stopped.set()
