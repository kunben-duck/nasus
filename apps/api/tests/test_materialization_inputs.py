from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.materialization_inputs import MaterializationInputApplicationService
from apps.api.app.domain.system_image.source_access import SourceAccessSnapshot, SourceBindingAccess, StaleSourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest
from apps.api.app.domain.system_image.materialization_command import (
    MaterializationCommandInput, MaterializationCommandConflict, MaterializationOriginalInputUnavailable,
)
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError


def inputs():
    members = (SourceManifestMember("code", "code", "code-revision", "captured"),
               SourceManifestMember("us", "us_doc", None, "failed"))
    manifest = CapturedSourceManifest("manifest", "project", snapshot_digest([
        {"binding_id": item.binding_id, "source_type": item.source_type,
         "source_revision_id": item.source_revision_id, "status": item.status} for item in members]), "now", members)
    access = SourceAccessSnapshot("project", 1, (
        SourceBindingAccess("code", "raw-code"), SourceBindingAccess("us", "raw-us"))).for_actor("owner", "project_admin")
    snapshots = SimpleNamespace(latest_manifest=lambda project_id: manifest,
        is_current_materialization_input=lambda selected: selected == manifest)
    checks = []
    authorization = SimpleNamespace(require_all_sources_access=lambda project_id: access,
        require_current=lambda scope: checks.append(scope))
    return MaterializationInputApplicationService(snapshots, authorization), manifest, access, checks


def test_fixed_admission_accepts_optional_gap_and_rechecks_permissions():
    service, manifest, access, checks = inputs()
    admitted = service.admit("project")
    assert admitted.manifest == manifest and admitted.access == access
    service.require_current(admitted)
    assert len(checks) >= 3 and all(scope == access for scope in checks)


def test_missing_binding_requires_registration_without_reading_manifest():
    service, *_ = inputs()
    empty = SourceAccessSnapshot("project", 1, ()).for_actor("owner", "project_admin")
    service.authorization.require_all_sources_access = lambda _: empty
    def forbidden_read(_):
        pytest.fail("Missing source bindings must be rejected before reading a manifest")
    service.snapshots.latest_manifest = forbidden_read
    with pytest.raises(PlatformApplicationError) as failed:
        service.admit("project")
    assert failed.value.code == "missing_source_binding" and failed.value.status_code == 409


@pytest.mark.parametrize("dependency", ["snapshots", "authorization"])
def test_missing_dependency_fails_closed(dependency):
    service, *_ = inputs()
    setattr(service, dependency, None)
    with pytest.raises(PlatformApplicationError) as failed:
        service.admit("project")
    assert failed.value.status_code == 503


@pytest.mark.parametrize("fault,code", [
    ("absent", "materialization_source_manifest_required"),
    ("project", "materialization_sources_changed"),
    ("uncaptured_code", "materialization_source_capture_required"),
    ("hash", "materialization_source_integrity_failed"),
    ("new_binding", "materialization_sources_changed"),
])
def test_bad_original_inputs_are_not_repaired(fault, code):
    service, manifest, *_ = inputs()
    corrupted = (None if fault == "absent" else replace(manifest, project_id="other") if fault == "project" else
        replace(manifest, members=(replace(manifest.members[0], status="legacy_unverified", source_revision_id=None),
                                  manifest.members[1])) if fault == "uncaptured_code" else
        replace(manifest, content_hash="sha256:" + "0" * 64) if fault == "hash" else manifest)
    service.snapshots.latest_manifest = lambda _: corrupted
    if fault == "new_binding":
        service.snapshots.is_current_materialization_input = lambda _: False
    with pytest.raises(PlatformApplicationError) as failed:
        service.admit("project")
    assert failed.value.code == code and failed.value.status_code == 409


def test_revocation_during_processing_is_not_a_source_gap():
    service, *_ = inputs()
    admitted = service.admit("project")
    def revoked(_):
        raise StaleSourceAccessScope("credentials/private-path must not appear in public errors")
    service.authorization.require_current = revoked
    with pytest.raises(PlatformApplicationError) as failed:
        service.require_current(admitted)
    assert failed.value.code == "source_access_denied" and failed.value.status_code == 403
    assert "credentials" not in failed.value.message


def command(manifest):
    return MaterializationCommandInput("command", "project", "owner", snapshot_digest({"tool": "materialize"}),
        manifest.manifest_id, manifest.content_hash)


def test_canonical_input_admission_pins_manifest_and_rechecks_the_durable_command():
    service, manifest, *_ = inputs()
    original, operations = command(manifest), []
    service.commands = SimpleNamespace(get=lambda *args: None,
        admit=lambda *args: operations.append("admit") or original,
        require_current=lambda *args: operations.append("recheck"))
    admitted = service.admit("project", invocation_id="command")
    assert admitted.command == original and operations == ["admit", "recheck"]
    service.require_current(admitted)
    assert operations == ["admit", "recheck", "recheck"]


def test_original_command_selection_is_loaded_before_checking_the_current_head():
    service, manifest, *_ = inputs()
    original, reads = command(manifest), []
    service.commands = SimpleNamespace(get=lambda *args: original, require_current=lambda *args: None,
        admit=lambda *args: pytest.fail("A conflicting original selection must not be replaced"))
    service.snapshots.get_manifest = lambda project, ident: reads.append(ident) or manifest
    service.snapshots.is_current_materialization_input = lambda selected: False
    with pytest.raises(PlatformApplicationError) as failed:
        service.admit("project", invocation_id="command")
    assert failed.value.code == "materialization_sources_changed" and reads == [manifest.manifest_id]


@pytest.mark.parametrize("fault,code,status", [
    (MaterializationOriginalInputUnavailable("private"), "materialization_original_input_required", 409),
    (MaterializationCommandConflict("private"), "materialization_sources_changed", 409),
    (ValueError("private"), "materialization_input_integrity_failed", 409),
    (OSError("private"), "materialization_inputs_unavailable", 503),
])
def test_command_history_failures_are_safe_and_do_not_fall_back_to_latest(fault, code, status):
    service, *_ = inputs()
    def failed(*args):
        raise fault
    service.commands = SimpleNamespace(get=failed)
    service.snapshots.latest_manifest = lambda _: pytest.fail("Invalid command history must not read latest inputs")
    with pytest.raises(PlatformApplicationError) as error:
        service.admit("project", invocation_id="command")
    assert (error.value.code, error.value.status_code) == (code, status)
    assert "private" not in error.value.message


def test_production_admission_requires_an_original_canonical_command():
    service, *_ = inputs()
    service.commands = SimpleNamespace()
    with pytest.raises(PlatformApplicationError) as error:
        service.admit("project")
    assert error.value.code == "materialization_canonical_command_required"


@pytest.mark.parametrize("field,value", [
    ("invocation_id", ""), ("project_id", " project"), ("actor_id", "actor\n"),
    ("manifest_id", "\x7f"), ("manifest_hash", "sha256:" + "x" * 64), ("command_hash", "not-a-hash"),
])
def test_materialization_command_pins_reject_invalid_identity_and_digest(field, value):
    _, manifest, *_ = inputs()
    with pytest.raises((ValueError, ImageRevisionIntegrityError)):
        replace(command(manifest), **{field: value})


def test_materialization_command_cannot_be_rebound_to_another_source_revision():
    _, manifest, *_ = inputs()
    original = command(manifest)
    assert original.content_hash == command(manifest).content_hash
    with pytest.raises(MaterializationCommandConflict):
        original.require_same(replace(original, manifest_id="new-manifest"))
