"""Explicit synthetic review of exweb's pinned three-source context, no execution."""
from uuid import uuid4

from apps.api.app.application.quality_loop.test_design_scope_inputs import ScopeReviewInput
from apps.api.app.application.quality_loop.test_design_scopes import TestDesignScopeApplicationService
from apps.api.app.domain.quality_loop.test_design_scope import SCOPE_TOOL
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.test_design_scope_repository import TestDesignScopeRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.test_design_scope_artifacts import TestDesignScopeArtifacts


def review_exweb_test_design_scope(packs, authorization, storage, archived, recorded_at):
    constraints = archived["context"]["required_constraints"]
    ac = next(item for item in constraints if item["kind"] == "acceptance_criterion")
    rule = next(item for item in constraints if item["kind"] == "business_rule")
    common = {"constraint_ids": [ac["object_id"]], "evidence_ids": ac["evidence_ids"], "oracle": ac["oracle"]}
    contract = {
        "authority_basis": "user_confirmed_test_design_scope",
        "risks": {"applicability": "applicable", "rationale": "Fixture reviewer requires response-contract evidence", "items": [
            {**common, "obligation_id": "response-type", "boundary": "A declared route does not prove streaming response content type"}]},
        "permissions": {"applicability": "applicable", "rationale": "Companion fixture authentication rule, not observed target behavior", "items": [
            {"obligation_id": "authentication", "constraint_ids": [rule["object_id"]], "evidence_ids": rule["evidence_ids"],
             "oracle": rule["oracle"], "actor": "Unauthenticated synthetic caller", "operation": "POST",
             "resource": "/api/v1/finance/chat/stream", "expected": "denied"}]},
        "transitions": {"applicability": "not_applicable", "rationale": "No approved lifecycle transition in this narrow companion fixture", "items": []},
        "invariants": {"applicability": "not_applicable", "rationale": "No incident invariant is supplied; none is invented from code", "items": []},
        "examples": [{"constraint_id": item["object_id"], "positive": item["oracle"], "negative": None,
                      "negative_not_applicable_reason": None, "negative_gap_id": "negative-partitions"} for item in constraints],
        "reused_case_ids": [], "reuse_assessment": "Historical test is retrieval evidence, not an approved reusable case",
        "conflicts": [], "conflict_assessment": "No contradiction between the two synthetic fixture oracles; real behavior remains unverified",
        "gaps": [{"id": "negative-partitions", "constraint_ids": [item["object_id"] for item in constraints],
                  "description": "An actual product owner must supply negative-input partitions; do not infer outcomes from exweb code"}],
    }
    metadata = archived["metadata"]
    request = ScopeReviewInput(project_id=metadata["project_id"], context_id=metadata["context_id"], context_artifact_hash=metadata["artifact_hash"],
        expected_previous_revision_id=None, decision="approve", contract=contract,
        reason="Explicit Nasus verification fixture, not exweb maintainer or product approval")
    service = TestDesignScopeApplicationService(packs, authorization, TestDesignScopeRepository(), TestDesignScopeArtifacts(storage))
    invocation_id = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation_id, tool_id=SCOPE_TOOL, status="running", summary="Review explicit exweb fixture scope",
            input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                "confirmed_actor_id": authorization.scope(request.project_id).actor_id}))
    revision = service.review(request, invocation_id=invocation_id, recorded_at=recorded_at)
    view = service.read(request.project_id, revision["revision_id"])
    assert view["request"]["contract"] == request.contract.model_dump(mode="json")
    assert view["assessment"]["constraint_ids"] == sorted(item["object_id"] for item in constraints)
    assert view["assessment"]["obligation_ids"] == ["authentication", "response-type"]
    assert view["current_use"] == {"scope_current": True, "scope_complete": False, "generation_authorized": False}
    assert view["assessment"]["blockers"] == ["explicit_gap:negative-partitions"]
    _, ref = service.repository.get(request.project_id, revision["revision_id"])
    assert ref.startswith("s3://")
    assert service.review(request, invocation_id=invocation_id, recorded_at="retry") == revision
    report = {"revision": revision, "minio_roundtrip_verified": True, "constraint_denominator_preserved": True,
        "permissions_and_risk_oracles_pinned": True, "gaps_not_silently_authorized": True,
        "reviewer_basis": "explicit_fixture_not_exweb_maintainer", "generation_authorized": False, "target_executed": False}
    return service, view, report
