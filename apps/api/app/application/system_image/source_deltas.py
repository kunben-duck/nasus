from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Callable, Optional, Protocol, Union

from ...domain.system_image.source_delta import (
    DELTA_KINDS, DELTA_POLICY, SourceDeltaIntegrityError, SourceDeltaPageTooLarge,
    SourceDeltaSnapshot, SourceFileDelta, SourceRenameCandidate, SourceRevisionPin,
    compare_source_snapshots,
)
from ...domain.system_image.evidence import valid_digest
from .source_access import SourceScopeAuthorizationPort


@dataclass(frozen=True)
class SourceRevisionReadTarget:
    pin: SourceRevisionPin
    source_id: str
    manifest_ref: str
    policy_version: str
    file_count: int
    byte_count: int


@dataclass(frozen=True)
class SourceBodyVerification:
    pin: SourceRevisionPin
    verified_file_count: int
    verified_byte_count: int
    verification_hash: str
    method: str = "nasus.source-body-verification.v1"

    def __post_init__(self):
        if (not isinstance(self.pin, SourceRevisionPin) or type(self.verified_file_count) is not int
                or not 1 <= self.verified_file_count <= 50000 or type(self.verified_byte_count) is not int
                or self.verified_byte_count < 0 or not valid_digest(self.verification_hash)
                or self.method != "nasus.source-body-verification.v1"):
            raise SourceDeltaIntegrityError("invalid complete source body verification")


class SourceDeltaRepositoryPort(Protocol):
    def get_pair(self, project_id: str, before_id: str, after_id: str, *,
                 binding_ids: frozenset[str]) -> tuple[SourceRevisionReadTarget, SourceRevisionReadTarget]: ...


class SourceDeltaArchivePort(Protocol):
    def read(self, target: SourceRevisionReadTarget) -> SourceDeltaSnapshot: ...
    def verify_bodies(self, target: SourceRevisionReadTarget, expected: SourceDeltaSnapshot, *,
                      require_current: Callable[[], None]) -> SourceBodyVerification: ...


@dataclass(frozen=True)
class SourceDeltaPage:
    before: SourceRevisionPin
    after: SourceRevisionPin
    content_hash: str
    counts: dict[str, int]
    gaps: tuple[str, ...]
    complete: bool
    full_validation_required: bool
    full_validation_reasons: tuple[str, ...]
    ambiguous_rename_groups: int
    rename_candidate_count: int
    section: str
    kind: Optional[str]
    items: tuple[Union[SourceFileDelta, SourceRenameCandidate], ...]
    total: int
    next_offset: Optional[int]
    schema_version: str = DELTA_POLICY
    integrity: str = "verified_manifests"
    file_bodies_verified: bool = False
    impact_complete: bool = False
    publication_authorized: bool = False


