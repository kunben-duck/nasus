from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json


class StaleSourceAccessScope(ValueError):
    pass


class SourceAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class SourceAccessRule:
    visibility: str = "project"
    reader_user_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.visibility not in {"project", "restricted"}:
            raise ValueError("unknown source visibility")
        if isinstance(self.reader_user_ids, str) or any(
            not isinstance(value, str) or not value.strip() for value in self.reader_user_ids
        ):
            raise ValueError("source readers must be nonempty user IDs")
        readers = tuple(sorted(set(self.reader_user_ids)))
        if len(readers) > 128 or (self.visibility == "project" and readers):
            raise ValueError("invalid source readers")
        object.__setattr__(self, "reader_user_ids", readers)

    def allows(self, actor_id: str, effective_project_role: str) -> bool:
        # Roles here must come from current project membership, never request JSON.
        if not actor_id or effective_project_role not in {
            "viewer", "tester", "qa_lead", "project_admin", "platform_admin",
        }:
            return False
        return (effective_project_role in {"project_admin", "platform_admin"}
                or self.visibility == "project" or actor_id in self.reader_user_ids)


@dataclass(frozen=True)
class SourceBindingAccess:
    binding_id: str
    source_id: str
    rule: SourceAccessRule = field(default_factory=SourceAccessRule)


@dataclass(frozen=True)
class SourceAccessScope:
    project_id: str
    actor_id: str
    effective_project_role: str
    acl_epoch: int
    binding_ids: frozenset[str]
    source_ids: frozenset[str]
    fingerprint: str
    requires_provenance: bool

    def require_binding(self, binding_id: str) -> None:
        if binding_id not in self.binding_ids:
            raise SourceAccessDenied("source is not available in the current access scope")

    def permits_sources(self, source_ids: tuple[str, ...]) -> bool:
        # Unknown/absent provenance cannot be treated as project-public evidence.
        return bool(source_ids) and set(source_ids).issubset(self.source_ids)


@dataclass(frozen=True)
class SourceAccessSnapshot:
    project_id: str
    acl_epoch: int
    bindings: tuple[SourceBindingAccess, ...]

    def __post_init__(self) -> None:
        if not self.project_id or type(self.acl_epoch) is not int or self.acl_epoch < 0:
            raise ValueError("invalid source access snapshot")
        bindings = tuple(sorted(self.bindings, key=lambda item: item.binding_id))
        if (len({item.binding_id for item in bindings}) != len(bindings)
                or len({item.source_id for item in bindings}) != len(bindings)
                or any(not item.binding_id or not item.source_id for item in bindings)):
            raise ValueError("source access bindings must have unique nonempty IDs")
        object.__setattr__(self, "bindings", bindings)

    def for_actor(self, actor_id: str, effective_project_role: str) -> SourceAccessScope:
        allowed = tuple(item for item in self.bindings if item.rule.allows(actor_id, effective_project_role))
        # Include the inventory, not just the epoch: registration can add bindings.
        payload = [self.project_id, self.acl_epoch, actor_id, effective_project_role,
                   [(item.binding_id, item.source_id, item.rule.visibility, item.rule.reader_user_ids)
                    for item in self.bindings]]
        fingerprint = "sha256:" + hashlib.sha256(json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        return SourceAccessScope(
            self.project_id, actor_id, effective_project_role, self.acl_epoch,
            frozenset(item.binding_id for item in allowed),
            frozenset(item.source_id for item in allowed), fingerprint,
            any(item.rule.visibility == "restricted" for item in self.bindings),
        )
