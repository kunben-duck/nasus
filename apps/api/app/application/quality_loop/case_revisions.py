"""Human edits are immutable descendants, not fabricated model responses."""
from copy import deepcopy
import json
from typing import Tuple
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_generation import replay_generation_input
from .test_design_output import GenerationValue, Id, Digest, Text, PlannedCase, validate_test_design_output
from .test_design_results import TestDesignResultIntegrityError

CASE_REVISION_SCHEMA = "nasus.test-design-case-revision.v1"
REVISE_CASES = "quality.test_design.cases.revise"


class CaseRevisionInput(GenerationValue):
    project_id: Id
    generation_id: Id
    generation_artifact_hash: Digest
    cases: Tuple[PlannedCase, ...] = Field(min_length=1, max_length=512)
    reason: Text


def revise_proposal(prepared, original, edits):
    by_id = {case["case_id"]: case for case in original["cases"]}
    changed, seen = [], set()
    for edit in edits:
        case = edit.model_dump(mode="json")
        ident = case["case_id"]
        if ident not in by_id or ident in seen:
            raise ValueError("Edit each existing case at most once; generation is required to add cases")
        seen.add(ident)
        previous = by_id[ident]
        for field in ("global_constraint_ids", "supporting_fact_ids", "reused_case_ids"):
            if case[field] != previous[field]:
                raise ValueError("Case editing cannot replace its approved source obligations")
        oracle = lambda value: sorted([{k: v for k, v in a.items() if k != "step_index"}
            for a in value["assertions"]], key=lambda a: a["row_id"])
        if oracle(case) != oracle(previous):
            raise ValueError("Approved business expectations cannot be edited here; revise and confirm the requirement first")
        if case != previous:
            changed.append({"case_id": ident, "before": previous, "after": case})
            by_id[ident] = case
    if not changed:
        raise ValueError("No case changes to save")
    output = {"input_digest": prepared["input_digest"], "cases": [by_id[item["case_id"]] for item in original["cases"]],
        "gaps": original["gaps"]}
    return validate_test_design_output(prepared, json.dumps(output, ensure_ascii=False)), changed


