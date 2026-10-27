"""Real PG revocation after an earlier receipt passed must discard the batch."""
from copy import deepcopy

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.main import app
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_ingestion_access_api import facts, revisions
from apps.api.tests.test_source_refresh_api import add_optional, read, refresh, selection


@pytest.mark.parametrize("endpoint", ["tool-invocations", "audit-events"])
@pytest.mark.parametrize("timing", ["before_later_check", "after_later_check"])
def test_late_source_revocation_discards_previously_visible_receipts(evidence_api, tmp_path, monkeypatch, endpoint, timing):
    v = evidence_api
    _, image, requirement = add_optional(v, tmp_path)
    code = next(item for item in image["sources"] if item["source_type"] == "code")
    first = refresh(v, selection(image, code["id"]))
    second = refresh(v, selection(read(v), requirement["id"]))
    grant_member(v)
    policy(v, (v["member"]["id"],))
    params = {"conversation_id": v["conversation"].json()["id"]}
    if endpoint == "tool-invocations":
        params["tool_id"] = "system_image.sources.ingest"
    url = f"/v1/{endpoint}"
    baseline = v["client"].get(url, headers=v["member_headers"], params=params)
    assert baseline.status_code == 200, baseline.text
    assert first["id"] in baseline.text and second["id"] in baseline.text
    repository = ConversationRepository()
    original = {item["id"]: deepcopy(repository.get_tool_invocation(item["id"]).model_dump(mode="json"))
        for item in (first, second)}
    original_facts, original_revisions = facts(v), revisions(v)
    access = app.state.container.platform._tool_invocations._read_resources
    authorize = access.require_access
    state = app.state.container.platform._tool_invocations._state
    method = "list_invocations" if endpoint == "tool-invocations" else "list_audit_events"
    load_rows = getattr(state, method)

    def earlier_receipt_first():
        # Arrange the revocation schedule, not authorization or query facts:
        # PostgreSQL's unordered row scan need not follow creation time.
        def rank(item):
            ident = item.id if endpoint == "tool-invocations" else item.tool_invocation_id
            return 0 if ident == first["id"] else 1 if ident == second["id"] else 2
        return sorted(load_rows(), key=rank)

    monkeypatch.setattr(state, method, earlier_receipt_first)
    checked, changed = [], []

    def revoke_during_later_receipt(item):
        if item.id == second["id"] and not changed:
            assert first["id"] in checked, "The earlier real receipt must already have passed."
            if timing == "before_later_check":
                policy(v)
            authorize(item)
            if timing == "after_later_check":
                policy(v)
            changed.append(item.id)
        else:
            authorize(item)
        checked.append(item.id)

    monkeypatch.setattr(access, "require_access", revoke_during_later_receipt)
    denied = v["client"].get(url, headers=v["member_headers"], params=params)
    assert changed == [second["id"]]
    assert denied.status_code == 403, denied.text
    for value in (first["id"], code["id"], image["source_manifest"]["content_hash"], str(v["path"])):
        assert value not in denied.text
    assert facts(v) == original_facts and revisions(v) == original_revisions
    assert {ident: repository.get_tool_invocation(ident).model_dump(mode="json") for ident in original} == original
    # New reads after a policy change may omit private records. They must still
    # retain the independently readable requirement receipt and immutable facts.
    hidden = v["client"].get(url, headers=v["member_headers"], params=params)
    assert hidden.status_code == 200 and first["id"] not in hidden.text and second["id"] in hidden.text
    policy(v, (v["member"]["id"],))
    restored = v["client"].get(url, headers=v["member_headers"], params=params)
    assert restored.status_code == 200 and restored.json() == baseline.json(), restored.text
    assert {ident: repository.get_tool_invocation(ident).model_dump(mode="json") for ident in original} == original


