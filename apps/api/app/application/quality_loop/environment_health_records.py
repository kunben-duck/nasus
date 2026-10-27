"""Archive exact original-instance health; reads never repeat native probes."""
from copy import deepcopy

from .environment_observation_records import EnvironmentObservationRecordApplicationService, EnvironmentRecordRepositoryPort
from .run_plan_environment_health import RunPlanEnvironmentHealthApplicationService
from .run_plan_environments import RunPlanEnvironmentQuery
from ...domain.quality_loop.environment_health_record import (
    HEALTH_RECORD_SCHEMA, health_record_identity, health_record_metadata, validate_health_archive,
)
from ...domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError


class EnvironmentHealthRecordApplicationService(EnvironmentObservationRecordApplicationService):
    def __init__(self, health: RunPlanEnvironmentHealthApplicationService, artifacts, repository: EnvironmentRecordRepositoryPort):
        super().__init__(health.original_inputs, artifacts, repository)
        self.health = health

    def record(self, request: RunPlanEnvironmentQuery, *, invocation_id, recorded_at):
        request = RunPlanEnvironmentQuery.model_validate(request.model_dump(mode="json"))
        access = self.inspections._access(request.project_id)
        current = lambda: self.inspections.authorization.require_current(access)
        with self._read_session():
            self.inspections.original_inputs(request)
            prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
                require_access=current)
            if prior is not None:
                if self._read(request.project_id, prior["record_id"])["metadata"] != prior:
                    raise RunPlanIntegrityError("committed health archive differs")
                current()
                return prior
            parents = self.inspections.original_inputs(request, current=True)
            view = self.health.inspect(request)
            plan, binding = parents
            if self.inspections.original_inputs(request, current=True) != parents:
                raise RunPlanChanged("health original parents changed before archival")
            declaration = plan["artifact"]["plan"]["selection"]["environment"]
            payload = {"schema": HEALTH_RECORD_SCHEMA, "project_id": request.project_id,
                "record_id": health_record_identity(invocation_id), "invocation_id": invocation_id,
                "actor_id": access.actor_id, "recorded_at": recorded_at, "request": request.model_dump(mode="json"),
                "parents": {**{key: plan["metadata"][key] for key in ("plan_digest", "image_revision_id", "manifest_id")},
                    "environment_id": declaration["environment_id"], "operator_policy_digest": declaration["inventory_hash"],
                    "target_artifact_hash": binding["metadata"]["target_artifact_hash"]},
                "observation": deepcopy(view["observation"].payload())}
            validate_health_archive(payload, payload["request"], plan, binding)
            current()
            ref, digest = self.artifacts.put(request.project_id, payload)
            metadata = health_record_metadata(payload)
            if digest != metadata["artifact_hash"]:
                raise RunPlanIntegrityError("health archive write differs")

            def verify_before_commit():
                if self.inspections.original_inputs(request, current=True) != parents:
                    raise RunPlanChanged("health original parents changed before commit")
                archived = self.artifacts.read(request.project_id, ref, digest)
                validate_health_archive(archived, payload["request"], plan, binding)
                if archived != payload:
                    raise RunPlanIntegrityError("original health bytes changed before commit")
                current()

            value = self.repository.record(request, payload, ref, metadata, require_access=verify_before_commit)
            current()
            return value

    def _read(self, project_id, record_id):
        access = self.inspections._access(project_id)
        stored = self.repository.read(project_id, record_id)
        request = RunPlanEnvironmentQuery.model_validate(stored["request"])
        if request.project_id != project_id or stored["metadata"]["record_id"] != record_id:
            raise RunPlanIntegrityError("health archive read scope differs")
        plan, binding = self.inspections.original_inputs(request)
        archive = self.artifacts.read(project_id, stored["artifact_ref"], stored["metadata"]["artifact_hash"])
        validate_health_archive(archive, stored["request"], plan, binding)
        if health_record_metadata(archive) != stored["metadata"]:
            raise RunPlanIntegrityError("health metadata differs from independently archived bytes")
        self.inspections.authorization.require_current(access)
        return {"metadata": deepcopy(stored["metadata"]), "archive": archive, "historical_not_live": True}
