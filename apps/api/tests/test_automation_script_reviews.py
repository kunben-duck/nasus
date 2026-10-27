"""Review protocol fixtures do not approve real exweb business behavior."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.automation_script_review_inputs import ScriptReviewRequest, ScriptReviewQuery
from apps.api.app.application.quality_loop.automation_script_reviews import AutomationScriptReviewApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_script_review import SCRIPT_REVIEW_SCHEMA, ScriptReviewChanged, ScriptReviewIntegrityError, assess_script_review
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_automation_scripts import script_executor


def decisions(proposal):
    actions, assertions = [], []
    for script in proposal["scripts"]:
        for index, action in enumerate(script["actions"]):
            actions.append({"case_id": script["case_id"], "action_index": index, "action_digest": acceptance_digest(action),
                "decision": "accept", "reason": "Explicit protocol action review, not exweb semantic approval"})
        for item in script["assertions"]:
            assertions.append({"case_id": script["case_id"], **{key: item[key] for key in
                ("row_id", "action_index", "source_step_index", "oracle_digest")},
                "decision": "accept", "reason": "Explicit protocol oracle/action review, not target execution"})
    return actions, assertions


def review_inputs():
    service, selection, deps, _ = script_executor()
    from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionRequest
    request = ScriptExecutionRequest.model_validate(service.preview(selection)["request"])
    metadata = asyncio.run(service.execute(request, invocation_id="native-script-command"))
    draft = service.read("p", metadata["script_revision_id"])
    actions, assertions = decisions(draft["result"]["proposal"])
    review = ScriptReviewRequest(project_id="p", script_revision_id=metadata["script_revision_id"],
        script_artifact_hash=metadata["artifact_hash"], expected_previous_revision_id=None, decision="review",
        actions=actions, assertions=assertions, reason="Independent protocol review")
    return draft, review, deps


@pytest.mark.parametrize("historical", [False, True])
def test_canonical_history_is_readonly_but_new_review_still_locks_its_command(historical):
    from sqlalchemy.dialects import postgresql
    from apps.api.app.domain.quality_loop.automation_script_review import SCRIPT_REVIEW_TOOL
    from apps.api.app.infrastructure.persistence.automation_script_models import AutomationScriptRevisionRecord
    from apps.api.app.infrastructure.persistence.automation_script_review_repository import AutomationScriptReviewRepository
    _, request, _ = review_inputs()
    actor_id = "independent-reviewer"
    command = SimpleNamespace(tool_id=SCRIPT_REVIEW_TOOL, status="completed" if historical else "running",
        conversation_id=None, input_payload={**request.model_dump(mode="json"),
            "confirmed_by_user": True, "confirmed_actor_id": actor_id})
    draft = SimpleNamespace(project_id=request.project_id, artifact_hash=request.script_artifact_hash)

    class Session:
        def scalar(self, query):
            sql = str(query.compile(dialect=postgresql.dialect()))
            assert ("FOR UPDATE" in sql) is (not historical)
            return command

        def get(self, model, ident):
            assert model is AutomationScriptRevisionRecord and ident == request.script_revision_id
            return draft

    assert AutomationScriptReviewRepository._canonical(Session(), request, "review-command", actor_id,
        historical=historical) is command
    command.input_payload["confirmed_actor_id"] = "another-actor"
    with pytest.raises(ScriptReviewIntegrityError, match="exact confirmed canonical actor"):
        AutomationScriptReviewRepository._canonical(Session(), request, "review-command", actor_id, historical=historical)


def test_full_action_and_oracle_review_is_separate_and_never_grants_execution():
    draft, request, _ = review_inputs()
    output = request.model_dump(mode="json")
    original = deepcopy(draft)
    assessment = assess_script_review(draft["result"]["proposal"], output["actions"], output["assertions"])
    assert assessment["review_complete"] and assessment["reviewed_oracle_count"] == 7
    assert assessment["accepted_count"] == len(output["actions"]) + len(output["assertions"])
    assert not assessment["execution_authorized"]
    assert assessment["automated_count"] == assessment["executed_on_target_count"] == assessment["passed_count"] == 0
    assert draft == original and draft["result"]["proposal"]["review_status"] == "pending_independent_review"


@pytest.mark.parametrize("fault", ["missing_action", "duplicate_action", "foreign_case", "action_index", "boolean_index", "action_digest",
    "missing_oracle", "duplicate_oracle", "row_id", "oracle_digest", "oracle_action", "oracle_step", "reason", "decision"])
def test_review_cannot_drop_or_rewrite_original_actions_and_oracles(fault):
    draft, request, _ = review_inputs()
    value = request.model_dump(mode="json")
    actions, assertions = value["actions"], value["assertions"]
    if fault == "missing_action": actions.pop()
    elif fault == "duplicate_action": actions.append(deepcopy(actions[0]))
    elif fault == "foreign_case": actions[0]["case_id"] = "foreign"
    elif fault == "action_index": actions[0]["action_index"] = 255
    elif fault == "boolean_index": actions[0]["action_index"] = True
    elif fault == "action_digest": actions[0]["action_digest"] = acceptance_digest("other")
    elif fault == "missing_oracle": assertions.pop()
    elif fault == "duplicate_oracle": assertions.append(deepcopy(assertions[0]))
    elif fault == "row_id": assertions[0]["row_id"] = "foreign"
    elif fault == "oracle_digest": assertions[0]["oracle_digest"] = acceptance_digest("other")
    elif fault == "oracle_action": assertions[0]["action_index"] = 255
    elif fault == "oracle_step": assertions[0]["source_step_index"] = 63
    elif fault == "reason": assertions[0]["reason"] = " "
    else: actions[0]["decision"] = "approve-execution"
    with pytest.raises(ValueError):
        parsed = ScriptReviewRequest.model_validate(value).model_dump(mode="json")
        assess_script_review(draft["result"]["proposal"], parsed["actions"], parsed["assertions"])


@pytest.mark.parametrize("decision", ["reject", "defer"])
def test_rejected_or_deferred_review_keeps_incomplete_without_changing_original_draft(decision):
    draft, request, _ = review_inputs()
    value = request.model_dump(mode="json")
    value["assertions"][0]["decision"] = decision
    assessment = assess_script_review(draft["result"]["proposal"], value["actions"], value["assertions"])
    assert not assessment["review_complete"] and assessment[decision + "red_count" if decision == "defer" else "rejected_count"] == 1
    assert not assessment["execution_authorized"] and assessment["passed_count"] == 0


def test_withdrawal_has_no_decisions_and_cannot_import_authority():
    _, request, _ = review_inputs()
    value = request.model_dump(mode="json")
    for changes in ({"decision": "withdraw"}, {"execution_authorized": True}, {"assertions": None}, {"policy_revision": "latest"}):
        with pytest.raises(ValidationError):
            ScriptReviewRequest.model_validate({**value, **changes})
    assert ScriptReviewRequest.model_validate({**value, "decision": "withdraw", "actions": None, "assertions": None}).assertions is None


def test_explicit_script_gap_and_byte_budget_cannot_become_complete_review(monkeypatch):
    draft, request, _ = review_inputs()
    proposal = deepcopy(draft["result"]["proposal"])
    removed = proposal["scripts"].pop()
    proposal["gaps"].append({"case_id": removed["case_id"], "case_digest": removed["case_digest"], "description": "No locator evidence"})
    actions, assertions = decisions(proposal)
    assert not assess_script_review(proposal, actions, assertions)["review_complete"]
    import apps.api.app.domain.quality_loop.automation_script_review as rules
    monkeypatch.setattr(rules, "MAX_SCRIPT_REVIEW_BYTES", 128)
    with pytest.raises(ScriptReviewIntegrityError, match="never truncate"):
        assess_script_review(proposal, actions, assertions)


def review_service():
    draft, request, _ = review_inputs()
    class Artifacts:
        def __init__(self): self.bodies = {}
        def put(self, project, payload):
            digest = acceptance_digest(payload)
            self.bodies[digest] = deepcopy(payload)
            return "private-review:" + digest, digest
        def read(self, project, ref, digest): return deepcopy(self.bodies[digest])
    class Repository:
        def __init__(self): self.values = []; self.fail = False
        def history(self, *args): return deepcopy(self.values)
        def committed(self, request, *, actor_id, invocation_id, require_access):
            require_access()
            return next((value["revision"] for value in self.values if value["revision"]["invocation_id"] == invocation_id), None)
        def record(self, request, payload, ref, digest, *, require_current):
            require_current()
            if self.fail: raise RuntimeError("explicit failed commit")
            previous = self.values[-1]["revision"]["revision_id"] if self.values else None
            if previous != request.expected_previous_revision_id: raise ScriptReviewChanged("head changed")
            meta = {"project_id": request.project_id, "script_revision_id": request.script_revision_id,
                "script_artifact_hash": request.script_artifact_hash, "revision_id": f"review-{len(self.values)+1}",
                "previous_revision_id": previous, "sequence": len(self.values) + 1, "status": "reviewed" if request.decision == "review" else "withdrawn",
                "artifact_hash": digest, "request_hash": acceptance_digest(request.model_dump(mode="json")),
                **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")}}
            self.values.append({"revision": meta, "artifact_ref": ref})
            return meta
        def revision(self, project, revision): return next(v["revision"] for v in self.values if v["revision"]["revision_id"] == revision)
    class Authorization:
        role = "qa_lead"
        revoked = False
        def scope(self, project):
            if self.revoked: raise SourceAccessDenied("explicit access withdrawal")
            return SimpleNamespace(project_id=project, actor_id="independent-reviewer", effective_project_role=self.role)
        def require_current(self, access):
            if self.revoked: raise SourceAccessDenied("explicit access withdrawal")
    auth, repo, artifacts = Authorization(), Repository(), Artifacts()
    app = AutomationScriptReviewApplicationService(SimpleNamespace(read=lambda *args: deepcopy(draft)), auth, repo, artifacts)
    return app, draft, request, auth, repo, artifacts


def test_review_application_replays_history_without_model_and_rechecks_live_source_mapping():
    service, draft, request, auth, repo, _ = review_service()
    query = ScriptReviewQuery(**{key: getattr(request, key) for key in ScriptReviewQuery.model_fields})
    assert service.inspect(query)["head"] is None and not service.receipt(query)["review_complete"]
    first = service.review(request, invocation_id="review-command", recorded_at="2026-10-10T00:00:00+00:00")
    assert service.review(request, invocation_id="review-command", recorded_at="2026-10-10T01:00:00+00:00") == first
    before = service.read("p", first["revision_id"])
    assert before["current_use"]["review_complete"] and len(repo.values) == 1
    draft["current_use"]["input_current"] = False
    assert service.read("p", first["revision_id"])["assessment"] == before["assessment"]
    assert not service.read("p", first["revision_id"])["current_use"]["review_complete"]
    with pytest.raises(ScriptReviewChanged):
        service.review(request.model_copy(update={"expected_previous_revision_id": first["revision_id"]}), invocation_id="new-command", recorded_at="now")
    withdrawal = request.model_copy(update={"expected_previous_revision_id": first["revision_id"], "decision": "withdraw", "actions": None, "assertions": None})
    second = service.review(withdrawal, invocation_id="withdraw", recorded_at="2026-10-10T02:00:00+00:00")
    assert second["status"] == "withdrawn" and not service.read("p", second["revision_id"])["current_use"]["review_current"]
    auth.revoked = True
    with pytest.raises(SourceAccessDenied): service.read("p", first["revision_id"])


@pytest.mark.parametrize("fault", ["pin", "assessment", "request", "actor", "schema"])
def test_review_archive_mismatch_is_not_repaired_by_a_new_write(fault):
    service, _, request, _, repo, artifacts = review_service()
    first = service.review(request, invocation_id="review-command", recorded_at="2026-10-10T00:00:00+00:00")
    body = artifacts.bodies[first["artifact_hash"]]
    if fault == "pin": body["script_pin"]["input_digest"] = acceptance_digest("other")
    elif fault == "assessment": body["assessment"]["passed_count"] = 1
    elif fault == "request": body["request"]["reason"] = "secret-corrupt-history"
    elif fault == "actor": body["authority_actor"] = "other"
    else: body["schema"] = "unknown"
    with pytest.raises(ScriptReviewIntegrityError): service.read("p", first["revision_id"])
    with pytest.raises(ScriptReviewIntegrityError):
        service.review(request.model_copy(update={"expected_previous_revision_id": first["revision_id"]}), invocation_id="repair-forbidden", recorded_at="now")
    assert len(repo.values) == 1
