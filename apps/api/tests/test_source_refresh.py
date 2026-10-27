"""Selection and stale-request guards; no database, remote source or model."""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.source_ingestion import SystemImageSourceIngestionApplicationService
from apps.api.app.application.system_image.source_refresh_inputs import source_refresh_selection
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_refresh import SourceRefreshConflict, SourceRefreshSelection
from apps.api.app.domain.system_image.source_access import SourceAccessSnapshot, SourceBindingAccess
from apps.api.app.domain.system_image.source_snapshots import CapturedSourceManifest


HASH = "sha256:" + "a" * 64
REQUEST = {"source_ids": ["code"], "expected_manifest_id": "manifest", "expected_manifest_hash": HASH}


@pytest.mark.parametrize("field,value", [
    ("source_ids", None), ("source_ids", "code"), ("source_ids", []),
    ("source_ids", ["code", "code"]), ("source_ids", [1]), ("source_ids", [True]),
    ("source_ids", [None]), ("source_ids", [[]]), ("source_ids", [" code"]),
    ("source_ids", ["code\n"]), ("source_ids", ["code\x7f"]), ("source_ids", ["x" * 129]),
    ("source_ids", [str(n) for n in range(101)]), ("expected_manifest_id", None),
    ("expected_manifest_id", ""), ("expected_manifest_id", "bad\tmanifest"),
    ("expected_manifest_hash", HASH.upper()), ("expected_manifest_hash", "sha256:" + "z" * 64),
    ("expected_manifest_hash", None), ("expected_manifest_hash", HASH + "\n"),
])
def test_selection_rejects_malformed_fields_without_coercion(field, value):
    with pytest.raises(ValueError):
        source_refresh_selection({**REQUEST, field: value})


@pytest.mark.parametrize("missing", list(REQUEST))
def test_selection_requires_all_three_fields(missing):
    with pytest.raises(ValueError):
        source_refresh_selection({key: value for key, value in REQUEST.items() if key != missing})


def test_legacy_payload_does_not_create_a_selection():
    assert source_refresh_selection({"project_id": "project"}) is None
    value = source_refresh_selection({"project_id": "project", **REQUEST})
    assert value == SourceRefreshSelection(("code",), "manifest", HASH)


def fixture():
    sources = [RawAssetRecord(id=identity, project_id="project", source_type=kind,
        source_uri="/allowed/" + identity, ingestion_status="indexed", content_hash=HASH,
        content_ref="archive:" + identity, evidence_refs=["source-revision:" + identity],
        last_ingested_at="original", permission_status="allowed", file_count=1, byte_count=3)
        for identity, kind in (("code", "code"), ("requirements", "us_doc"), ("tests", "test_asset"))]
    manifest = CapturedSourceManifest("manifest", "project", HASH, "original", ())
    events = []
    project = SimpleNamespace(name="Project", system_image_status="indexed", progress=20)
    projection = SimpleNamespace(mutation_guard=lambda _: nullcontext(), list_sources=lambda _: sources,
        get_project=lambda _: project, save_project=lambda _: events.append("save_project"),
        persist=lambda _: events.append("persist"), refresh=lambda _: events.append("refresh"),
        replace_sources=lambda _project, _sources: events.append("replace_sources"),
        clear_chunks=lambda _: events.append("clear_chunks"))
    def ingest(source):
        events.append(("ingest", source.id))
        return SimpleNamespace(content_hash="sha256:" + "b" * 64, content_ref="new:" + source.id,
            evidence_refs=["new_evidence"], file_count=1, byte_count=10, inventory=None, snapshot=None)
    snapshots = SimpleNamespace(latest_manifest=lambda _: manifest,
        freeze_manifest=lambda _project, items, **_: events.append(("manifest", [s.id for s in items])))
    chunks = SimpleNamespace(materialize=lambda _project, **kwargs: events.append(("chunks", kwargs)))
    scope = SourceAccessSnapshot("project", 0, tuple(SourceBindingAccess(item.id, item.id) for item in sources)).for_actor("actor", "tester")
    authorization = SimpleNamespace(scope=lambda _: scope, require_current=lambda _: None)
    service = SystemImageSourceIngestionApplicationService(projection, SimpleNamespace(ingest=ingest), chunks, snapshots,
        source_authorization=authorization)
    def invoke(selection):
        service.ingest_sources("project", selection=selection,
            ensure_draft_state=lambda: events.append("ensure"), source_binding_incomplete=lambda: False,
            missing_source_types=lambda: [])
    return SimpleNamespace(sources=sources, snapshots=snapshots, manifest=manifest, events=events,
        invoke=invoke, service=service, project=project, authorization=authorization, scope=scope)


def test_refresh_only_mutates_selected_sources_and_freezes_the_full_manifest():
    v = fixture()
    unchanged = deepcopy(v.sources[1:])
    v.invoke(source_refresh_selection(REQUEST))
    assert v.sources[1:] == unchanged
    assert v.sources[0].content_ref == "new:code"
    assert [event for event in v.events if type(event) is tuple and event[0] == "ingest"] == [("ingest", "code")]
    assert ("manifest", ["code", "requirements", "tests"]) in v.events
    assert next(event[1] for event in v.events if type(event) is tuple and event[0] == "chunks")["source_ids"] == ("code",)
    assert v.project.system_image_status == "indexed"


def test_legacy_ingestion_still_refreshes_all_registered_sources():
    v = fixture()
    v.invoke(None)
    assert [event[1] for event in v.events if type(event) is tuple and event[0] == "ingest"] == ["code", "requirements", "tests"]
    assert "source_ids" not in next(event[1] for event in v.events if type(event) is tuple and event[0] == "chunks")


@pytest.mark.parametrize("manifest", [None,
    CapturedSourceManifest("different", "project", HASH, "now", ()),
    CapturedSourceManifest("manifest", "other-project", HASH, "now", ()),
    CapturedSourceManifest("manifest", "project", "sha256:" + "b" * 64, "now", ())])
def test_stale_manifest_is_rejected_before_mutation_or_source_acquisition(manifest):
    v = fixture()
    before = deepcopy(v.sources)
    v.snapshots.latest_manifest = lambda _: manifest
    with pytest.raises(SourceRefreshConflict):
        v.invoke(source_refresh_selection(REQUEST))
    assert v.sources == before and v.events == []


def test_foreign_source_id_is_rejected_before_mutation():
    v = fixture()
    with pytest.raises(ValueError, match="this project's"):
        v.invoke(source_refresh_selection({**REQUEST, "source_ids": ["foreign"]}))
    assert v.events == []


def test_projection_cannot_supply_a_source_from_another_project():
    v = fixture()
    v.sources[0].project_id = "other-project"
    with pytest.raises(ValueError, match="this project's"):
        v.invoke(source_refresh_selection(REQUEST))
    assert v.events == []
