from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Optional

from ...domain.system_image.image_revision import (
    ImageArtifactUnavailable, ImageRevisionIntegrityError, ImageRevisionSummary, ImageRevisionPageTooLarge, verify_image_artifact,
)
from ...domain.system_image.source_access import SourceAccessDenied
from .image_revision_ports import ImageArtifactPort, ImageRevisionRepositoryPort, ImageEvidenceReadPort
from .source_access import SourceScopeAuthorizationPort
from .document_queries import DocumentQueryApplicationService
from .code_aliases import CodeObjectAliasReadPort, FrozenCodeObjectIdentity
from ...domain.system_image.code_alias import AmbiguousCodeObjectAlias
from ..operation_read_scope import OperationReadScope


@dataclass(frozen=True)
class ImageRevisionList:
    items: tuple[ImageRevisionSummary, ...]
    next_after_id: Optional[str]


@dataclass(frozen=True)
class ImageRevisionPage:
    revision: ImageRevisionSummary
    section: str
    items: tuple[dict, ...]
    total: int
    next_offset: Optional[int]


class ImageRevisionQueryApplicationService:
    def __init__(self, repository: ImageRevisionRepositoryPort, artifacts: ImageArtifactPort, authorization: SourceScopeAuthorizationPort,
                 evidence: Optional[ImageEvidenceReadPort] = None, documents: Optional[DocumentQueryApplicationService] = None,
                 code_aliases: Optional[CodeObjectAliasReadPort] = None):
        self.repository, self.artifacts, self.authorization = repository, artifacts, authorization
        self.evidence = evidence
        self.documents = documents
        self.code_aliases = code_aliases
        self._verified_reads = ContextVar("image_revision_verified_reads", default=None)
        self._verified_read_scope = ContextVar("image_revision_verified_read_scope", default=None)

    def _current_verified_reads(self):
        scope = self._verified_read_scope.get()
        return scope.value if scope is not None and scope.is_current else None

    @contextmanager
    def verified_read_session(self, *, reuse=False):
        """Reuse verified immutable inputs in one compilation, never live ACL."""
        if reuse and self._current_verified_reads() is not None:
            yield
            return
        scope = OperationReadScope({})
        token = self._verified_reads.set(scope.value)
        scope_token = self._verified_read_scope.set(scope)
        try:
            evidence_session = getattr(self.evidence, "verified_read_session", None)
            repository_session = getattr(self.repository, "verified_read_session", None)
            with repository_session() if repository_session else nullcontext():
                with evidence_session() if evidence_session else nullcontext():
                    yield
        finally:
            scope.close()
            self._verified_read_scope.reset(scope_token)
            self._verified_reads.reset(token)

    def frozen_snapshot(self, project_id, image_revision_id):
        scope = self.authorization.scope(project_id)
        result = self._verified_payload(project_id, image_revision_id, scope)
        self.authorization.require_current(scope)
        return result

    def frozen_document_members(self, project_id, image_revision_id):
        scope = self.authorization.scope(project_id)
        header, payload = self._verified_payload(project_id, image_revision_id, scope, copy_payload=False)
        members = deepcopy(tuple(item for item in payload["members"] if item["kind"] == "source_document"))
        self.authorization.require_current(scope)
        return header, members

    def frozen_source_members(self, project_id, image_revision_id):
        """Return the complete source manifest after whole-image verification."""
        scope = self.authorization.scope(project_id)
        header, payload = self._verified_payload(project_id, image_revision_id, scope, copy_payload=False)
        members = deepcopy(tuple(payload["source_members"]))
        self.authorization.require_current(scope)
        return header, members

    def resolve_code_object(self, project_id, image_revision_id, object_id, *, registration_hash=None):
        if type(object_id) is not str or not 1 <= len(object_id) <= 256:
            raise ValueError("Invalid code object identity.")
        scope = self.authorization.scope(project_id)
        header, payload = self._verified_payload(project_id, image_revision_id, scope)
        if self.code_aliases is None:
            raise ImageArtifactUnavailable("Code identity reader is unavailable.")
        candidates = self.code_aliases.find_in_image(project_id, image_revision_id, object_id,
                                                     registration_hash=registration_hash)
        members = {member["object_id"]: member for member in payload["members"]}
        objects = {obj["id"]: obj for obj in payload["objects"]}
        direct = members.get(object_id)
        # A historical object's exact membership wins over later alias reuse.
        if direct is not None:
            if direct["kind"] != "code_entity":
                raise KeyError("Object is not a registered code member.")
            candidates = tuple((alias, ident) for alias, ident in candidates if ident == object_id)
        if not candidates:
            if direct is not None:
                raise ImageRevisionIntegrityError("Frozen code identity has no audited alias registration.")
            raise KeyError("Code identity is not registered in this frozen image.")
        endpoints = set()
        for alias, ident in candidates:
            member = members.get(ident)
            reference = objects.get(ident, {}).get("code_reference")
            if (alias.project_id != project_id or object_id not in {alias.legacy_object_id, alias.canonical_object_id}
                    or not member or member["kind"] != "code_entity"
                    or any(member[key] != getattr(alias, key) for key in ("entity_id", "entity_revision_id", "source_revision_id"))
                    or not reference or any(reference[key] != getattr(alias, key) for key in
                                           ("entity_id", "entity_revision_id", "source_revision_id"))
                    or not any(source["binding_id"] == alias.binding_id and source["source_revision_id"] == alias.source_revision_id
                               for source in payload["source_members"])):
                raise ImageRevisionIntegrityError("Code alias does not match frozen source membership.")
            endpoints.add((ident, alias.entity_id, alias.entity_revision_id, alias.source_revision_id))
        if len(endpoints) != 1:
            raise AmbiguousCodeObjectAlias("Code alias has multiple members in the requested image.")
        alias, ident = candidates[0]
        result = FrozenCodeObjectIdentity(project_id, image_revision_id, header.artifact_hash, object_id,
            ident, alias.canonical_object_id, alias.entity_id, alias.entity_revision_id, alias.source_revision_id,
            alias.content_hash)
        self.authorization.require_current(scope)
        return result

    def read_document(self, project_id, image_revision_id, object_id, *, offset=0, limit=20):
        scope = self.authorization.scope(project_id)
        _, payload = self._verified_payload(project_id, image_revision_id, scope, copy_payload=False)
        member = next((item for item in payload["members"] if item["object_id"] == object_id), None)
        if not member or member["kind"] != "source_document":
            raise KeyError("Source document is not a member of this frozen image.")
        if self.documents is None:
            raise ImageArtifactUnavailable("Source document reader is unavailable.")
        result = self.documents.read(project_id, member["document_revision_id"], offset=offset, limit=limit)
        if (result["document"]["document_revision_id"] != member["document_revision_id"]
                or result["document"]["source_revision_id"] != member["source_revision_id"]):
            raise ImageRevisionIntegrityError("Source document scope mismatch.")
        parent_id = result["document"].get("parent_document_revision_id")
        if parent_id and not any(item["kind"] == "source_document" and item["document_revision_id"] == parent_id
                                 and item["source_revision_id"] == member["source_revision_id"] for item in payload["members"]):
            raise ImageRevisionIntegrityError("Source component parent is outside this frozen image.")
        # A later extractor may add evidence, but cannot extend a frozen image.
        result["evidence"] = [item for item in result["evidence"] if item["evidence_id"] in member["evidence_ids"]]
        self.authorization.require_current(scope)
        return result

    def list(self, project_id, *, after_id="", limit=20):
        if type(limit) is not int or not 1 <= limit <= 100 or len(after_id) > 64:
            raise ValueError("Invalid image revision page.")
        scope = self.authorization.scope(project_id)
        rows = self.repository.list(project_id, binding_ids=scope.binding_ids, after_id=after_id, limit=limit + 1)
        if len(rows) > limit + 1 or any(row.project_id != project_id for row in rows):
            raise ImageRevisionIntegrityError("Image revision scope mismatch.")
        result = ImageRevisionList(tuple(rows[:limit]), rows[limit - 1].image_revision_id if len(rows) > limit else None)
        self._require_page_size(result)
        self.authorization.require_current(scope)
        return result

    def read(self, project_id, image_revision_id, *, section="objects", offset=0, limit=25):
        if section not in {"objects", "relationships", "members", "source_members", "assertion_members", "semantic_assertion_members"} or type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError("Invalid image revision section or offset.")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid image revision page size.")
        scope = self.authorization.scope(project_id)
        header, payload = self._verified_payload(project_id, image_revision_id, scope, copy_payload=False)
        items = payload.get(section, [])
        if offset > len(items):
            raise ValueError("Offset is outside the frozen image.")
        end = min(offset + limit, len(items))
        result = ImageRevisionPage(header, section, deepcopy(tuple(items[offset:end])), len(items), end if end < len(items) else None)
        self._require_page_size(result)
        self.authorization.require_current(scope)
        return result

    def read_evidence(self, project_id, image_revision_id, object_id, evidence_id, *, start_line=None, max_lines=100):
        scope = self.authorization.scope(project_id)
        _, payload = self._verified_payload(project_id, image_revision_id, scope, copy_payload=False)
        return self._read_evidence_in_snapshot(project_id, payload, scope, object_id, evidence_id,
                                               start_line=start_line, max_lines=max_lines)

    def verify_evidence_selection(self, project_id, image_revision_id, selection):
        if not 1 <= len(selection) <= 512 or len(set(selection)) != len(selection):
            raise ValueError("invalid frozen evidence selection")
        scope = self.authorization.scope(project_id)
        _, payload = self._verified_payload(project_id, image_revision_id, scope, copy_payload=False)
        verify_many = getattr(self.evidence, "verify_many", None)
        if verify_many:
            members = {item["object_id"]: item for item in payload["members"]}
            bindings = {item["source_revision_id"]: item["binding_id"] for item in payload["source_members"]}
            requested = set()
            for object_id, evidence_id in selection:
                member = members.get(object_id)
                if not member or member["kind"] not in {"code_entity", "source_document"} or evidence_id not in member["evidence_ids"]:
                    raise KeyError("Evidence is not a member of this frozen object.")
                requested.add((member["source_revision_id"], evidence_id))
            self.authorization.require_current(scope)
            result = verify_many(project_id, tuple(sorted(requested)))
            if (len(result) != len(requested) or {(item.source_revision_id, item.evidence_id) for item in result} != requested
                    or any(item.binding_id != bindings[item.source_revision_id] for item in result)):
                raise ImageRevisionIntegrityError("Evidence does not match its frozen membership.")
            self.authorization.require_current(scope)
            return
        # Query-local reuse only: never cache authorized source bytes across actors.
        for object_id, evidence_id in selection:
            self._read_evidence_in_snapshot(project_id, payload, scope, object_id, evidence_id, max_lines=1)
        self.authorization.require_current(scope)

    def _read_evidence_in_snapshot(self, project_id, payload, scope, object_id, evidence_id, *, start_line=None, max_lines=100):
        member = next((item for item in payload["members"] if item["object_id"] == object_id), None)
        if not member or member["kind"] not in {"code_entity", "source_document"} or evidence_id not in member["evidence_ids"]:
            raise KeyError("Evidence is not a member of this frozen object.")
        if self.evidence is None:
            raise ImageArtifactUnavailable("Image evidence reader is unavailable.")
        self.authorization.require_current(scope)
        result = self.evidence.read(project_id, evidence_id, source_revision_id=member["source_revision_id"],
                                    start_line=start_line, max_lines=max_lines)
        binding_id = next(item["binding_id"] for item in payload["source_members"]
                          if item["source_revision_id"] == member["source_revision_id"])
        if (result.evidence.evidence_id != evidence_id or result.evidence.source_revision_id != member["source_revision_id"]
                or result.evidence.binding_id != binding_id or result.integrity != "verified"):
            raise ImageRevisionIntegrityError("Evidence does not match its frozen membership.")
        self.authorization.require_current(scope)
        return result

    def _verified_payload(self, project_id, image_revision_id, scope, *, copy_payload=True):
        try:
            header, ref, bindings = self.repository.get(project_id, image_revision_id)
        except (ImageRevisionIntegrityError, ImageArtifactUnavailable):
            # A metadata failure cannot hide a concurrent authorization change.
            self.authorization.require_current(scope)
            raise
        if header.project_id != project_id or header.image_revision_id != image_revision_id:
            raise ImageRevisionIntegrityError("Image revision scope mismatch.")
        if not bindings or not bindings.issubset(scope.binding_ids):
            raise SourceAccessDenied("Not all candidate inputs are available.")
        self.authorization.require_current(scope)
        cache = self._current_verified_reads()
        key = (project_id, image_revision_id, ref, json.dumps(asdict(header), sort_keys=True),
               scope.actor_id, scope.fingerprint, scope.acl_epoch)
        if cache is not None and key in cache:
            # The repository owns a compilation-local immutable snapshot. Every
            # call still checks live authority. Internal selectors may borrow it
            # read-only; all outward payloads or selected rows remain isolated.
            payload = deepcopy(cache[key]) if copy_payload else cache[key]
        else:
            payload = self.artifacts.read(project_id, ref, header.artifact_hash)
            verify_image_artifact(payload, header)
        if {item["binding_id"] for item in payload["source_members"]} != bindings:
            raise ImageRevisionIntegrityError("Image membership integrity mismatch.")
        self.authorization.require_current(scope)
        if cache is not None and key not in cache:
            if len(cache) >= 2:
                del cache[next(iter(cache))]
            cache[key] = deepcopy(payload)
        return header, payload

    @staticmethod
    def _require_page_size(result):
        if len(json.dumps(asdict(result), ensure_ascii=False).encode("utf-8")) > 65536:
            raise ImageRevisionPageTooLarge("Request fewer image objects; page exceeds 64 KiB.")