class SourceDeltaQueryApplicationService:
    def __init__(self, repository: SourceDeltaRepositoryPort, reader: SourceDeltaArchivePort,
                 authorization: SourceScopeAuthorizationPort):
        self.repository, self.reader, self.authorization = repository, reader, authorization

    def _snapshot_target(self, project_id, revision_id):
        if type(revision_id) is not str or not 1 <= len(revision_id) <= 128:
            raise ValueError("invalid fixed source revision")
        scope = self.authorization.scope(project_id)
        targets = self.repository.get_pair(project_id, revision_id, revision_id, binding_ids=scope.binding_ids)
        if len(targets) != 2 or targets[0] != targets[1]:
            raise SourceDeltaIntegrityError("one revision must identify one immutable read target")
        target = targets[0]
        if (target.pin.project_id, target.pin.source_revision_id) != (project_id, revision_id) or target.source_id not in scope.source_ids:
            raise SourceDeltaIntegrityError("fixed source inventory scope mismatch")
        scope.require_binding(target.pin.binding_id)
        self.authorization.require_current(scope)
        return scope, target

    def snapshot(self, project_id, revision_id):
        scope, target = self._snapshot_target(project_id, revision_id)
        result = self.reader.read(target)
        if result.pin != target.pin:
            raise SourceDeltaIntegrityError("fixed source inventory pin mismatch")
        self.authorization.require_current(scope)
        return result

    def verify_bodies(self, project_id, revision_id, expected):
        scope, target = self._snapshot_target(project_id, revision_id)
        if expected.pin != target.pin:
            raise SourceDeltaIntegrityError("body verification requires the exact immutable source pin")
        result = self.reader.verify_bodies(target, expected,
            require_current=lambda: self.authorization.require_current(scope))
        if (result.pin != target.pin or result.verified_file_count != len(expected.files)
                or result.verified_byte_count != sum(item.byte_count for item in expected.files)):
            raise SourceDeltaIntegrityError("source body verification omitted fixed files or bytes")
        self.authorization.require_current(scope)
        return result

    def read(self, project_id: str, before_id: str, after_id: str, *, section: str = "files",
             kind: str | None = None, offset: int = 0, limit: int = 50) -> SourceDeltaPage:
        if (any(not isinstance(value, str) or not value or len(value) > 128 for value in (before_id, after_id))
                or section not in {"files", "rename_candidates"}
                or kind is not None and (section != "files" or kind not in DELTA_KINDS)
                or type(offset) is not int or not 0 <= offset <= 100000
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError("invalid source delta page")
        scope = self.authorization.scope(project_id)
        delta = self.compare(project_id, before_id, after_id)
        self.authorization.require_current(scope)
        scope.require_binding(delta.before.binding_id)
        items = delta.items if section == "files" else delta.rename_candidates
        if kind is not None:
            items = tuple(item for item in items if item.kind == kind)
        if offset > len(items):
            raise ValueError("offset is outside the fixed source delta")
        end = min(offset + limit, len(items))
        result = SourceDeltaPage(delta.before, delta.after, delta.content_hash, delta.counts, delta.gaps,
            delta.complete, delta.full_validation_required, delta.full_validation_reasons,
            delta.ambiguous_rename_groups, len(delta.rename_candidates), section, kind,
            tuple(items[offset:end]), len(items), end if end < len(items) else None)
        if len(json.dumps(asdict(result), ensure_ascii=False).encode("utf-8")) > 65536:
            self.authorization.require_current(scope)
            raise SourceDeltaPageTooLarge("source delta page exceeds 64 KiB")
        self.authorization.require_current(scope)
        return result

    def compare(self, project_id, before_id, after_id):
        if any(type(value) is not str or not value or len(value) > 128 for value in (before_id, after_id)):
            raise ValueError("invalid source revision pin")
        scope = self.authorization.scope(project_id)
        targets = self.repository.get_pair(project_id, before_id, after_id, binding_ids=scope.binding_ids)
        self.authorization.require_current(scope)
        if len(targets) != 2:
            raise SourceDeltaIntegrityError("source delta requires both complete read targets")
        if (targets[0].pin.binding_id, targets[0].pin.source_type) != (
                targets[1].pin.binding_id, targets[1].pin.source_type):
            raise ValueError("source delta requires revisions of the same binding")
        snapshots = []
        for target, revision_id in zip(targets, (before_id, after_id)):
            if (target.pin.project_id != project_id or target.pin.source_revision_id != revision_id
                    or target.source_id not in scope.source_ids):
                raise SourceDeltaIntegrityError("source delta revision scope mismatch")
            scope.require_binding(target.pin.binding_id)
            self.authorization.require_current(scope)
            snapshot = self.reader.read(target)
            if snapshot.pin != target.pin:
                raise SourceDeltaIntegrityError("archive returned a different source revision")
            snapshots.append(snapshot)
        delta = compare_source_snapshots(*snapshots)
        self.authorization.require_current(scope)
        return delta
