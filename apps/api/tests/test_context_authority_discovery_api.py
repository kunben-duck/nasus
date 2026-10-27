from uuid import uuid4

import pytest

from apps.api.app.main import app
from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.application.system_image.context_pack_inputs import CONTEXT_AUTHORITY_BACKFILL_TOOL
from apps.api.app.domain.system_image.context_partition import RULE_AUTHORITY_POLICY
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_context_authorities_api import (
    authority, acceptance, rule, documents, evidence_api, remove_registration, rows, Root, Dependency, register,
)
from apps.api.tests.test_context_packs_api import preview, archive, read
from apps.api.tests.test_semantic_evaluations_api import completed, invoke
from apps.api.tests.test_source_access_api import grant_member


def discover(v, **changes):
    return invoke(v, CONTEXT_AUTHORITY_BACKFILL_TOOL, {"project_id": v["project_id"], "limit": 3, **changes}, key=uuid4().hex)


def test_canonical_discovery_returns_exact_registration_pins_and_rejects_old_page_after_confirmation(authority):
    v = authority
    context, url = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        remove_registration(session, v["project_id"], enroll=True)
    done = completed(discover(v))
    receipt = done["result"]["context_authority_backfill"]
    http = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/context-authority-backfill", headers=v["headers"])
    assert http.status_code == 200 and receipt["items"] == http.json()["items"]
    assert receipt["page_digest"] == snapshot_digest(http.json())
    assert receipt["items"][0]["registration_request"]["artifact_hash"] == context["metadata"]["artifact_hash"]
    assert receipt["generation_authorized"] is receipt["execution_authorized"] is False
    assert all(secret not in str(receipt) for secret in ("expected_result", "s3://", "artifact_ref", "HTTP 400"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(done["id"], v["project_id"]) == receipt
        command = ToolInvocation.model_validate(done)
        assert observation_receipt_fingerprint(command.result)
    with session_scope() as session:
        assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
    assert v["client"].get(url, headers=v["headers"]).status_code == 409
    completed(register(v, context))
    assert v["client"].get(url, headers=v["headers"]).json()["metadata"] == context["metadata"]
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(PlatformApplicationError):
        app.state.container.tool_evidence.describe(done["id"], v["project_id"])
    assert completed(discover(v))["result"]["context_authority_backfill"]["items"] == []


def test_discovery_verifies_hidden_lookahead_and_original_cursor_and_canonical_never_repairs(authority, monkeypatch):
    v = authority
    contexts = [read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))[0] for _ in range(2)]
    ordered = sorted(contexts, key=lambda item: item["metadata"]["context_id"])
    with session_scope() as session:
        remove_registration(session, v["project_id"], enroll=True)
    url = f"/v1/projects/{v['project_id']}/system-image/context-authority-backfill"
    first = v["client"].get(url, headers=v["headers"], params={"limit": 1}).json()
    assert first["next_after_id"] == ordered[0]["metadata"]["context_id"]
    artifacts = app.state.container.context_packs.artifacts
    original = artifacts.read
    for damaged, params in ((ordered[1], {"limit": 1}), (ordered[0], {"after_id": first["next_after_id"], "limit": 1})):
        def corrupt(*args):
            value = original(*args)
            if value["context_id"] == damaged["metadata"]["context_id"]:
                value["provenance"]["authority_pins"] = []
            return value
        monkeypatch.setattr(artifacts, "read", corrupt)
        response = v["client"].get(url, headers=v["headers"], params=params)
        assert response.status_code == 502 and all(item["metadata"]["context_id"] not in response.text for item in ordered)
        failed = discover(v, **params).json()
        assert failed["status"] == "failed" and failed["result"]["context_authority_backfill"] is None
        with session_scope() as session:
            assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
    monkeypatch.setattr(artifacts, "read", original)
    assert v["client"].get(url, headers=v["headers"], params={"after_id": first["next_after_id"], "limit": 1}).status_code == 200


def test_current_viewer_cannot_discover_ids_or_bypass_reviewer_role_via_canonical_query(authority):
    v = authority
    context, _ = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        remove_registration(session, v["project_id"], enroll=True)
    grant_member(v)
    url = f"/v1/projects/{v['project_id']}/system-image/context-authority-backfill"
    response = v["client"].get(url, headers=v["member_headers"])
    assert response.status_code == 403 and context["metadata"]["context_id"] not in response.text
    query = invoke(v, CONTEXT_AUTHORITY_BACKFILL_TOOL, {"project_id": v["project_id"], "limit": 3},
                   headers=v["member_headers"], key=uuid4().hex)
    assert query.status_code == 403 or query.json()["status"] in {"denied", "failed"}
    assert context["metadata"]["context_id"] not in query.text
    with session_scope() as session:
        assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
