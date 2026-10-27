"""Evidence expansion is authorized against the whole frozen image, not current aliases."""
from dataclasses import replace
from uuid import uuid4

import pytest

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_image_revision_api import selected
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord, CodeEntityEvidenceRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def frozen_evidence_url(v):
    _, _, revision_url = selected(v)
    return f"{revision_url}/objects/{v['obj']['id']}/evidence/{v['evidence']['evidence_id']}"


def test_frozen_evidence_reads_history_and_rejects_other_members(evidence_api, monkeypatch):
    v = evidence_api
    url = frozen_evidence_url(v)
    response = v["client"].get(url, headers=v["headers"], params={"max_lines": 1})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["content"] == "class Orders:\n"
    assert response.json()["next_start_line"] == 2
    v["path"].write_text("class NewOrders:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["path"].unlink()
    old = v["client"].get(url, headers=v["headers"]).json()
    assert "return 'original'" in old["content"]
    assert old["evidence"]["source_revision_id"] == v["revision"]
    calls = []
    monkeypatch.setattr(app.state.container.image_revisions.evidence, "read", lambda *a, **kw: calls.append(a))
    for wrong in (url.replace(v["obj"]["id"], "not-a-member"), url.replace(v["evidence"]["evidence_id"], "other-evidence")):
        denied = v["client"].get(wrong, headers=v["headers"])
        assert denied.status_code == 404, denied.text
    assert calls == []


def test_frozen_evidence_rechecks_scope_after_source_read(evidence_api, monkeypatch):
    v = evidence_api
    url = frozen_evidence_url(v)
    grant_member(v)
    policy(v, (v["member"]["id"],))
    evidence = app.state.container.image_revisions.evidence
    original = evidence.read
    calls = []

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        policy(v)
        return result

    monkeypatch.setattr(evidence, "read", revoke)
    response = v["client"].get(url, headers=v["member_headers"])
    assert response.status_code in (403, 409), response.text
    assert "Orders" not in response.text and calls == [True]
    response = v["client"].get(url, headers=v["member_headers"])
    assert response.status_code == 403 and calls == [True]


def test_frozen_evidence_rejects_wrong_adapter_revision(evidence_api, monkeypatch):
    v = evidence_api
    url = frozen_evidence_url(v)
    service = app.state.container.image_revisions.evidence
    page = service.read(v["project_id"], v["evidence"]["evidence_id"])
    monkeypatch.setattr(service, "read", lambda *a, **kw: replace(page,
        evidence=replace(page.evidence, source_revision_id="wrong-source")))
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 502, response.text
    assert "Orders" not in response.text


def test_batch_verification_rechecks_frozen_scope_after_reader_returns(evidence_api, monkeypatch):
    v = evidence_api
    _, image, _ = selected(v)
    service = app.state.container.image_revisions
    original = service.evidence.verify_many
    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        policy(v)
        return result
    monkeypatch.setattr(service.evidence, "verify_many", revoke)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(StaleSourceAccessScope):
            service.verify_evidence_selection(v["project_id"], image["image_revision_id"],
                ((v["obj"]["id"], v["evidence"]["evidence_id"]),))


def test_batch_verification_rejects_faulty_adapter_binding(evidence_api, monkeypatch):
    v = evidence_api
    _, image, _ = selected(v)
    service = app.state.container.image_revisions
    original = service.evidence.verify_many
    monkeypatch.setattr(service.evidence, "verify_many", lambda *args, **kwargs:
        [replace(item, binding_id="another-binding") for item in original(*args, **kwargs)])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ImageRevisionIntegrityError):
            service.verify_evidence_selection(v["project_id"], image["image_revision_id"],
                ((v["obj"]["id"], v["evidence"]["evidence_id"]),))


def test_an_unrelated_hidden_candidate_input_blocks_evidence_before_source_read(evidence_api, monkeypatch):
    v = evidence_api
    list_url, old, _ = selected(v)
    other = v["path"].parent / "other.py"
    other.write_text("class Payments:\n    pass\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(other)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    images = v["client"].get(list_url, headers=v["headers"]).json()["items"]
    current = next(item for item in images if item["image_revision_id"] != old["image_revision_id"])
    read_url = f"{list_url}/{current['image_revision_id']}"
    # The old code symbol/evidence still belongs to the new multi-source image.
    members = v["client"].get(read_url, headers=v["headers"], params={"section": "members", "limit": 100}).json()["items"]
    member = next(item for item in members if v["evidence"]["evidence_id"] in item["evidence_ids"])
    url = f"{read_url}/objects/{member['object_id']}/evidence/{v['evidence']['evidence_id']}"
    grant_member(v)
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    hidden = next(item.binding_id for item in snapshot.bindings if item.binding_id != v["evidence"]["binding_id"])
    repo.set_policy(v["project_id"], hidden, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
                    changed_by=v["owner"]["id"], invocation_id="deny-other-frozen-input")
    calls = []
    monkeypatch.setattr(app.state.container.image_revisions.evidence, "read", lambda *a, **kw: calls.append(a))
    response = v["client"].get(url, headers=v["member_headers"])
    assert response.status_code == 403, response.text
    assert calls == [] and "Orders" not in response.text


def test_newly_registered_valid_evidence_is_excluded_until_another_image_is_frozen(evidence_api):
    v = evidence_api
    list_url, old, old_url = selected(v)
    later_id = str(uuid4())
    # Same verified bytes/locator, a later extractor observation associated with
    # the same code revision. It is readable independently but not in the old image.
    with session_scope() as session:
        original = session.get(SourceEvidenceRecord, v["evidence"]["evidence_id"])
        values = {column.name: getattr(original, column.name) for column in SourceEvidenceRecord.__table__.columns
                  if column.name not in {"evidence_id", "identity_hash"}}
        values["extractor_version"] += "/later-observation"
        session.add(SourceEvidenceRecord(evidence_id=later_id,
            identity_hash=snapshot_digest({key: value for key, value in values.items() if key != "captured_at"}), **values))
        session.flush()
        session.add(CodeEntityEvidenceRecord(entity_revision_id=v["obj"]["code_reference"]["entity_revision_id"],
            evidence_id=later_id, project_id=v["project_id"], binding_id=original.binding_id, source_revision_id=v["revision"]))
    direct = v["client"].get(f"{v['url']}/{later_id}", headers=v["headers"])
    assert direct.status_code == 200 and "original" in direct.json()["content"]
    suffix = f"/objects/{v['obj']['id']}/evidence/{later_id}"
    rejected = v["client"].get(old_url + suffix, headers=v["headers"])
    assert rejected.status_code == 404 and "original" not in rejected.text
    v["invoke"]("system_image.context.materialize")
    images = v["client"].get(list_url, headers=v["headers"]).json()["items"]
    new = next(item for item in images if item["image_revision_id"] != old["image_revision_id"])
    response = v["client"].get(f"{list_url}/{new['image_revision_id']}{suffix}", headers=v["headers"])
    assert response.status_code == 200 and response.json() == direct.json()
    assert v["client"].get(old_url + suffix, headers=v["headers"]).status_code == 404
