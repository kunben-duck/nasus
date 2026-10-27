from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.source_delta import (
    SourceDeltaIntegrityError, SourceDeltaSnapshot, SourceRevisionPin, compare_source_snapshots,
)
from apps.api.app.domain.system_image.source_inventory import SourceInventory, SourceInventoryEntry
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def snapshot(revision, files, *, legacy=False, excluded=(), extra=(), complete=True):
    entries = tuple(SourceInventoryEntry(path, "file", "included", "captured", len(body), snapshot_digest(body))
                    for path, body in sorted(files.items()))
    inventory = SourceInventory(tuple(sorted((SourceInventoryEntry(".", "directory", "enumerated", "scanned"),
                                              *entries, *extra), key=lambda item: item.path)), excluded, complete)
    pin = SourceRevisionPin("project", "binding", revision, "code", revision,
                            snapshot_digest(inventory.to_payload()), snapshot_digest(files))
    return SourceDeltaSnapshot(pin, entries, excluded, None if legacy else inventory)


def test_complete_fixed_delta_preserves_counts_hashes_and_unapproved_rename_candidate():
    before = snapshot("one", {"gone.py": "gone", "old.py": "rename", "stay.py": "same", "edit.py": "old"})
    after = snapshot("two", {"new.py": "rename", "stay.py": "same", "edit.py": "new", "added.py": "add"})
    delta = compare_source_snapshots(before, after)
    assert delta.counts == {"added": 2, "deleted": 2, "modified": 1, "unchanged": 1, "unresolved": 0}
    assert delta.complete and delta.full_validation_required
    assert [(item.before_path, item.after_path, item.identity_preserved) for item in delta.rename_candidates] == [
        ("old.py", "new.py", False)]
    assert not delta.impact_complete and not delta.publication_authorized and not delta.file_bodies_verified
    assert compare_source_snapshots(before, after).content_hash == delta.content_hash
    assert before.files[0].path == "edit.py"  # Neither immutable input is rewritten.
    assert compare_source_snapshots(after, before).content_hash != delta.content_hash


@pytest.mark.parametrize("side", ["before", "after", "both"])
def test_legacy_manifests_do_not_prove_missing_files(side):
    before = snapshot("one", {"stay.py": "old", "gone.py": "gone"}, legacy=side in {"before", "both"})
    after = snapshot("two", {"stay.py": "new", "added.py": "add"}, legacy=side in {"after", "both"})
    result = compare_source_snapshots(before, after)
    by_path = {item.path: item.kind for item in result.items}
    assert by_path["stay.py"] == "modified"
    assert by_path["added.py"] == ("unresolved" if side in {"before", "both"} else "added")
    assert by_path["gone.py"] == ("unresolved" if side in {"after", "both"} else "deleted")
    assert not result.complete and result.full_validation_required


def test_changed_capture_policy_never_treats_omissions_as_deletions_or_additions():
    result = compare_source_snapshots(snapshot("one", {"old/a.py": "a", "stay.py": "same"}),
        snapshot("two", {"new/a.py": "a", "stay.py": "same"}, excluded=("old",)))
    assert result.counts["unresolved"] == 2 and result.counts["unchanged"] == 1
    assert "capture_scope_changed" in result.gaps and not result.rename_candidates


@pytest.mark.parametrize("entry", [
    SourceInventoryEntry("old", "directory", "excluded", "policy_exclusion"),
    SourceInventoryEntry("old/a.py", "file", "excluded", "policy_exclusion"),
    SourceInventoryEntry("old", "directory", "failed", "permission_denied"),
    SourceInventoryEntry("old", "symlink", "unsupported", "symbolic_link"),
])
def test_excluded_unreadable_or_unsupported_paths_are_not_deletions(entry):
    before = snapshot("one", {"old/a.py": "a", "stay.py": "same"})
    after = snapshot("two", {"stay.py": "same"}, extra=(entry,), complete=entry.status != "failed")
    result = compare_source_snapshots(before, after)
    assert result.counts["deleted"] == 0 and result.counts["unresolved"] == 1
    assert not result.complete and result.full_validation_required


def test_duplicate_content_never_creates_a_unique_rename_or_identity_merge():
    result = compare_source_snapshots(snapshot("one", {"old.py": "same", "stay.py": "same"}),
        snapshot("two", {"new.py": "same", "stay.py": "same"}))
    assert not result.rename_candidates and result.ambiguous_rename_groups == 1
    assert result.counts["added"] == result.counts["deleted"] == 1


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("binding_id", "other"), ("source_type", "us_doc")])
def test_revisions_from_different_projects_or_bindings_are_not_compared(field, value):
    before, after = snapshot("one", {"a.py": "a"}), snapshot("two", {"a.py": "b"})
    after = replace(after, pin=replace(after.pin, **{field: value}))
    with pytest.raises(ValueError, match="same binding"):
        compare_source_snapshots(before, after)


def test_same_revision_and_digest_cannot_identify_conflicting_metadata():
    before = snapshot("one", {"a.py": "a"})
    with pytest.raises(SourceDeltaIntegrityError, match="one source revision"):
        compare_source_snapshots(before, replace(before, pin=replace(before.pin, external_revision="other")))
    file = replace(before.files[0], byte_count=200)
    after = replace(snapshot("two", {"a.py": "a"}), files=(file,), inventory=None)
    with pytest.raises(SourceDeltaIntegrityError, match="different file sizes"):
        compare_source_snapshots(before, after)


def test_every_path_and_full_digest_participate_even_after_the_first_page():
    files = {f"src/{index:05}.py": str(index) for index in range(1200)}
    before = snapshot("one", files)
    after = snapshot("two", {**files, "src/01199.py": "last changed"})
    result = compare_source_snapshots(before, after)
    assert len(result.items) == 1200 and result.items[-1].kind == "modified"
    assert result.counts["modified"] == 1 and not result.full_validation_required
    assert result.content_hash != compare_source_snapshots(before, snapshot("two", files)).content_hash
    same = compare_source_snapshots(before, before)
    assert same.complete and same.counts["unchanged"] == 1200


def test_single_file_capture_never_proves_absence_outside_its_scope():
    before = snapshot("one", {"one.py": "same"})
    before = replace(before, inventory=replace(before.inventory, entries=before.files))
    after = snapshot("two", {"one.py": "same", "two.py": "added"})
    forward = compare_source_snapshots(before, after)
    reverse = compare_source_snapshots(after, before)
    assert forward.counts["added"] == reverse.counts["deleted"] == 0
    assert forward.counts["unresolved"] == reverse.counts["unresolved"] == 1
    assert not forward.complete and forward.full_validation_required
