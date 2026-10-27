from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.source_deltas import SourceBodyVerification, SourceDeltaQueryApplicationService, SourceRevisionReadTarget
from apps.api.app.domain.system_image.source_access import SourceAccessSnapshot, SourceBindingAccess, StaleSourceAccessScope
from apps.api.app.domain.system_image.source_delta import SourceDeltaIntegrityError, SourceDeltaPageTooLarge
from apps.api.tests.test_source_delta import snapshot


@pytest.fixture
def delta_app():
    snapshots = {"one": snapshot("one", {"old.py": "a", "stay.py": "same"}),
                 "two": snapshot("two", {"new.py": "a", "stay.py": "same"})}
    scope = SourceAccessSnapshot("project", 0, (SourceBindingAccess("binding", "source"),)).for_actor("actor", "viewer")
    calls = []
    def targets(project_id, before, after, *, binding_ids):
        assert project_id == "project" and binding_ids == frozenset({"binding"})
        return tuple(SourceRevisionReadTarget(snapshots[key].pin, "source", "private-ref", "policy", 2, 5)
                     for key in (before, after))
    def read(target):
        calls.append(target.pin.source_revision_id)
        return snapshots[target.pin.source_revision_id]
    auth = SimpleNamespace(scope=lambda project: scope, require_current=lambda current: None)
    app = SourceDeltaQueryApplicationService(SimpleNamespace(get_pair=targets), SimpleNamespace(read=read), auth)
    return app, snapshots, calls


def test_pages_and_rename_section_share_the_full_fixed_delta_digest(delta_app):
    app, _, calls = delta_app
    first = app.read("project", "one", "two", limit=1)
    second = app.read("project", "one", "two", offset=1, limit=2)
    rename = app.read("project", "one", "two", section="rename_candidates")
    deleted = app.read("project", "one", "two", kind="deleted")
    assert first.next_offset == 1 and second.next_offset is None
    assert first.content_hash == second.content_hash == rename.content_hash == deleted.content_hash
    assert first.total == 3 and rename.total == deleted.total == 1
    assert not rename.items[0].identity_preserved and len(calls) == 8


@pytest.mark.parametrize("kwargs", [{"limit": True}, {"limit": 101}, {"offset": -1}, {"section": "raw"},
    {"kind": "accepted"}, {"section": "rename_candidates", "kind": "added"}])
def test_invalid_parameters_do_not_read_storage(delta_app, kwargs):
    app, _, calls = delta_app
    with pytest.raises(ValueError):
        app.read("project", "one", "two", **kwargs)
    assert not calls


def test_revocation_between_manifest_reads_stops_before_the_second_read(delta_app):
    app, _, calls = delta_app
    def current(scope):
        if calls:
            raise StaleSourceAccessScope("revoked")
    app.authorization.require_current = current
    with pytest.raises(StaleSourceAccessScope):
        app.read("project", "one", "two")
    assert calls == ["one"]


def test_revocation_after_comparison_discards_all_returned_paths(delta_app):
    app, _, calls = delta_app
    def current(scope):
        if len(calls) == 2:
            raise StaleSourceAccessScope("revoked")
    app.authorization.require_current = current
    with pytest.raises(StaleSourceAccessScope):
        app.read("project", "one", "two")


def test_archive_pin_mismatch_and_missing_target_fail_closed(delta_app):
    app, snapshots, _ = delta_app
    app.reader.read = lambda target: replace(snapshots[target.pin.source_revision_id],
        pin=replace(target.pin, manifest_hash=snapshots["two"].pin.manifest_hash))
    with pytest.raises(SourceDeltaIntegrityError, match="different source"):
        app.read("project", "one", "two")
    app.repository.get_pair = lambda *args, **kwargs: ()
    with pytest.raises(SourceDeltaIntegrityError, match="both complete"):
        app.read("project", "one", "two")


def test_large_paths_require_smaller_pages_without_truncating_counts(delta_app):
    app, snapshots, _ = delta_app
    files = {"src/" + "x" * 2000 + f"{index:02}.py": str(index) for index in range(40)}
    snapshots.update(one=snapshot("one", files), two=snapshot("two", files))
    with pytest.raises(SourceDeltaPageTooLarge):
        app.read("project", "one", "two", limit=40)
    page = app.read("project", "one", "two", limit=1)
    assert page.counts["unchanged"] == page.total == 40 and page.next_offset == 1


def test_revocation_during_archive_read_takes_precedence_over_page_size_errors(delta_app):
    app, snapshots, calls = delta_app
    files = {"src/" + "x" * 2000 + f"{index:02}.py": str(index) for index in range(40)}
    snapshots.update(one=snapshot("one", files), two=snapshot("two", files))
    def current(scope):
        if len(calls) == 2:
            raise StaleSourceAccessScope("revoked")
    app.authorization.require_current = current
    with pytest.raises(StaleSourceAccessScope):
        app.read("project", "one", "two", limit=40)


def test_revocation_during_persistence_query_prevents_archive_reads(delta_app):
    app, _, calls = delta_app
    original = app.repository.get_pair
    def deny(scope):
        raise StaleSourceAccessScope("revoked")
    def revoked(*args, **kwargs):
        result = original(*args, **kwargs)
        app.authorization.require_current = deny
        return result
    app.repository.get_pair = revoked
    with pytest.raises(StaleSourceAccessScope):
        app.read("project", "one", "two")
    assert not calls


@pytest.mark.parametrize("failure", ["pin", "file_count", "byte_count"])
def test_full_body_verification_rejects_adapter_scope_or_count_mismatch(delta_app, failure):
    app, snapshots, _ = delta_app
    expected = snapshots["one"]
    result = SourceBodyVerification(expected.pin, len(expected.files), sum(item.byte_count for item in expected.files),
                                    "sha256:" + "1" * 64)
    if failure == "pin":
        result = replace(result, pin=snapshots["two"].pin)
    elif failure == "file_count":
        result = replace(result, verified_file_count=1)
    else:
        result = replace(result, verified_byte_count=0)
    app.reader.verify_bodies = lambda *args, **kwargs: result
    with pytest.raises(SourceDeltaIntegrityError, match="omitted"):
        app.verify_bodies("project", "one", expected)


def test_full_body_verification_checks_current_acl_after_adapter_returns(delta_app):
    app, snapshots, calls = delta_app
    def verify(target, expected, *, require_current):
        calls.append("verified")
        return SourceBodyVerification(expected.pin, len(expected.files), sum(item.byte_count for item in expected.files),
                                      "sha256:" + "1" * 64)
    app.reader.verify_bodies = verify
    def current(scope):
        if calls:
            raise StaleSourceAccessScope("revoked")
    app.authorization.require_current = current
    with pytest.raises(StaleSourceAccessScope):
        app.verify_bodies("project", "one", snapshots["one"])
