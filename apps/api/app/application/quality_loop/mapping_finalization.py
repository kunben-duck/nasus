"""Independent final authority for a complete immutable staged-part commitment."""
from pydantic import ValidationError

from .mapping_finalization_inputs import MappingFinalizeInput
from .test_design_mapping_pins import mapping_generation_pin
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.mapping_partitions import prepare_mapping_partitions, assess_partitioned_mappings
from ...domain.quality_loop.mapping_part_sets import PARTITIONED_MAPPING_SCHEMA, part_member, part_set_commitment
from ...domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied


class MappingFinalizationApplicationService:
    def __init__(self, results, authorization, repository, artifacts, parts):
        self.results, self.authorization, self.repository, self.artifacts, self.parts = results, authorization, repository, artifacts, parts

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("final mapping requires an independent project reviewer")
        return access

    def _inputs(self, request, *, previous, current):
        result = self.results.read(request.project_id, request.generation_id)
        if result["metadata"]["artifact_hash"] != request.generation_artifact_hash:
            raise TestDesignMappingIntegrityError("final mapping generation pin mismatch")
        if current and not result["current_use"]["scope_current"]:
            raise TestDesignMappingChanged("final mapping scope is no longer current")
        pin = mapping_generation_pin(result)
        plan, _ = prepare_mapping_partitions(result["result"]["proposal"], {"project_id": request.project_id, **pin}, previous)
        if plan["plan_digest"] != request.plan_digest:
            raise TestDesignMappingChanged("final mapping plan changed; inspect again")
        return result, pin, plan

    def _head(self, request):
        history = self.repository.history(request.project_id, request.generation_id)
        return history[-1]["revision_id"] if history else None

    def _members(self, plan, actor_id):
        heads = self.parts.heads(plan, actor_id)
        return [part_member(value) for value in heads]

    def inspect(self, request):
        access = self._access(request.project_id)
        previous = self._head(request)
        result, _, plan = self._inputs(request, previous=previous, current=False)
        members = self._members(plan, access.actor_id)
        if any(member["sequence"] >= plan["part_count"] for member in members):
            raise TestDesignMappingIntegrityError("staged part is outside the complete plan")
        ready = bool(plan["part_count"] and [item["sequence"] for item in members] == list(range(plan["part_count"])))
        commitment = part_set_commitment(plan, access.actor_id, members) if ready else None
        if ready:
            # A metadata head is not proof of intact private decisions.
            assess_partitioned_mappings(result["result"]["proposal"], plan["generation_pin"], previous,
                plan["plan_digest"], self.parts.decision_parts(plan, access.actor_id, members))
        if self._head(request) != previous or self._members(plan, access.actor_id) != members:
            raise TestDesignMappingChanged("mapping set changed during inspection")
        self.authorization.require_current(access)
        return {**request.model_dump(mode="json"), "expected_previous_revision_id": previous,
            "authority_actor": access.actor_id, "part_count": plan["part_count"], "saved_part_count": len(members),
            "assertion_count": plan["assertion_count"], "part_set": commitment,
            "ready_for_confirmation": bool(ready and result["current_use"]["scope_current"]),
            "scope_current": result["current_use"]["scope_current"], "review_authorized": False, "execution_authorized": False}

    def finalize(self, request: MappingFinalizeInput, *, invocation_id, recorded_at):
        request = MappingFinalizeInput.model_validate(request.model_dump(mode="json"))
        access = self._access(request.project_id)
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id, require_access=require_access)
        if prior is not None:
            value, _ = self.read(request.project_id, prior["revision_id"])
            if value["request"] != request.model_dump(mode="json"):
                raise TestDesignMappingIntegrityError("final mapping recovery request mismatch")
            require_access()
            return prior
        if self._head(request) != request.expected_previous_revision_id:
            raise TestDesignMappingChanged("mapping head changed before final confirmation")
        result, pin, plan = self._inputs(request, previous=request.expected_previous_revision_id, current=True)
        members = self._members(plan, access.actor_id)
        commitment = part_set_commitment(plan, access.actor_id, members)
        if commitment["part_set_digest"] != request.part_set_digest:
            raise TestDesignMappingChanged("private parts changed after the final preview")
        assessment = assess_partitioned_mappings(result["result"]["proposal"], plan["generation_pin"],
            request.expected_previous_revision_id, request.plan_digest, self.parts.decision_parts(plan, access.actor_id, members))
        payload = {"schema": PARTITIONED_MAPPING_SCHEMA, "project_id": request.project_id,
            "request": request.model_dump(mode="json"), "generation_pin": pin, "plan": plan,
            "part_set": {**commitment, "members": members}, "assessment": assessment,
            "authority_actor": access.actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at}
        require_access()
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise TestDesignMappingIntegrityError("final mapping artifact write mismatch")

        def require_current():
            fresh, fresh_pin, fresh_plan = self._inputs(request, previous=request.expected_previous_revision_id, current=True)
            if fresh_pin != pin or fresh_plan != plan:
                raise TestDesignMappingIntegrityError("final mapping derivation changed before commit")
            if self._members(plan, access.actor_id) != members:
                raise TestDesignMappingChanged("private part head changed before final commit")
            verified = assess_partitioned_mappings(fresh["result"]["proposal"], plan["generation_pin"],
                request.expected_previous_revision_id, request.plan_digest, self.parts.decision_parts(plan, access.actor_id, members))
            if verified != assessment:
                raise TestDesignMappingIntegrityError("final mapping decisions changed before commit")
            require_access()

        metadata = self.repository.record(request, payload, ref, digest, require_current=require_current)
        require_access()
        return metadata

    def read(self, project_id, revision_id):
        metadata, ref = self.repository.get(project_id, revision_id)
        return self.read_value(project_id, metadata, ref)

    def read_value(self, project_id, metadata, ref):
        access = self._access(project_id)
        payload = self.artifacts.read(project_id, ref, metadata["artifact_hash"])
        try:
            request = MappingFinalizeInput.model_validate(payload["request"])
            members = payload["part_set"]["members"]
        except (ValidationError, KeyError, TypeError) as exc:
            raise TestDesignMappingIntegrityError("partitioned mapping archive invalid") from exc
        if (payload.get("schema") != PARTITIONED_MAPPING_SCHEMA or metadata.get("mapping_schema") != PARTITIONED_MAPPING_SCHEMA
                or request.project_id != project_id or payload.get("project_id") != project_id
                or acceptance_digest(payload) != metadata["artifact_hash"]
                or acceptance_digest(request.model_dump(mode="json")) != metadata["request_hash"]
                or request.generation_id != metadata["generation_id"]
                or request.generation_artifact_hash != metadata["generation_artifact_hash"]
                or request.expected_previous_revision_id != metadata["previous_revision_id"] or metadata["status"] != "reviewed"
                or any(payload.get(key) != metadata[key] for key in ("authority_actor", "invocation_id", "recorded_at"))):
            raise TestDesignMappingIntegrityError("partitioned mapping archive provenance mismatch")
        result, pin, plan = self._inputs(request, previous=request.expected_previous_revision_id, current=False)
        commitment = part_set_commitment(plan, metadata["authority_actor"], members)
        assessment = assess_partitioned_mappings(result["result"]["proposal"], plan["generation_pin"],
            request.expected_previous_revision_id, request.plan_digest, self.parts.decision_parts(plan, metadata["authority_actor"], members,
                final_revision=metadata["revision_id"]))
        if (payload.get("generation_pin") != pin or payload.get("plan") != plan
                or payload.get("part_set") != {**commitment, "members": members}
                or request.part_set_digest != commitment["part_set_digest"] or payload.get("assessment") != assessment):
            raise TestDesignMappingIntegrityError("partitioned mapping derivation mismatch")
        current = self._head(request) == metadata["revision_id"] and result["current_use"]["scope_current"]
        self.authorization.require_current(access)
        return {"revision": metadata, "request": request.model_dump(mode="json"), "generation_pin": pin,
            "plan": plan, "part_set": {**commitment, "members": members}, "assessment": assessment, "historical_not_live": True,
            "current_use": {"scope_current": result["current_use"]["scope_current"], "mapping_current": current,
                "mapping_complete": bool(current and assessment["mapping_complete"]), "execution_authorized": False}}, result
