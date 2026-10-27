from typing import Protocol

from pydantic import ValidationError

from .test_design_mapping_inputs import MappingQueryInput, MappingReviewInput, MappingReceipt, PartitionedMappingReceipt
from .mapping_finalization import MappingFinalizationApplicationService
from ...domain.quality_loop.mapping_part_sets import PARTITIONED_MAPPING_SCHEMA
from .mapping_partition_inputs import MappingPartitionPageInput
from .test_design_mapping_pins import mapping_generation_pin
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.mapping_partitions import prepare_mapping_partitions
from ...domain.quality_loop.test_design_mapping import (
    MAPPING_SCHEMA, TestDesignMappingChanged, TestDesignMappingIntegrityError, assess_mappings,
)
from ...domain.system_image.source_access import SourceAccessDenied


class MappingResultPort(Protocol):
    def read(self, project_id, generation_id): ...


class MappingRepositoryPort(Protocol):
    def history(self, project_id, generation_id, through_revision_id=None): ...
    def get(self, project_id, revision_id): ...
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, artifact_ref, artifact_hash, *, require_current): ...


class MappingArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class TestDesignMappingApplicationService:
    __test__ = False

    def __init__(self, results: MappingResultPort, authorization, repository: MappingRepositoryPort, artifacts: MappingArtifactPort, *, parts=None):
        self.results, self.authorization, self.repository, self.artifacts = results, authorization, repository, artifacts
        self.partitioned = MappingFinalizationApplicationService(results, authorization, repository, artifacts, parts) if parts else None

    def finalization_preview(self, request):
        return self.partitioned.inspect(request)

    def finalize(self, request, *, invocation_id, recorded_at):
        return self.partitioned.finalize(request, invocation_id=invocation_id, recorded_at=recorded_at)

    def _result(self, request, *, current=False):
        value = self.results.read(request.project_id, request.generation_id)
        if value["metadata"]["artifact_hash"] != request.generation_artifact_hash:
            raise TestDesignMappingIntegrityError("mapping generation pin mismatch")
        if current and not value["current_use"]["scope_current"]:
            raise TestDesignMappingChanged("generation scope is no longer current")
        return value

    @staticmethod
    def _pin(result):
        return mapping_generation_pin(result)

    def inspect(self, request: MappingQueryInput):
        return self._inspection_inputs(request)[0]

    def _inspection_inputs(self, request):
        access = self.authorization.scope(request.project_id)
        history = self.repository.history(request.project_id, request.generation_id)
        if history:
            head, result = self._read_inputs(request.project_id, history[-1]["revision_id"])
            if head["revision"]["generation_artifact_hash"] != request.generation_artifact_hash:
                raise TestDesignMappingIntegrityError("mapping query generation pin mismatch")
        else:
            head, result = None, self._result(request)
        self.authorization.require_current(access)
        return {"project_id": request.project_id, "generation_id": request.generation_id,
            "generation_artifact_hash": request.generation_artifact_hash, "head": head, "history": history,
            "scope_current": result["current_use"]["scope_current"],
            "can_review": access.effective_project_role in {"qa_lead", "project_admin", "platform_admin"}}, result

    def partition_plan(self, request: MappingQueryInput):
        return self._partition_view(request)

    def partition_page(self, request: MappingPartitionPageInput):
        return self._partition_view(request, sequence=request.sequence, expected_digest=request.plan_digest)

    def _partition_view(self, request, *, sequence=None, expected_digest=None):
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("mapping partition inspection requires a project reviewer")
        query = MappingQueryInput(**{key: getattr(request, key) for key in MappingQueryInput.model_fields})
        view, result = self._inspection_inputs(query)
        previous = view["history"][-1]["revision_id"] if view["history"] else None
        plan, part = prepare_mapping_partitions(result["result"]["proposal"],
            {"project_id": request.project_id, **self._pin(result)}, previous, sequence=sequence)
        if expected_digest is not None and plan["plan_digest"] != expected_digest:
            raise TestDesignMappingChanged("mapping partition plan changed; inspect again")
        history = self.repository.history(request.project_id, request.generation_id)
        if (history[-1]["revision_id"] if history else None) != previous:
            raise TestDesignMappingChanged("mapping head changed during partition inspection")
        self.authorization.require_current(access)
        return {**query.model_dump(mode="json"), "plan": plan, "part": part,
            "scope_current": view["scope_current"], "historical_not_live": True,
            "review_authorized": False, "execution_authorized": False}

    def receipt(self, request):
        view = self.inspect(request)
        head = view["head"]
        revision, assessment = (head["revision"], head["assessment"]) if head else (None, None)
        receipt_type = PartitionedMappingReceipt if revision and revision.get("mapping_schema") == PARTITIONED_MAPPING_SCHEMA else MappingReceipt
        return receipt_type(**request.model_dump(), head_revision_id=revision["revision_id"] if revision else None,
            head_artifact_hash=revision["artifact_hash"] if revision else None, status=revision["status"] if revision else "unreviewed",
            scope_current=view["scope_current"], mapping_current=head["current_use"]["mapping_current"] if head else False,
            mapping_complete=head["current_use"]["mapping_complete"] if head else False,
            **{key: assessment[key] if assessment else 0 for key in (
                "accepted_assertion_count", "rejected_assertion_count", "deferred_assertion_count")})

    def verify_receipt(self, receipt):
        current = self.receipt(MappingQueryInput(**{key: getattr(receipt, key) for key in MappingQueryInput.model_fields}))
        if current != receipt:
            raise TestDesignMappingChanged("mapping observation changed; query again")

    def review(self, request: MappingReviewInput, *, invocation_id, recorded_at):
        request = MappingReviewInput.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("mapping review requires a project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id, require_access=require_access)
        if prior is not None:
            value = self.read(request.project_id, prior["revision_id"])
            if value["request"] != request.model_dump(mode="json"):
                raise TestDesignMappingIntegrityError("mapping recovery request mismatch")
            require_access()
            return prior
        result = self._result(request, current=request.decision == "review")
        assessment = assess_mappings(result["result"]["proposal"], request.model_dump(mode="json")["mappings"]) if request.mappings is not None else None
        payload = {"schema": MAPPING_SCHEMA, "project_id": request.project_id, "request": request.model_dump(mode="json"),
            "generation_pin": self._pin(result), "assessment": assessment,
            "authority_actor": access.actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at}
        require_access()
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise TestDesignMappingIntegrityError("mapping artifact write mismatch")

        def require_current():
            fresh = self._result(request, current=request.decision == "review")
            if self._pin(fresh) != payload["generation_pin"]:
                raise TestDesignMappingIntegrityError("mapping derivation changed before commit")
            require_access()

        metadata = self.repository.record(request, payload, ref, digest, require_current=require_current)
        require_access()
        return metadata

    def read(self, project_id, revision_id):
        return self.read_with_result(project_id, revision_id)[0]

    def read_with_result(self, project_id, revision_id):
        """Return this read's complete verified parent, not a cached authority lease."""
        return self._read_inputs(project_id, revision_id)

    def _read_inputs(self, project_id, revision_id):
        access = self.authorization.scope(project_id)
        revision, ref = self.repository.get(project_id, revision_id)
        if revision.get("mapping_schema") == PARTITIONED_MAPPING_SCHEMA:
            if self.partitioned is None:
                raise TestDesignMappingIntegrityError("partitioned mapping reader unavailable")
            return self.partitioned.read_value(project_id, revision, ref)
        payload = self.artifacts.read(project_id, ref, revision["artifact_hash"])
        try:
            request = MappingReviewInput.model_validate(payload["request"])
        except (ValidationError, KeyError, TypeError) as exc:
            raise TestDesignMappingIntegrityError("mapping archive request invalid") from exc
        if (acceptance_digest(payload) != revision["artifact_hash"] or payload.get("schema") != MAPPING_SCHEMA
                or request.project_id != project_id or payload.get("project_id") != project_id
                or acceptance_digest(request.model_dump(mode="json")) != revision["request_hash"]
                or request.generation_id != revision["generation_id"]
                or request.generation_artifact_hash != revision["generation_artifact_hash"]
                or request.expected_previous_revision_id != revision["previous_revision_id"]
                or revision["status"] != ("reviewed" if request.decision == "review" else "withdrawn")
                or any(payload.get(key) != revision[key] for key in ("authority_actor", "invocation_id", "recorded_at"))):
            raise TestDesignMappingIntegrityError("mapping archive metadata mismatch")
        result = self._result(request)
        assessment = assess_mappings(result["result"]["proposal"], request.model_dump(mode="json")["mappings"]) if request.mappings is not None else None
        if payload.get("generation_pin") != self._pin(result) or payload.get("assessment") != assessment:
            raise TestDesignMappingIntegrityError("mapping derivation mismatch")
        history = self.repository.history(project_id, request.generation_id)
        current = history[-1]["revision_id"] == revision_id and revision["status"] == "reviewed" and result["current_use"]["scope_current"]
        self.authorization.require_current(access)
        return {"revision": revision, "request": request.model_dump(mode="json"), "generation_pin": self._pin(result),
            "assessment": assessment, "historical_not_live": True, "current_use": {"scope_current": result["current_use"]["scope_current"],
                "mapping_current": current, "mapping_complete": bool(current and assessment and assessment["mapping_complete"]),
                "execution_authorized": False}}, result

    def resolve(self, project_id, revision_id, artifact_hash):
        return self.resolve_with_result(project_id, revision_id, artifact_hash)[0]

    def resolve_with_result(self, project_id, revision_id, artifact_hash):
        value, result = self.read_with_result(project_id, revision_id)
        if value["revision"]["artifact_hash"] != artifact_hash:
            raise TestDesignMappingIntegrityError("mapping consumer pin mismatch")
        if not value["current_use"]["mapping_current"]:
            raise TestDesignMappingChanged("mapping or scope was superseded or withdrawn")
        return value, result
