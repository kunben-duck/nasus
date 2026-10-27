from copy import deepcopy
import json

import pytest

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.test_design_generation import GenerationSelection
from apps.api.app.domain.quality_loop.test_design_generation import TestDesignGenerationInvalid
from apps.api.app.domain.quality_loop.test_design_scope import TestDesignScopeChanged
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.tests.test_test_design_scope_api import design_scope, submit, inspect
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import completed, invoke
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_published_context_packs import advance
from apps.api.tests.test_test_design_generation import case_output


def generation_request(v):
    revision = inspect(v)["head"]["revision"]
    selection = GenerationSelection(project_id=v["project_id"], scope_revision_id=revision["revision_id"], scope_artifact_hash=revision["artifact_hash"])
    return selection, v["scope_url"] + "/" + revision["revision_id"] + "/generation-preview"


def test_generation_preview_uses_archived_inputs_and_rechecks_stale_scope(design_scope):
    v = design_scope
    completed(submit(v))
    request, url = generation_request(v)
    client = v["client"]
    response = client.get(url, headers=v["headers"], params={"artifact_hash": request.scope_artifact_hash})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    preview = response.json()
    assert preview["constraint_count"] == len(v["context"]["context"]["required_constraints"])
    assert preview["obligation_count"] == preview["constraint_count"] * 3 + 1
    assert not preview["generation_authorized"] and not preview["execution_authorized"]
    assert "HTTP 400" not in response.text
    application = app.state.container.test_design_generation
    query = completed(invoke(v, "query.quality.test_design_generation", request.model_dump(mode="json")))
    assert query["result"]["test_design_generation"]["input_digest"] == preview["input_digest"]
    assert "HTTP 400" not in json.dumps(query["result"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(query["id"], v["project_id"]) == query["result"]["test_design_generation"]
        prepared = application.prepare(request)
        output = json.dumps(case_output(prepared))
        result = application.check_output(request, expected_input_digest=preview["input_digest"], content=output)
        assert result["coverage"]["planned_constraint_count"] == preview["constraint_count"]
        assert result["coverage"]["passed_count"] == 0
    completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": request.scope_revision_id, "decision": "withdraw", "contract": None}))
    assert client.get(url, headers=v["headers"], params={"artifact_hash": request.scope_artifact_hash}).status_code == 409
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignScopeChanged):
            app.state.container.tool_evidence.describe(query["id"], v["project_id"])
        with pytest.raises(TestDesignScopeChanged):
            application.check_output(request, expected_input_digest=preview["input_digest"], content=output)


def test_generation_preview_rejects_scope_gaps_and_hash_rebinding(design_scope):
    v = design_scope
    scope = deepcopy(v["scope_request"])
    scope["contract"]["gaps"] = [{"id": "await-owner", "constraint_ids": [scope["contract"]["examples"][0]["constraint_id"]],
                                  "description": "Explicitly unresolved fixture input boundary"}]
    completed(submit(v, scope))
    request, url = generation_request(v)
    response = v["client"].get(url, headers=v["headers"], params={"artifact_hash": request.scope_artifact_hash})
    assert response.status_code == 409 and response.json()["detail"]["error"]["code"] == "test_design_generation_input_invalid", response.text
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignGenerationInvalid):
            app.state.container.test_design_generation.prepare(request)
    assert v["client"].get(url, headers=v["headers"], params={"artifact_hash": "sha256:" + "0" * 64}).status_code == 502
    assert v["client"].get(url, headers=v["headers"], params={"artifact_hash": "bad"}).status_code == 422
    assert v["client"].get(url, params={"artifact_hash": request.scope_artifact_hash}).status_code == 401


def test_generation_preview_respects_source_acl_and_publication_head(design_scope):
    v = design_scope
    completed(submit(v))
    request, url = generation_request(v)
    params = {"artifact_hash": request.scope_artifact_hash}
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"], params=params).status_code == 200
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="generation-revoke")
    denied = v["client"].get(url, headers=v["member_headers"], params=params)
    assert denied.status_code == 403 and "HTTP 400" not in denied.text
    advance(v, v["context_head"])
    assert v["client"].get(url, headers=v["headers"], params=params).status_code == 409
