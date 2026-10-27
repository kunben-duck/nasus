"""Allocation/ownership specimens, not source-provider or performance gold."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image import image_revision_queries as queries
from apps.api.app.domain.system_image.image_revision import build_image_artifact, ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, SourceAccessScope
from apps.api.tests.test_image_revision import candidate, header


OPERATIONS = ("documents", "sources", "objects", "members", "relationships", "source_members", "evidence", "verify", "document")


def reader():
    manifest, objects, relationships = candidate()
    objects.append({"id": "requirement", "name": "Original requirement", "document_reference": {
        "document_revision_id": "document-revision", "source_revision_id": "source-revision"}})
    payload, _ = build_image_artifact(manifest, "baseline", objects, relationships)
    for member in payload["members"]:
        if member["kind"] != "legacy_observation":
            member["evidence_ids"] = [member["object_id"] + "-evidence"]
    summary = replace(header(payload), object_count=len(objects))
    state = SimpleNamespace(allowed=True, metadata=0, artifacts=0, authority=0)

    def metadata(*args):
        state.metadata += 1
        return summary, "original-private-archive", frozenset({"binding"})

    def artifact(*args):
        state.artifacts += 1
        return deepcopy(payload)

    def current(scope):
        state.authority += 1
        if not state.allowed:
            raise SourceAccessDenied("source access revoked")

    scope = SourceAccessScope("project", "actor", "tester", 0, frozenset({"binding"}),
        frozenset({"source"}), "original-scope", False)

    def evidence(_project, ident, **kwargs):
        return SimpleNamespace(integrity="verified", evidence=SimpleNamespace(evidence_id=ident,
            source_revision_id="source-revision", binding_id="binding"))

    def document(_project, ident, **kwargs):
        return {"document": {"document_revision_id": ident, "source_revision_id": "source-revision"},
            "evidence": [{"evidence_id": "requirement-evidence"}]}

    service = queries.ImageRevisionQueryApplicationService(SimpleNamespace(get=metadata),
        SimpleNamespace(read=artifact), SimpleNamespace(scope=lambda _: scope, require_current=current),
        SimpleNamespace(read=evidence), SimpleNamespace(read=document))
    return service, payload, state


def select(service, operation):
    args = ("project", "image")
    if operation == "documents":
        return service.frozen_document_members(*args)[1]
    if operation == "sources":
        return service.frozen_source_members(*args)[1]
    if operation == "evidence":
        return service.read_evidence(*args, "code", "code-evidence")
    if operation == "verify":
        return service.verify_evidence_selection(*args, (("code", "code-evidence"),))
    if operation == "document":
        return service.read_document(*args, "requirement")
    return service.read(*args, section=operation, limit=1).items


@pytest.mark.parametrize("operation", OPERATIONS)
def test_selection_does_not_copy_the_complete_already_verified_image(monkeypatch, operation):
    service, payload, state = reader()
    copied = []
    original = queries.deepcopy

    def counted(value):
        if type(value) is dict and value.get("schema") == payload["schema"]:
            copied.append(value)
        return original(value)

    monkeypatch.setattr(queries, "deepcopy", counted)
    with service.verified_read_session():
        service.frozen_snapshot("project", "image")
        copied.clear()
        before = state.authority
        first = select(service, operation)
        second = select(service, operation)
        assert first == second and state.authority > before
        assert copied == []
        assert state.artifacts == 1
    assert service._current_verified_reads() is None


@pytest.mark.parametrize("operation", ("documents", "sources", "objects", "members", "relationships", "source_members"))
def test_selected_return_values_never_expose_the_cached_image(operation):
    service, payload, _ = reader()
    with service.verified_read_session():
        expected = deepcopy(select(service, operation))
        first = select(service, operation)
        first[0].clear()
        assert select(service, operation) == expected
        assert service.frozen_snapshot("project", "image")[1] == payload


@pytest.mark.parametrize("operation", OPERATIONS)
def test_selected_reads_still_recheck_live_source_access(operation):
    service, _, state = reader()
    with service.verified_read_session():
        select(service, operation)
        state.allowed = False
        before = state.authority
        with pytest.raises(SourceAccessDenied):
            select(service, operation)
        assert state.authority > before and state.artifacts == 1


def test_partial_output_still_requires_complete_original_membership():
    service, payload, state = reader()
    payload["members"][-1]["object_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ImageRevisionIntegrityError):
        select(service, "objects")
    assert state.artifacts == 1 and service._current_verified_reads() is None


def test_full_snapshot_keeps_its_isolated_copy_contract():
    service, payload, state = reader()
    with service.verified_read_session():
        first = service.frozen_snapshot("project", "image")[1]
        first["objects"][0].clear()
        second = service.frozen_snapshot("project", "image")[1]
        assert second == payload
        second["members"].clear()
        assert service.frozen_snapshot("project", "image")[1] == payload
    assert state.artifacts == 1


def test_source_inventory_still_verifies_unselected_original_objects():
    service, payload, state = reader()
    payload["members"][-1]["object_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ImageRevisionIntegrityError):
        service.frozen_source_members("project", "image")
    assert state.artifacts == 1 and service._current_verified_reads() is None