@pytest.mark.parametrize("endpoint", ["tool-invocations", "audit-events"])
@pytest.mark.parametrize("change", ["source_policy", "membership_revoked", "administrator_demoted"])
def test_receipt_cohort_rechecks_policy_and_membership_after_all_individual_checks(evidence_api, tmp_path, monkeypatch, endpoint, change):
    v = evidence_api
    _, image, requirement = add_optional(v, tmp_path)
    code = next(item for item in image["sources"] if item["source_type"] == "code")
    first = refresh(v, selection(image, code["id"]))
    refresh(v, selection(read(v), requirement["id"]))
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    role = "project_admin" if change == "administrator_demoted" else "viewer"
    assert v["client"].put(membership, headers=v["headers"], json={"role": role}).status_code == 200
    policy(v, () if change == "administrator_demoted" else (v["member"]["id"],))
    original = ConversationRepository().get_tool_invocation(first["id"]).model_dump(mode="json")
    original_facts, original_revisions = facts(v), revisions(v)
    from apps.api.tests.test_tool_invocation_resolution_api import source_receipt_authorization
    access = source_receipt_authorization()
    recheck = access.require_current_many
    cohorts = []

    def change_before_atomic_check(scopes):
        cohorts.append(scopes)
        assert len(scopes) == 1 and scopes[0].project_id == v["project_id"]
        if change == "source_policy":
            policy(v)
        elif change == "membership_revoked":
            assert v["client"].delete(membership, headers=v["headers"]).status_code == 200
        else:
            assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
        recheck(scopes)

    monkeypatch.setattr(access, "require_current_many", change_before_atomic_check)
    params = {"conversation_id": v["conversation"].json()["id"]}
    response = v["client"].get(f"/v1/{endpoint}", headers=v["member_headers"], params=params)
    assert len(cohorts) == 1 and response.status_code == 403, response.text
    assert code["id"] not in response.text and first["id"] not in response.text
    assert ConversationRepository().get_tool_invocation(first["id"]).model_dump(mode="json") == original
    assert facts(v) == original_facts and revisions(v) == original_revisions


