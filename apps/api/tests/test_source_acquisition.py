"""Immutable acquisition admission, independent of DB, connectors and frameworks."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.source_refresh_inputs import source_refresh_selection
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.domain.system_image.source_acquisition import (
    AcquisitionSourcePin, SourceAcquisitionIntent, SourceAcquisitionIntentConflict,
)
from apps.api.app.domain.system_image.source_acquisition_results import SourceAcquisitionResult, acquisition_results_hash
from apps.api.tests.test_source_refresh import HASH, REQUEST, fixture


def intent(**changes):
    return SourceAcquisitionIntent(**{
        "invocation_id": "command", "project_id": "project", "actor_id": "actor",
        "command_hash": HASH, "selection_mode": "selected",
        "sources": (AcquisitionSourcePin("code", "binding", HASH),),
        "origin_manifest_id": "manifest", "origin_manifest_hash": HASH, **changes,
    })


@pytest.mark.parametrize("field,value", [
    ("source_id", ""), ("source_id", " leading"), ("source_id", "bad\n"),
    ("binding_id", True), ("binding_id", "x" * 513), ("binding_id", "bad\x7f"),
    ("identity_hash", HASH.upper()), ("identity_hash", "sha256:" + "z" * 64),
])
def test_source_pin_rejects_invalid_identities(field, value):
    with pytest.raises(ValueError):
        AcquisitionSourcePin(**{"source_id": "code", "binding_id": "binding", "identity_hash": HASH, field: value})


@pytest.mark.parametrize("changes", [
    {"invocation_id": ""}, {"project_id": "wrong\n"}, {"actor_id": None},
    {"command_hash": HASH.upper()}, {"selection_mode": "latest"}, {"sources": []},
    {"sources": ()}, {"sources": (object(),)},
    {"sources": (AcquisitionSourcePin("code", "b1", HASH), AcquisitionSourcePin("code", "b2", HASH))},
    {"sources": (AcquisitionSourcePin("a", "b1", HASH), AcquisitionSourcePin("b", "b1", HASH))},
    {"sources": (AcquisitionSourcePin("z", "b1", HASH), AcquisitionSourcePin("a", "b2", HASH))},
    {"origin_manifest_id": None}, {"origin_manifest_hash": None},
    {"origin_manifest_id": None, "origin_manifest_hash": None},
    {"origin_manifest_hash": "not-a-digest"},
])
def test_intent_rejects_ambiguous_or_unpinned_input(changes):
    with pytest.raises(ValueError):
        intent(**changes)


@pytest.mark.parametrize("mode,count,valid", [("selected", 100, True), ("selected", 101, False),
    ("whole_project", 1000, True), ("whole_project", 1001, False)])
def test_intent_source_limits_are_explicit_not_truncation(mode, count, valid):
    pins = tuple(AcquisitionSourcePin(f"source-{n:04d}", f"binding-{n}", HASH) for n in range(count))
    if valid:
        assert len(intent(selection_mode=mode, sources=pins).sources) == count
    else:
        with pytest.raises(ValueError):
            intent(selection_mode=mode, sources=pins)


def test_whole_project_first_admission_may_have_no_previous_manifest():
    value = intent(selection_mode="whole_project", origin_manifest_id=None, origin_manifest_hash=None)
    assert value.content_hash != intent().content_hash
    with pytest.raises(FrozenInstanceError):
        value.actor_id = "other"


@pytest.mark.parametrize("changes", [
    {"actor_id": "other"}, {"project_id": "other"}, {"invocation_id": "other"},
    {"command_hash": "sha256:" + "b" * 64}, {"origin_manifest_id": "new-manifest"},
    {"origin_manifest_hash": "sha256:" + "b" * 64}, {"selection_mode": "whole_project"},
    {"sources": (AcquisitionSourcePin("code", "different-binding", HASH),)},
])
def test_reentry_cannot_replace_any_original_pin(changes):
    original = intent()
    original.require_same(intent())
    with pytest.raises(SourceAcquisitionIntentConflict):
        original.require_same(intent(**changes))


def ingest(v, selection=None):
    v.service.ingest_sources("project", selection=selection, invocation_id="command",
        ensure_draft_state=lambda: v.events.append("ensure"), source_binding_incomplete=lambda: False,
        missing_source_types=lambda: [])


@pytest.mark.parametrize("selected", [False, True])
def test_admission_precedes_every_mutable_marker_and_connector(selected):
    v = fixture()
    before = deepcopy(v.sources)
    selection = source_refresh_selection(REQUEST) if selected else None
    def admit(command, scope, sources, requested):
        assert command == "command" and scope == v.scope and requested == selection
        assert sources == (("code",) if selected else ("code", "requirements", "tests"))
        assert v.events == [] and v.sources == before
        v.events.append("admitted")
        return intent(selection_mode="selected" if selected else "whole_project",
            sources=tuple(AcquisitionSourcePin(source_id, source_id, HASH) for source_id in sorted(sources)))
    def save(original, scope, source, ingested):
        assert original.project_id == scope.project_id and source.ingestion_status == "ingesting"
        v.events.append(("result", source.id))
        return SourceAcquisitionResult("command", "project", source.id, source.id, original.content_hash,
            "legacy_unverified", "2026-10-09T00:00:00+00:00", ingested.content_hash, ingested.content_ref,
            tuple(ingested.evidence_refs), ingested.file_count, ingested.byte_count, None, None, None, None)
    v.service._acquisition_intents = SimpleNamespace(admit=admit, results=lambda *args: (), record_success=save,
        commit_manifest=lambda *args: v.events.append("manifest_receipt"))
    ingest(v, selection)
    assert v.events[0] == "admitted"
    assert "manifest_receipt" in v.events
    assert not any(type(event) is tuple and event[0] == "manifest" for event in v.events)


@pytest.mark.parametrize("error,code,status", [
    (SourceAcquisitionIntentConflict("private conflict"), "source_acquisition_scope_changed", 409),
    (SourceAccessDenied("private source"), "source_access_denied", 403),
    (ValueError("private invalid source"), "source_acquisition_scope_invalid", 409),
    (OSError("secret storage credentials"), "source_acquisition_unavailable", 503),
])
def test_failed_admission_is_sanitized_and_does_not_touch_projection(error, code, status):
    v = fixture()
    before = deepcopy(v.sources)
    def fail(*args):
        raise error
    v.service._acquisition_intents = SimpleNamespace(admit=fail)
    with pytest.raises(PlatformApplicationError) as failure:
        ingest(v)
    assert failure.value.code == code and failure.value.status_code == status
    assert "private" not in str(failure.value) and "credentials" not in str(failure.value)
    assert v.events == [] and v.sources == before


def test_missing_admission_port_does_not_fall_back_to_inline_canonical_ingestion():
    v = fixture()
    with pytest.raises(PlatformApplicationError) as failure:
        ingest(v)
    assert failure.value.code == "source_acquisition_unavailable" and v.events == []


def test_revocation_after_admission_stops_before_markers_or_connectors():
    v = fixture()
    before = deepcopy(v.sources)
    def admit(*args):
        v.authorization.require_current = lambda _: (_ for _ in ()).throw(SourceAccessDenied("revoked"))
    v.service._acquisition_intents = SimpleNamespace(admit=admit)
    with pytest.raises(PlatformApplicationError) as failure:
        ingest(v)
    assert failure.value.code == "source_access_denied" and v.events == [] and v.sources == before


def outcome(**changes):
    return SourceAcquisitionResult(**{
        "invocation_id": "command", "project_id": "project", "source_id": "code", "binding_id": "binding",
        "intent_hash": intent().content_hash, "status": "captured", "acquired_at": "2026-10-09T00:00:00+00:00",
        "content_hash": HASH, "content_ref": "s3://private/source-manifest", "evidence_refs": ("source:code",),
        "file_count": 1, "byte_count": 0, "source_revision_id": "revision", "snapshot_hash": HASH,
        "inventory_id": "inventory", "inventory_hash": HASH, **changes,
    })


@pytest.mark.parametrize("changes", [
    {"invocation_id": ""}, {"source_id": "bad\n"}, {"intent_hash": "invalid"},
    {"status": "indexed"}, {"status": "failed"}, {"status": "legacy_unverified"},
    {"acquired_at": None}, {"acquired_at": "not-a-date"}, {"acquired_at": "2026-10-09T00:00:00"},
    {"evidence_refs": []}, {"evidence_refs": ()}, {"evidence_refs": ("bad\n",)},
    {"file_count": True}, {"file_count": 0}, {"byte_count": -1},
    {"source_revision_id": None}, {"snapshot_hash": None}, {"inventory_hash": None},
    {"content_hash": "invalid"}, {"content_ref": ""}, {"failure_reason": "source_connector_failed"},
    {"permission_status": "denied"},
])
def test_acquisition_outcome_cannot_invent_captured_content_or_unpinned_artifacts(changes):
    with pytest.raises(ValueError):
        outcome(**changes)


def test_results_digest_requires_exact_complete_original_selection():
    result = outcome()
    assert acquisition_results_hash(intent(), (result,))
    for results in ((), (result, result), (outcome(intent_hash=HASH),), (outcome(source_id="other"),)):
        with pytest.raises(ValueError):
            acquisition_results_hash(intent(), results)
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"


def test_failure_carries_no_content_or_private_connector_message():
    result = outcome(status="failed", content_hash=None, content_ref=None, evidence_refs=(), file_count=0,
        source_revision_id=None, snapshot_hash=None, failure_reason="source_acquisition_incomplete")
    assert result.result_hash
    with pytest.raises(ValueError):
        outcome(status="failed", content_hash=None, content_ref=None, evidence_refs=(), file_count=0,
            source_revision_id=None, snapshot_hash=None, failure_reason="private/path/credentials")
