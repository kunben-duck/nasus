"""Pinned acquisition deltas, never entity lineage or verified test coverage."""
from __future__ import annotations

from collections import defaultdict
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Optional

from .evidence import valid_digest
from .source_inventory import SourceInventory, SourceInventoryEntry
from .source_snapshots import snapshot_digest


DELTA_POLICY = "nasus.source-delta.v1"
DELTA_KINDS = frozenset({"added", "modified", "deleted", "unchanged", "unresolved"})


class SourceDeltaIntegrityError(ValueError):
    pass


class SourceDeltaUnavailable(RuntimeError):
    pass


class SourceDeltaPageTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class SourceRevisionPin:
    project_id: str
    binding_id: str
    source_revision_id: str
    source_type: str
    external_revision: str
    manifest_hash: str
    content_hash: str

    def __post_init__(self):
        if (any(not isinstance(value, str) or not value or len(value) > 512 for value in
                (self.project_id, self.binding_id, self.source_revision_id, self.external_revision))
                or self.source_type not in {"code", "us_doc", "test_asset"}
                or not isinstance(self.manifest_hash, str) or not valid_digest(self.manifest_hash)
                or not isinstance(self.content_hash, str) or not valid_digest(self.content_hash)):
            raise SourceDeltaIntegrityError("invalid source revision pin")


@dataclass(frozen=True)
class SourceDeltaSnapshot:
    pin: SourceRevisionPin
    files: tuple[SourceInventoryEntry, ...]
    excluded_names: tuple[str, ...]
    inventory: Optional[SourceInventory]

    def __post_init__(self):
        if (not isinstance(self.files, tuple) or not 1 <= len(self.files) <= 50000
                or any(not isinstance(item, SourceInventoryEntry) or item.status != "included" for item in self.files)
                or [item.path for item in self.files] != sorted({item.path for item in self.files})
                or not isinstance(self.excluded_names, tuple)
                or any(not isinstance(name, str) or not name or name in {".", ".."}
                       or "/" in name or "\\" in name for name in self.excluded_names)
                or tuple(sorted(set(self.excluded_names))) != self.excluded_names):
            raise SourceDeltaIntegrityError("invalid pinned file inventory")
        if self.inventory is not None and (not isinstance(self.inventory, SourceInventory)
                or self.inventory.excluded_names != self.excluded_names or
                tuple(item for item in self.inventory.entries if item.status == "included") != self.files):
            raise SourceDeltaIntegrityError("capture inventory does not match archived files")


@dataclass(frozen=True)
class SourceFileDelta:
    path: str
    kind: str
    before_hash: Optional[str]
    after_hash: Optional[str]
    before_bytes: Optional[int]
    after_bytes: Optional[int]
    reason: str


@dataclass(frozen=True)
class SourceRenameCandidate:
    before_path: str
    after_path: str
    content_hash: str
    identity_preserved: bool = False


@dataclass(frozen=True)
class SourceDelta:
    before: SourceRevisionPin
    after: SourceRevisionPin
    items: tuple[SourceFileDelta, ...]
    rename_candidates: tuple[SourceRenameCandidate, ...]
    counts: dict[str, int]
    gaps: tuple[str, ...]
    complete: bool
    full_validation_required: bool
    full_validation_reasons: tuple[str, ...]
    ambiguous_rename_groups: int
    content_hash: str
    schema_version: str = DELTA_POLICY
    file_bodies_verified: bool = False
    impact_complete: bool = False
    publication_authorized: bool = False


def _absence_proof(snapshot):
    inventory = snapshot.inventory
    # A complete single-file capture cannot prove absence elsewhere in a tree.
    return (inventory is not None and inventory.complete and any(
                entry.path == "." and entry.status == "enumerated" for entry in inventory.entries),
            frozenset(entry.path for entry in inventory.entries if entry.status != "enumerated")
            if inventory else frozenset())


