"""Record verified private observations without granting target execution authority."""
from contextlib import nullcontext
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .run_plan_observation_archives import (
    RunPlanObservationArchiveApplicationService, RunPlanObservationArchiveParent,
    SavedRunPlanObservationArchiveAccess,
)
from .test_design_output import GenerationValue, Id, Digest
from ...domain.quality_loop.run_plan_observation_record import observation_record_metadata
from ...domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from ...domain.system_image.source_access import SourceAccessDenied


OBSERVATION_RECORD_TOOL = "quality.run_plan.record_observations"
OBSERVATION_RECORD_QUERY_TOOL = "query.quality.run_plan_observations"
OBSERVATION_RECORD_TOOLS = frozenset({OBSERVATION_RECORD_TOOL, OBSERVATION_RECORD_QUERY_TOOL})


class ObservationRecordRequest(RunPlanObservationArchiveParent):
    observation_artifact_hash: Digest
    collection_digest: Digest
    run_id: Id

    def parent(self):
        return RunPlanObservationArchiveParent(**{key: getattr(self, key)
            for key in RunPlanObservationArchiveParent.model_fields})


class ObservationRecordQuery(GenerationValue):
    project_id: Id
    record_id: Id


class ObservationRecordRepositoryPort(Protocol):
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, archive, ref, metadata, *, require_access): ...
    def read(self, project_id, record_id): ...


class RunPlanObservationRecordApplicationService:
    def __init__(self, plans, authorization, observations, artifacts, repository: ObservationRecordRepositoryPort):
        self.plans, self.authorization = plans, authorization
        self.observations, self.artifacts, self.repository = observations, artifacts, repository

    def _read_session(self):
        operation = getattr(self.plans, "verified_read_session", None)
        return operation() if callable(operation) else nullcontext()

    def _read_archive(self, request, ref):
        service = RunPlanObservationArchiveApplicationService(self.observations, self.artifacts,
            SavedRunPlanObservationArchiveAccess(self.plans, request.parent()))
        # The surrounding operation owns the immutable read scope; ACL stays live.
        archive = service._read(request.project_id, ref, request.observation_artifact_hash,
            plan_digest=request.plan_digest)
        if archive["run_id"] != request.run_id or archive["summary"]["collection_digest"] != request.collection_digest:
            raise RunPlanObservationInvalid("observation recording cannot replace the original attempt or collection")
        return archive

    def record(self, request: ObservationRecordRequest, *, invocation_id, recorded_at):
        request = ObservationRecordRequest.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("recording original observations requires a current project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        with self._read_session():
            prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
                require_access=require_access)
            if prior is not None:
                view = self._read(request.project_id, prior["record_id"])
                if view["metadata"] != prior:
                    raise RunPlanObservationInvalid("original observation registration differs")
                require_access()
                return prior
            ref = self.artifacts.reference(request.project_id, request.observation_artifact_hash)
            archive = self._read_archive(request, ref)
            metadata = observation_record_metadata(archive, request.model_dump(mode="json"),
                record_id=str(uuid5(NAMESPACE_URL, "nasus:run-plan-observations:" + invocation_id)),
                invocation_id=invocation_id, actor_id=access.actor_id, recorded_at=recorded_at)

            def verify_before_commit():
                if self._read_archive(request, ref) != archive:
                    raise RunPlanObservationInvalid("original observation bytes changed before commit")
                require_access()

            value = self.repository.record(request, archive, ref, metadata, require_access=verify_before_commit)
            require_access()
            return value

    def _read(self, project_id, record_id):
        access = self.authorization.scope(project_id)
        stored = self.repository.read(project_id, record_id)
        metadata = stored["metadata"]
        request = ObservationRecordRequest.model_validate(stored["request"])
        if request.project_id != project_id:
            raise RunPlanObservationInvalid("observation record project differs")
        archive = self._read_archive(request, stored["artifact_ref"])
        expected = observation_record_metadata(archive, request.model_dump(mode="json"),
            **{key: metadata[key] for key in ("record_id", "invocation_id", "actor_id", "recorded_at")})
        if expected != metadata:
            raise RunPlanObservationInvalid("observation record differs from the complete original archive")
        self.authorization.require_current(access)
        return {"metadata": metadata, "archive": archive, "historical_not_live": True}

    def read(self, project_id, record_id):
        with self._read_session():
            return self._read(project_id, record_id)

    def receipt(self, project_id, record_id):
        view = self.read(project_id, record_id)
        return {"metadata": {key: value for key, value in view["metadata"].items() if key != "members"},
            "historical_not_live": True}

    def require_receipt_inputs_access_many(self, scopes):
        if not 1 <= len(scopes) <= 128:
            raise RunPlanObservationInvalid("observation receipts require a bounded cohort")
        with self._read_session():
            access = {scope.project_id: self.authorization.scope(scope.project_id) for scope in scopes}
            for scope in scopes:
                if isinstance(scope, ObservationRecordQuery):
                    self._read(scope.project_id, scope.record_id)
                elif isinstance(scope, ObservationRecordRequest):
                    ref = self.artifacts.reference(scope.project_id, scope.observation_artifact_hash)
                    self._read_archive(scope, ref)
                else:
                    raise RunPlanObservationInvalid("observation receipt original scope invalid")
            for original in access.values():
                self.authorization.require_current(original)

    def require_receipt_inputs_access(self, scope):
        self.require_receipt_inputs_access_many((scope,))