class CaseRevisionApplicationService:
    def __init__(self, results, repository, authorization, artifacts):
        self.results, self.repository = results, repository
        self.authorization, self.artifacts = authorization, artifacts

    def revise(self, request, *, invocation_id):
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise PermissionError("Case editing requires a current project reviewer")
        prior = self.results.repository.by_invocation(request.project_id, invocation_id)
        if prior is not None:
            value = self.results.read(request.project_id, prior["generation_id"])
            if value["result"].get("edit_request") != request.model_dump(mode="json") or value["result"]["actor_id"] != access.actor_id:
                raise TestDesignResultIntegrityError("Case edit command already has a different result")
            return value["metadata"]
        parent = self.results.read(request.project_id, request.generation_id)
        if parent["metadata"]["artifact_hash"] != request.generation_artifact_hash or not parent["current_use"]["scope_current"]:
            raise ValueError("Select the current case revision and valid scope before editing")
        original = parent["result"]
        scope, context = self.results.generation.scopes.read_inputs(request.project_id,
            original["scope_pin"]["revision_id"], original["scope_pin"]["artifact_hash"])
        proposal, changes = revise_proposal(replay_generation_input(context, scope), original["proposal"], request.cases)
        sequence = original.get("edit_sequence", 0) + 1
        if sequence > 64:
            raise ValueError("Case revision chain exceeds its read budget; create a new reviewed design")
        payload = {"schema": CASE_REVISION_SCHEMA, "project_id": request.project_id,
            "generation_id": str(uuid5(NAMESPACE_URL, "nasus:case-revision:" + invocation_id)),
            "invocation_id": invocation_id, "actor_id": access.actor_id,
            "author_ids": sorted(set(original.get("author_ids", [original["actor_id"]])) | {access.actor_id}),
            "edit_sequence": sequence, "edit_request": request.model_dump(mode="json"), "changes": changes,
            "parent": {"generation_id": request.generation_id, "artifact_hash": request.generation_artifact_hash},
            "original_generation_id": original.get("original_generation_id", request.generation_id),
            "request": deepcopy(original["request"]), "context_pin": deepcopy(original["context_pin"]),
            "scope_pin": deepcopy(original["scope_pin"]), "proposal": proposal, "status": "draft",
            "mapping_status": "pending_independent_review", "execution_authorized": False}
        ref, digest = self.artifacts.put(request.project_id, payload)
        if digest != acceptance_digest(payload):
            raise TestDesignResultIntegrityError("Case revision artifact write mismatch")
        def check():
            current = self.results.read(request.project_id, request.generation_id)
            if current["metadata"]["artifact_hash"] != request.generation_artifact_hash or not current["current_use"]["scope_current"]:
                raise ValueError("Case revision or its context changed before commit")
            self.authorization.require_current(access)
        value = self.repository.append(request, payload, ref, digest, scope=access, check=check)
        self.authorization.require_current(access)
        return value

    def read_archive(self, access, stored, payload, project_id, generation_id, depth):
        if depth > 64:
            raise TestDesignResultIntegrityError("Case revision chain exceeds its read budget")
        metadata = stored["metadata"]
        if (acceptance_digest(payload) != metadata["artifact_hash"] or payload.get("schema") != CASE_REVISION_SCHEMA
                or payload.get("project_id") != project_id or payload.get("generation_id") != generation_id
                or payload.get("invocation_id") != metadata["invocation_id"] or metadata["call_id"] is not None
                or payload.get("status") != "draft" or payload.get("mapping_status") != "pending_independent_review"
                or payload.get("execution_authorized") is not False):
            raise TestDesignResultIntegrityError("Case revision metadata mismatch")
        request = CaseRevisionInput.model_validate(payload["edit_request"])
        if (request.project_id != project_id or payload["parent"] != {
                "generation_id": request.generation_id, "artifact_hash": request.generation_artifact_hash}):
            raise TestDesignResultIntegrityError("Case revision parent mismatch")
        parent = self.results._read_archive(project_id, request.generation_id, depth=depth + 1)
        original = parent["result"]
        if parent["metadata"]["artifact_hash"] != request.generation_artifact_hash:
            raise TestDesignResultIntegrityError("Case revision parent artifact changed")
        for key in ("context_pin", "scope_pin", "request"):
            if payload[key] != original[key]:
                raise TestDesignResultIntegrityError("Case edit cannot replace generation inputs")
        if metadata["scope_revision_id"] != original["scope_pin"]["revision_id"]:
            raise TestDesignResultIntegrityError("Case revision scope metadata mismatch")
        if (payload["edit_sequence"] != original.get("edit_sequence", 0) + 1
                or payload["original_generation_id"] != original.get("original_generation_id", request.generation_id)
                or payload["author_ids"] != sorted(set(original.get("author_ids", [original["actor_id"]])) | {payload["actor_id"]})):
            raise TestDesignResultIntegrityError("Case revision authorship or sequence mismatch")
        scope, context = self.results.generation.scopes.read_inputs(project_id,
            original["scope_pin"]["revision_id"], original["scope_pin"]["artifact_hash"])
        proposal, changes = revise_proposal(replay_generation_input(context, scope), original["proposal"], request.cases)
        if (proposal != payload["proposal"] or changes != payload["changes"] or stored["coverage"] != proposal["coverage"]
                or stored["cases"] != sorted(proposal["cases"], key=lambda item: item["case_id"])
                or metadata["case_count"] != len(proposal["cases"]) or metadata["gap_count"] != len(proposal["gaps"])):
            raise TestDesignResultIntegrityError("Case revision does not replay to its archived diff")
        self.repository.verify_history(request, payload, metadata)
        self.authorization.require_current(access)
        return {"metadata": metadata, "result": payload, "historical_not_live": True,
            "current_use": {"scope_current": parent["current_use"]["scope_current"], "mapping_approved": False, "execution_authorized": False}}