def _absence_known(proof, path, comparable_scope):
    complete, barriers = proof
    if not comparable_scope or not complete:
        return False
    # Explicit exclusions and unreadable ancestor directories are not deletions.
    parts = PurePosixPath(path).parts
    return "." not in barriers and not any("/".join(parts[:end]) in barriers
                                           for end in range(1, len(parts) + 1))


def compare_source_snapshots(before: SourceDeltaSnapshot, after: SourceDeltaSnapshot) -> SourceDelta:
    if (before.pin.project_id, before.pin.binding_id, before.pin.source_type) != (
            after.pin.project_id, after.pin.binding_id, after.pin.source_type):
        raise ValueError("source delta requires revisions of the same binding")
    if before.pin.source_revision_id == after.pin.source_revision_id and before != after:
        raise SourceDeltaIntegrityError("one source revision cannot identify different inventories")
    sizes = {}
    for entry in (*before.files, *after.files):
        if entry.content_hash in sizes and sizes[entry.content_hash] != entry.byte_count:
            raise SourceDeltaIntegrityError("one content digest cannot identify different file sizes")
        sizes[entry.content_hash] = entry.byte_count
    left, right = ({item.path: item for item in snapshot.files} for snapshot in (before, after))
    comparable = before.excluded_names == after.excluded_names
    before_proof, after_proof = _absence_proof(before), _absence_proof(after)
    items = []
    for path in sorted(left.keys() | right.keys()):
        old, new = left.get(path), right.get(path)
        if old and new:
            kind = "unchanged" if old.content_hash == new.content_hash else "modified"
            reason = "matching_archived_hash" if kind == "unchanged" else "archived_hash_changed"
        elif new:
            kind = "added" if _absence_known(before_proof, path, comparable) else "unresolved"
            reason = "absent_in_complete_before_scope" if kind == "added" else "before_absence_unproven"
        else:
            kind = "deleted" if _absence_known(after_proof, path, comparable) else "unresolved"
            reason = "absent_in_complete_after_scope" if kind == "deleted" else "after_absence_unproven"
        items.append(SourceFileDelta(path, kind, old.content_hash if old else None,
            new.content_hash if new else None, old.byte_count if old else None,
            new.byte_count if new else None, reason))
    counts = {kind: sum(item.kind == kind for item in items) for kind in sorted(DELTA_KINDS)}
    removed, added = defaultdict(list), defaultdict(list)
    for item in items:
        if item.kind == "deleted":
            removed[item.before_hash].append(item.path)
        elif item.kind == "added":
            added[item.after_hash].append(item.path)
    renames, ambiguous = [], 0
    left_hashes, right_hashes = (Counter(item.content_hash for item in snapshot.files)
                               for snapshot in (before, after))
    for digest in sorted(removed.keys() & added.keys()):
        if len(removed[digest]) == len(added[digest]) == left_hashes[digest] == right_hashes[digest] == 1:
            renames.append(SourceRenameCandidate(removed[digest][0], added[digest][0], digest))
        else:
            ambiguous += 1
    gaps = []
    for name, snapshot in (("before", before), ("after", after)):
        if snapshot.inventory is None or not snapshot.inventory.complete:
            gaps.append(f"{name}_inventory_unverified")
    if not comparable:
        gaps.append("capture_scope_changed")
    if counts["unresolved"]:
        gaps.append("unresolved_file_presence")
    reasons = list(gaps)
    if (len(items) - counts["unchanged"]) / len(items) > 0.2:
        reasons.append("changed_file_ratio_exceeds_20_percent")
    value = dict(before=asdict(before.pin), after=asdict(after.pin),
        items=[asdict(item) for item in items], rename_candidates=[asdict(item) for item in renames],
        counts=counts, gaps=gaps, complete=not gaps, full_validation_required=bool(reasons),
        full_validation_reasons=reasons, ambiguous_rename_groups=ambiguous,
        schema_version=DELTA_POLICY, file_bodies_verified=False, impact_complete=False,
        publication_authorized=False)
    return SourceDelta(before.pin, after.pin, tuple(items), tuple(renames), counts, tuple(gaps),
        not gaps, bool(reasons), tuple(reasons), ambiguous, snapshot_digest(value))