@pytest.mark.parametrize("endpoint", ["tool-invocations", "audit-events"])
def test_multi_project_receipts_use_one_final_pg_authorization_cohort(evidence_api, tmp_path, monkeypatch, endpoint):
    v = evidence_api
    image = read(v)
    code = next(item for item in image["sources"] if item["source_type"] == "code")
    first = refresh(v, selection(image, code["id"]))
    grant_member(v)
    policy(v, (v["member"]["id"],))
    client = v["client"]
    created = client.post("/v1/projects", headers=v["headers"], json={"name": f"Cohort peer {v['project_id']}"})
    assert created.status_code == 200, created.text
    other_id = created.json()["id"]
    membership = f"/v1/projects/{other_id}/members/{v['member']['id']}"
    assert client.put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    path = tmp_path / "peer.py"
    path.write_text("class Peer:\n    pass\n")

    def invoke(tool, payload=None):
        response = client.post("/v1/tool-invocations", headers=v["headers"], json={
            "tool_id": tool, "input": {"project_id": other_id, **(payload or {})}})
        assert response.status_code == 200 and response.json()["status"] == "completed", response.text
        return response.json()

    invoke("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(path)}]})
    second = invoke("system_image.sources.ingest")
    params = {"tool_id": "system_image.sources.ingest"} if endpoint == "tool-invocations" else {}
    url = f"/v1/{endpoint}"
    baseline = client.get(url, headers=v["member_headers"], params=params)
    assert baseline.status_code == 200 and first["id"] in baseline.text and second["id"] in baseline.text
    from apps.api.tests.test_tool_invocation_resolution_api import source_receipt_authorization
    access = source_receipt_authorization().repository
    load = access.load_authorized_snapshots
    cohorts = []

    def revoke_before_one_statement(project_ids, actor_id, **kwargs):
        assert set(project_ids) == {v["project_id"], other_id} and actor_id == v["member"]["id"]
        cohorts.append(project_ids)
        policy(v)
        return load(project_ids, actor_id, **kwargs)

    monkeypatch.setattr(access, "load_authorized_snapshots", revoke_before_one_statement)
    denied = client.get(url, headers=v["member_headers"], params=params)
    assert len(cohorts) == 1 and denied.status_code == 403, denied.text
    assert first["id"] not in denied.text and code["id"] not in denied.text
    repository = ConversationRepository()
    assert repository.get_tool_invocation(first["id"]).model_dump(mode="json") == first
    assert repository.get_tool_invocation(second["id"]).model_dump(mode="json") == second
    monkeypatch.setattr(access, "load_authorized_snapshots", load)
    hidden = client.get(url, headers=v["member_headers"], params=params)
    assert hidden.status_code == 200 and first["id"] not in hidden.text and second["id"] in hidden.text
    policy(v, (v["member"]["id"],))
    restored = client.get(url, headers=v["member_headers"], params=params)
    assert restored.status_code == 200 and restored.json() == baseline.json(), restored.text
    assert repository.get_tool_invocation(first["id"]).model_dump(mode="json") == first
    assert repository.get_tool_invocation(second["id"]).model_dump(mode="json") == second


@pytest.mark.parametrize("endpoint", ["tool-invocations", "audit-events"])
@pytest.mark.parametrize("status", [409, 503, 504])
def test_late_receipt_verification_failure_does_not_return_partial_http_success(
        evidence_api, tmp_path, monkeypatch, endpoint, status):
    v = evidence_api
    _, image, requirement = add_optional(v, tmp_path)
    code = next(item for item in image["sources"] if item["source_type"] == "code")
    first = refresh(v, selection(image, code["id"]))
    second = refresh(v, selection(read(v), requirement["id"]))
    params = {"conversation_id": v["conversation"].json()["id"]}
    if endpoint == "tool-invocations":
        params["tool_id"] = "system_image.sources.ingest"
    url = f"/v1/{endpoint}"
    baseline = v["client"].get(url, headers=v["headers"], params=params)
    assert baseline.status_code == 200 and all(item["id"] in baseline.text for item in (first, second))
    service = app.state.container.platform._tool_invocations
    access, state = service._read_resources, service._state
    authorize = access.require_access
    method = "list_invocations" if endpoint == "tool-invocations" else "list_audit_events"
    load_rows = getattr(state, method)
    repository = ConversationRepository()
    originals = {item["id"]: repository.get_tool_invocation(item["id"]).model_dump(mode="json")
        for item in (first, second)}
    original_facts, original_revisions = facts(v), revisions(v)
    checked = []

    def earlier_receipt_first():
        def rank(item):
            ident = item.id if endpoint == "tool-invocations" else item.tool_invocation_id
            return 0 if ident == first["id"] else 1 if ident == second["id"] else 2
        return sorted(load_rows(), key=rank)

    def fail_later_receipt(command):
        if command.id == second["id"]:
            assert first["id"] in checked
            raise PlatformApplicationError("receipt_verification_failed", "Original receipt could not be verified.", status)
        authorize(command)
        checked.append(command.id)

    monkeypatch.setattr(state, method, earlier_receipt_first)
    monkeypatch.setattr(access, "require_access", fail_later_receipt)
    failed = v["client"].get(url, headers=v["headers"], params=params)
    assert failed.status_code == status, failed.text
    for value in (first["id"], second["id"], code["id"], str(v["path"]), image["source_manifest"]["content_hash"]):
        assert value not in failed.text
    assert facts(v) == original_facts and revisions(v) == original_revisions
    assert {ident: repository.get_tool_invocation(ident).model_dump(mode="json") for ident in originals} == originals
    monkeypatch.setattr(access, "require_access", authorize)
    recovered = v["client"].get(url, headers=v["headers"], params=params)
    assert recovered.status_code == 200 and recovered.json() == baseline.json()


@pytest.mark.parametrize("endpoint", ["tool-invocations", "audit-events"])
def test_missing_source_receipt_reader_returns_unavailable_not_empty_history(evidence_api, monkeypatch, endpoint):
    v = evidence_api
    image = read(v)
    code = next(item for item in image["sources"] if item["source_type"] == "code")
    original = refresh(v, selection(image, code["id"]))
    service = app.state.container.platform._tool_invocations
    params = {"conversation_id": v["conversation"].json()["id"]}
    if endpoint == "tool-invocations":
        params["tool_id"] = "system_image.sources.ingest"
    url = f"/v1/{endpoint}"
    baseline = v["client"].get(url, headers=v["headers"], params=params)
    assert baseline.status_code == 200 and original["id"] in baseline.text
    reader = service._read_resources
    monkeypatch.setattr(service, "_read_resources", None)
    failed = v["client"].get(url, headers=v["headers"], params=params)
    assert failed.status_code == 503, failed.text
    assert original["id"] not in failed.text and code["id"] not in failed.text
    assert ConversationRepository().get_tool_invocation(original["id"]).model_dump(mode="json") == original
    monkeypatch.setattr(service, "_read_resources", reader)
    recovered = v["client"].get(url, headers=v["headers"], params=params)
    assert recovered.status_code == 200 and recovered.json() == baseline.json()
