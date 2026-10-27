"""Persist independent review parts; only a separate final review can approve them."""
from typing import Protocol

from pydantic import ValidationError

from .mapping_part_inputs import MappingPartStageInput, STAGED_PART_SCHEMA
from .mapping_partition_inputs import MappingPartitionPageInput
from .test_design_mapping_pins import mapping_generation_pin
from .test_design_mappings import MappingResultPort, MappingRepositoryPort, MappingArtifactPort
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.mapping_partitions import prepare_mapping_partitions, verify_partition_decisions
from ...domain.quality_loop.mapping_part_sets import PARTITIONED_MAPPING_SCHEMA, part_set_commitment
from ...domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied


class MappingPartRepositoryPort(Protocol):
    def heads(self, project_id, generation_id, plan_digest, actor_id): ...
    def history(self, project_id, generation_id, plan_digest, sequence, actor_id, through_revision_id=None): ...
    def get(self, project_id, revision_id): ...
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, artifact_ref, artifact_hash, *, require_current): ...


class MappingPartStagingApplicationService:
    def __init__(self, results: MappingResultPort, authorization, reviews: MappingRepositoryPort,
                 repository: MappingPartRepositoryPort, artifacts: MappingArtifactPort):
        self.results, self.authorization, self.reviews = results, authorization, reviews
        self.repository, self.artifacts = repository, artifacts

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("staged mapping parts require a project reviewer")
        return access

    def _prepare(self, request, *, current):
        result = self.results.read(request.project_id, request.generation_id)
        if result["metadata"]["artifact_hash"] != request.generation_artifact_hash:
            raise TestDesignMappingIntegrityError("staged part generation pin mismatch")
        if current and not result["current_use"]["scope_current"]:
            raise TestDesignMappingChanged("staged part scope is no longer current")
        # This is the full original proposal, never a capacity-truncated subset.
        pin = {"project_id": request.project_id, **mapping_generation_pin(result)}
        plan, part = prepare_mapping_partitions(result["result"]["proposal"], pin,
            request.expected_previous_revision_id, sequence=request.sequence)
        if plan["plan_digest"] != request.plan_digest or part["part_digest"] != request.part_digest:
            raise TestDesignMappingIntegrityError("staged part does not match its full immutable plan")
        decisions = verify_partition_decisions(part, request.model_dump(mode="json")["decisions"])
        if current:
            self._require_head(request)
        return plan, part, decisions, result["current_use"]["scope_current"]

    def _require_head(self, request):
        history = self.reviews.history(request.project_id, request.generation_id)
        if (history[-1]["revision_id"] if history else None) != request.expected_previous_revision_id:
            raise TestDesignMappingChanged("mapping head changed; inspect a new partition plan")

    def inspect(self, request: MappingPartitionPageInput):
        access = self._access(request.project_id)
        reviews = self.reviews.history(request.project_id, request.generation_id)
        previous = reviews[-1]["revision_id"] if reviews else None
        result = self.results.read(request.project_id, request.generation_id)
        if result["metadata"]["artifact_hash"] != request.generation_artifact_hash:
            raise TestDesignMappingIntegrityError("staged part inspection generation pin mismatch")
        plan, _ = prepare_mapping_partitions(result["result"]["proposal"],
            {"project_id": request.project_id, **mapping_generation_pin(result)}, previous, sequence=request.sequence)
        if plan["plan_digest"] != request.plan_digest:
            raise TestDesignMappingChanged("staged part plan changed; inspect again")
        history = self.repository.history(request.project_id, request.generation_id, request.plan_digest,
            request.sequence, access.actor_id)
        fresh = self.reviews.history(request.project_id, request.generation_id)
        if (fresh[-1]["revision_id"] if fresh else None) != previous:
            raise TestDesignMappingChanged("mapping head changed during staged part inspection")
        self.authorization.require_current(access)
        return {**request.model_dump(mode="json"), "authority_actor": access.actor_id,
            "head": history[-1] if history else None, "history": history[-5:], "history_count": len(history),
            "history_truncated": len(history) > 5, "scope_current": result["current_use"]["scope_current"],
            "assertion_mapped": False, "review_authorized": False, "execution_authorized": False}

    def stage(self, request: MappingPartStageInput, *, invocation_id, recorded_at):
        request = MappingPartStageInput.model_validate(request.model_dump(mode="json"))
        access = self._access(request.project_id)
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
            require_access=require_access)
        if prior is not None:
            value = self.read(request.project_id, prior["part_revision_id"])
            if value["request"] != request.model_dump(mode="json"):
                raise TestDesignMappingIntegrityError("staged part recovery request mismatch")
            require_access()
            return prior
        plan, _, _, _ = self._prepare(request, current=True)
        payload = {"schema": STAGED_PART_SCHEMA, "project_id": request.project_id,
            "request": request.model_dump(mode="json"), "plan": plan,
            "authority_actor": access.actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at,
            "assertion_mapped": False, "execution_authorized": False}
        require_access()
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise TestDesignMappingIntegrityError("staged part artifact write mismatch")

        def require_current():
            fresh, _, _, _ = self._prepare(request, current=True)
            if fresh != plan:
                raise TestDesignMappingIntegrityError("staged part derivation changed before commit")
            require_access()

        metadata = self.repository.record(request, payload, ref, digest, require_current=require_current)
        require_access()
        return metadata

    def read(self, project_id, revision_id):
        access = self._access(project_id)
        metadata, ref = self.repository.get(project_id, revision_id)
        if (metadata["authority_actor"] != access.actor_id
                and access.effective_project_role not in {"project_admin", "platform_admin"}):
            raise SourceAccessDenied("another reviewer's staged decisions are private")
        payload, request = self._archive(project_id, metadata, ref)
        plan, _, _, scope_current = self._prepare(request, current=False)
        if payload.get("plan") != plan:
            raise TestDesignMappingIntegrityError("staged part derivation mismatch")
        review_history = self.reviews.history(project_id, request.generation_id)
        part_history = self.repository.history(project_id, request.generation_id, request.plan_digest,
            request.sequence, metadata["authority_actor"])
        current = (scope_current
            and (review_history[-1]["revision_id"] if review_history else None) == request.expected_previous_revision_id
            and part_history[-1]["part_revision_id"] == revision_id)
        self.authorization.require_current(access)
        return {"revision": metadata, "request": request.model_dump(mode="json"), "plan": plan,
            "historical_not_live": True, "current_use": {"scope_current": scope_current, "part_current": current,
                "assertion_mapped": False, "review_authorized": False, "execution_authorized": False}}

    def _archive(self, project_id, metadata, ref):
        payload = self.artifacts.read(project_id, ref, metadata["artifact_hash"])
        try:
            request = MappingPartStageInput.model_validate(payload["request"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise TestDesignMappingIntegrityError("staged part archive request invalid") from exc
        if (payload.get("schema") != STAGED_PART_SCHEMA or request.project_id != project_id
                or payload.get("project_id") != project_id or acceptance_digest(payload) != metadata["artifact_hash"]
                or acceptance_digest(request.model_dump(mode="json")) != metadata["request_hash"]
                or any(getattr(request, key) != metadata[key] for key in (
                    "generation_id", "generation_artifact_hash", "plan_digest", "sequence", "part_digest",
                    "expected_previous_revision_id", "expected_previous_part_revision_id"))
                or any(payload.get(key) != metadata[key] for key in ("authority_actor", "invocation_id", "recorded_at"))
                or payload.get("assertion_mapped") is not False or payload.get("execution_authorized") is not False):
            raise TestDesignMappingIntegrityError("staged part archive metadata mismatch")
        return payload, request

    def heads(self, plan, actor_id):
        pin = plan["generation_pin"]
        access = self._access(pin["project_id"])
        if actor_id != access.actor_id:
            raise SourceAccessDenied("only the signer may select their private parts for final review")
        values = self.repository.heads(pin["project_id"], pin["generation_id"], plan["plan_digest"], actor_id)
        self.authorization.require_current(access)
        return values

    def decision_parts(self, plan, actor_id, members, *, final_revision=None):
        """Read all fixed originals once; the domain reducer verifies every pair."""
        pin = plan["generation_pin"]
        access = self._access(pin["project_id"])
        if actor_id != access.actor_id and access.effective_project_role not in {"project_admin", "platform_admin"}:
            if final_revision is None:
                raise SourceAccessDenied("another reviewer's staged decisions are private")
            # Only the exact persisted final authority permits internal verification
            # for another reviewer. Private draft reads still reject that actor.
            final, _ = self.reviews.get(pin["project_id"], final_revision)
            commitment = part_set_commitment(plan, actor_id, members)
            if (final.get("mapping_schema") != PARTITIONED_MAPPING_SCHEMA or final["status"] != "reviewed"
                    or final["generation_id"] != pin["generation_id"] or final["generation_artifact_hash"] != pin["artifact_hash"]
                    or final["authority_actor"] != actor_id or final.get("plan_digest") != plan["plan_digest"]
                    or final.get("part_set_digest") != commitment["part_set_digest"]):
                raise SourceAccessDenied("private parts are not bound to this exact final authority")
        for member in members:
            metadata, ref = self.repository.get(pin["project_id"], member["part_revision_id"])
            payload, request = self._archive(pin["project_id"], metadata, ref)
            if (any(member[key] != metadata[key] for key in member) or metadata["authority_actor"] != actor_id
                    or payload.get("plan") != plan or request.plan_digest != plan["plan_digest"]
                    or request.generation_id != pin["generation_id"] or request.generation_artifact_hash != pin["artifact_hash"]
                    or request.expected_previous_revision_id != plan["expected_previous_revision_id"]):
                raise TestDesignMappingIntegrityError("final mapping part provenance mismatch")
            self.authorization.require_current(access)
            yield {"sequence": request.sequence, "plan_digest": request.plan_digest, "part_digest": request.part_digest,
                "decisions": request.model_dump(mode="json")["decisions"]}
        self.authorization.require_current(access)
