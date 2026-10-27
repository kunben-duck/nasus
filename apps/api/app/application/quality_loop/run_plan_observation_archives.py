"""Private, physically reverified observations; not a canonical execution fact."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, fields
from typing import Protocol

from .runner_port import AutomationRunnerResult, RunnerArtifact
from .test_design_output import GenerationValue, Id, Digest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_observations import (
    RunPlanObservationInvalid, collect_run_plan_observations, collect_run_plan_attempt_observations,
)


OBSERVATION_ARCHIVE_SCHEMA = "nasus.run-plan-observation-archive.v1"
OBSERVATION_ATTEMPT_ARCHIVE_SCHEMA = "nasus.run-plan-observation-archive.v2"
OBSERVATION_ARCHIVE_SCHEMAS = frozenset({OBSERVATION_ARCHIVE_SCHEMA, OBSERVATION_ATTEMPT_ARCHIVE_SCHEMA})
MAX_OBSERVATION_ARCHIVE_BYTES = 32 * 1024 * 1024


class RunPlanObservationArchiveParent(GenerationValue):
    project_id: Id
    run_plan_id: Id
    run_plan_artifact_hash: Digest
    plan_digest: Digest


class RunPlanObservationArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class RunPlanObservationArchiveAccessPort(Protocol):
    def require_plan_access(self, project_id, plan_digest) -> RunPlanObservationArchiveParent: ...


class SavedRunPlanReadPort(Protocol):
    def read(self, project_id, run_plan_id): ...


class SavedRunPlanObservationArchiveAccess:
    """Reauthorize the exact saved plan through its existing application read port."""
    def __init__(self, plans: SavedRunPlanReadPort, parent: RunPlanObservationArchiveParent):
        self.plans = plans
        self.parent = RunPlanObservationArchiveParent.model_validate(parent.model_dump(mode="json"))

    def verified_read_session(self):
        read_session = getattr(self.plans, "verified_read_session", None)
        return read_session() if callable(read_session) else nullcontext()

    def require_plan_access(self, project_id, plan_digest):
        if project_id != self.parent.project_id or plan_digest != self.parent.plan_digest:
            raise RunPlanObservationInvalid("observation archive original plan scope differs")
        view = self.plans.read(project_id, self.parent.run_plan_id)
        try:
            metadata, artifact = view["metadata"], view["artifact"]
            if (metadata["project_id"] != project_id or metadata["run_plan_id"] != self.parent.run_plan_id
                    or metadata["artifact_hash"] != self.parent.run_plan_artifact_hash
                    or metadata["plan_digest"] != plan_digest
                    or artifact["project_id"] != project_id or artifact["run_plan_id"] != self.parent.run_plan_id
                    or artifact["plan"]["project_id"] != project_id or artifact["plan"]["plan_digest"] != plan_digest
                    or acceptance_digest(artifact) != self.parent.run_plan_artifact_hash):
                raise RunPlanObservationInvalid("saved observation parent was rebound")
        except (KeyError, TypeError, UnicodeError, RecursionError):
            raise RunPlanObservationInvalid("saved observation parent cannot be verified") from None
        return self.parent


class RunPlanObservationArchiveApplicationService:
    def __init__(self, observations, artifacts: RunPlanObservationArtifactPort,
                 access: RunPlanObservationArchiveAccessPort):
        self.observations, self.artifacts, self.access = observations, artifacts, access

    def _read_session(self):
        read_session = getattr(self.access, "verified_read_session", None)
        return read_session() if callable(read_session) else nullcontext()

    @staticmethod
    def _result(value):
        if type(value) is not dict or set(value) != {item.name for item in fields(AutomationRunnerResult)}:
            raise RunPlanObservationInvalid("original result fields are incomplete or unexpected")
        if (type(value["artifacts"]) not in {list, tuple} or len(value["artifacts"]) > 201
                or type(value["timeline"]) not in {list, tuple} or len(value["timeline"]) > 1024
                or any(type(value[key]) is not str or len(value[key]) > 4096 for key in
                    ("runner_job_id", "summary", "failure_summary", "started_at", "completed_at", "runner_mode"))
                or any(type(item) is not str or len(item) > 4096 for item in value["timeline"])):
            raise RunPlanObservationInvalid("original result metadata exceeds its bound")
        try:
            artifacts = tuple(RunnerArtifact(**item) for item in value["artifacts"])
        except (ValueError, TypeError):
            raise RunPlanObservationInvalid("original result artifacts cannot be decoded") from None
        if any(type(item.content_base64) is not str for item in artifacts):
            raise RunPlanObservationInvalid("original result artifact encoding is invalid")
        if (value["failure_fingerprint"] is not None and
                (type(value["failure_fingerprint"]) is not str or len(value["failure_fingerprint"]) > 128)):
            raise RunPlanObservationInvalid("original result failure identity is invalid")
        return AutomationRunnerResult(**{**value, "artifacts": artifacts, "timeline": tuple(value["timeline"])})

    @staticmethod
    def _parent(value, project_id, plan_digest):
        if not isinstance(value, RunPlanObservationArchiveParent):
            raise RunPlanObservationInvalid("archive access must return the exact saved parent")
        parent = RunPlanObservationArchiveParent.model_validate(value.model_dump(mode="json"))
        if parent.project_id != project_id or parent.plan_digest != plan_digest:
            raise RunPlanObservationInvalid("archive access parent scope differs")
        return parent

    def _compile(self, parent, plan, entries, *, run_id, timeout_ms):
        plan = deepcopy(plan)
        commands = self.observations.commands(plan, run_id=run_id, timeout_ms=timeout_ms)
        if type(entries) not in {list, tuple} or len(entries) > len(commands):
            raise RunPlanObservationInvalid("observations exceed the original case roster")
        by_job, encoded_bytes = {}, 0
        for entry in entries:
            if type(entry) is not dict or set(entry) != {"runner_job_id", "result"}:
                raise RunPlanObservationInvalid("original observation entry is invalid")
            result = self._result(entry["result"])
            if entry["runner_job_id"] != result.runner_job_id or result.runner_job_id in by_job:
                raise RunPlanObservationInvalid("observation jobs are duplicated or rebound")
            encoded_bytes += (sum(len(item.content_base64) for item in result.artifacts)
                + sum(len(item) for item in result.timeline) + len(result.summary) + len(result.failure_summary))
            if encoded_bytes > MAX_OBSERVATION_ARCHIVE_BYTES:
                raise RunPlanObservationInvalid("observation artifacts exceed the complete archive byte bound")
            by_job[result.runner_job_id] = result
        if set(by_job) - {item.job_id for item in commands}:
            raise RunPlanObservationInvalid("observation job is outside the original plan attempt")
        pairs = tuple((command, by_job[command.job_id]) for command in commands if command.job_id in by_job)
        observations, unknown = self.observations.observe_http_attempt_batch(plan, pairs, run_id=run_id, timeout_ms=timeout_ms)
        observations, unknown = list(observations), list(unknown)
        raw_results = [{"runner_job_id": command.job_id, "result": asdict(result)} for command, result in pairs]
        summary = (collect_run_plan_attempt_observations(plan, observations, unknown, run_id=run_id, timeout_ms=timeout_ms)
            if unknown else collect_run_plan_observations(plan, observations))
        value = {"schema": OBSERVATION_ATTEMPT_ARCHIVE_SCHEMA if unknown else OBSERVATION_ARCHIVE_SCHEMA, "project_id": plan["project_id"],
            "plan_digest": plan["plan_digest"], "run_id": run_id, "timeout_ms": timeout_ms,
            "original_run_plan": parent.model_dump(mode="json"),
            "plan": deepcopy(plan), "raw_results": raw_results, "observations": observations, "summary": summary,
            "execution_authorized": False, "target_build_verified": False, "business_coverage_verified": False,
            "canonical_execution_committed": False}
        if unknown:
            value["unverified_attempts"] = unknown
        return value

    def archive(self, plan, entries, *, run_id, timeout_ms):
        # Share only operation-local immutable source validation, not access decisions.
        with self._read_session():
            return self._archive(plan, entries, run_id=run_id, timeout_ms=timeout_ms)

    def _archive(self, plan, entries, *, run_id, timeout_ms):
        parent = self._parent(self.access.require_plan_access(plan["project_id"], plan["plan_digest"]), plan["project_id"], plan["plan_digest"])
        payload = self._compile(parent, plan, entries, run_id=run_id, timeout_ms=timeout_ms)
        if self.access.require_plan_access(plan["project_id"], plan["plan_digest"]) != parent:
            raise RunPlanObservationInvalid("original plan changed before archive upload")
        ref, digest = self.artifacts.put(plan["project_id"], payload)
        if acceptance_digest(payload) != digest:
            raise RunPlanObservationInvalid("observation archive write changed its complete content")
        # Verify the stored bytes rather than trusting a successful upload.
        self._read(plan["project_id"], ref, digest, plan_digest=plan["plan_digest"])
        return {"project_id": plan["project_id"], "plan_digest": plan["plan_digest"],
            "run_id": run_id, "artifact_ref": ref, "artifact_hash": digest,
            "summary": payload["summary"], "canonical_execution_committed": False}

    def read(self, project_id, ref, digest, *, plan_digest):
        with self._read_session():
            return self._read(project_id, ref, digest, plan_digest=plan_digest)

    def _read(self, project_id, ref, digest, *, plan_digest):
        parent = self._parent(self.access.require_plan_access(project_id, plan_digest), project_id, plan_digest)
        payload = self.artifacts.read(project_id, ref, digest)
        try:
            if (payload["schema"] not in OBSERVATION_ARCHIVE_SCHEMAS or payload["project_id"] != project_id
                    or payload["plan_digest"] != plan_digest or payload["plan"]["project_id"] != project_id
                    or payload["plan"]["plan_digest"] != plan_digest or acceptance_digest(payload) != digest
                    or payload["original_run_plan"] != parent.model_dump(mode="json")):
                raise RunPlanObservationInvalid("observation archive original scope differs")
            rebuilt = self._compile(parent, payload["plan"], payload["raw_results"], run_id=payload["run_id"], timeout_ms=payload["timeout_ms"])
            if acceptance_digest(rebuilt) != digest:
                raise RunPlanObservationInvalid("observation archive original results or oracle mapping differ")
        except (KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
            raise RunPlanObservationInvalid("observation archive cannot be completely verified") from None
        if self.access.require_plan_access(project_id, plan_digest) != parent:
            raise RunPlanObservationInvalid("original plan changed during archive replay")
        return payload
