from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Callable, Protocol, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.reference_links import (
    ReferenceDocument, ReferenceMention, ReferenceProposal, propose_references, requirement_references,
)
from .image_revision_queries import ImageRevisionQueryApplicationService
from .source_access import SourceScopeAuthorizationPort


PROPOSE_REFERENCES_TOOL = "system_image.links.propose_references"


class ReferenceProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class StoredReferenceProposal:
    proposal_id: str
    digest: str
    created_at: str
    proposal: ReferenceProposal
    assertion_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceProposalPage:
    proposal_id: str
    digest: str
    image_revision_id: str
    image_artifact_hash: str
    method_version: str
    status: str
    publication: str
    created_at: str
    document_count: int
    assertion_count: int
    gap_count: int
    section: str
    items: tuple[dict, ...]
    next_offset: Optional[int]


class ReferenceProposalRepositoryPort(Protocol):
    def record(self, proposal: ReferenceProposal, *, actor_id: str, invocation_id: str, created_at: str,
               require_current_scope: Callable[[], None]) -> StoredReferenceProposal: ...
    def get(self, project_id: str, proposal_id: str) -> StoredReferenceProposal: ...
    def list_for_image(self, project_id: str, image_revision_id: str, after_id: str, limit: int) -> tuple[dict, ...]: ...


class ReferenceLinkApplicationService:
    def __init__(self, images: ImageRevisionQueryApplicationService, repository: ReferenceProposalRepositoryPort,
                 authorization: SourceScopeAuthorizationPort):
        self.images, self.repository, self.authorization = images, repository, authorization

    def list_for_image(self, project_id, image_revision_id, *, after_id="", limit=20):
        if type(limit) is not int or not 1 <= limit <= 50 or not isinstance(after_id, str) or len(after_id) > 128:
            raise ValueError("invalid reference list page")
        scope = self.authorization.scope(project_id)
        self.images.frozen_document_members(project_id, image_revision_id)
        rows = self.repository.list_for_image(project_id, image_revision_id, after_id, limit + 1)
        self.authorization.require_current(scope)
        return {"image_revision_id": image_revision_id, "items": rows[:limit],
                "next_after_id": rows[limit - 1]["proposal_id"] if len(rows) > limit else None}

    def propose(self, request: ReferenceProposalInput, *, invocation_id: str, created_at: str) -> StoredReferenceProposal:
        scope = self.authorization.scope(request.project_id)
        with self.images.verified_read_session():
            proposal = self._derive(request)
        self.authorization.require_current(scope)
        stored = self.repository.record(proposal, actor_id=scope.actor_id, invocation_id=invocation_id, created_at=created_at,
                                        require_current_scope=lambda: self.authorization.require_current(scope))
        if stored.proposal != proposal or stored.digest != proposal.digest:
            raise ImageRevisionIntegrityError("reference proposal changed during persistence")
        self.authorization.require_current(scope)
        return stored

    def _derive(self, request: ReferenceProposalInput) -> ReferenceProposal:
        header, members = self.images.frozen_document_members(request.project_id, request.image_revision_id)
        if len(members) > 1000:
            raise ValueError("reference derivation exceeds 1000 document budget")
        documents = []
        for member in members:
            fields, evidence, offset = [], {}, 0
            while True:
                page = self.images.read_document(request.project_id, request.image_revision_id, member["object_id"], offset=offset, limit=90)
                fields.extend(page["fields"])
                evidence.update({item["evidence_id"]: item for item in page["evidence"]})
                if page["next_offset"] is None:
                    break
                if page["next_offset"] <= offset:
                    raise ImageRevisionIntegrityError("document cursor does not advance")
                offset = page["next_offset"]
            projection = page["projection"]
            mentions = []
            for field in fields:
                if field["name"] != "reference":
                    continue
                refs = requirement_references(field["value"])
                if not refs:
                    continue
                matched = tuple(sorted(key for key, item in evidence.items()
                    if (item["start_line"], item["end_line"], item["snippet_hash"]) ==
                    (field["start_line"], field["end_line"], field["snippet_hash"])))
                if not matched:
                    raise ImageRevisionIntegrityError("reference field has no frozen evidence")
                for ident in matched:
                    self._verify_excerpt(request, member["object_id"], ident, refs)
                mentions.extend(ReferenceMention(ref, matched) for ref in refs)
            whole = tuple(sorted(key for key, item in evidence.items()
                if (item["start_line"], item["end_line"], item["snippet_hash"]) ==
                (projection["locator"]["start_line"], projection["locator"]["end_line"], projection["snippet_hash"])))
            if projection["kind"] == "requirement" and projection["external_id"]:
                if not whole:
                    raise ImageRevisionIntegrityError("requirement has no frozen source evidence")
                for ident in whole:
                    self._verify_excerpt(request, member["object_id"], ident, (projection["external_id"],))
            documents.append(ReferenceDocument(member["object_id"], member["document_revision_id"], member["source_revision_id"],
                projection["kind"], projection["external_id"], projection["identity_status"],
                tuple(sorted(evidence)), whole, tuple(mentions)))
        return propose_references(request.project_id, request.image_revision_id, header.artifact_hash, tuple(documents))

    def _verify_excerpt(self, request, object_id, evidence_id, references):
        start, found = None, set()
        while True:
            page = self.images.read_evidence(request.project_id, request.image_revision_id, object_id, evidence_id,
                                             start_line=start, max_lines=200)
            found.update(requirement_references(page.content))
            if page.next_start_line is None:
                break
            if start is not None and page.next_start_line <= start:
                raise ImageRevisionIntegrityError("evidence cursor does not advance")
            start = page.next_start_line
        if not set(references).issubset(found):
            raise ImageRevisionIntegrityError("reference is not present in the archived evidence")

    def read(self, project_id: str, proposal_id: str, *, section="assertions", offset=0, limit=20):
        if section not in {"assertions", "gaps"} or type(offset) is not int or not 0 <= offset <= 10000 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("invalid reference proposal page")
        scope = self.authorization.scope(project_id)
        saved = self.repository.get(project_id, proposal_id)
        proposal = saved.proposal
        image, _ = self.images.frozen_document_members(project_id, proposal.image_revision_id)
        if (saved.proposal_id != proposal_id or proposal.project_id != project_id or proposal.image_artifact_hash != image.artifact_hash
                or proposal.digest != saved.digest or len(saved.assertion_ids) != len(proposal.assertions)):
            raise ImageRevisionIntegrityError("reference proposal scope or digest mismatch")
        items = getattr(proposal, section)
        if offset > len(items):
            raise ValueError("reference proposal offset out of bounds")
        end = min(offset + limit, len(items))
        result = {"proposal_id": saved.proposal_id, "digest": saved.digest, "image_revision_id": proposal.image_revision_id,
                  "image_artifact_hash": image.artifact_hash, "method_version": proposal.method_version,
                  "status": "proposed", "publication": "not_in_image_membership", "created_at": saved.created_at,
                  "document_count": proposal.document_count, "assertion_count": len(proposal.assertions), "gap_count": len(proposal.gaps),
                  "section": section, "items": [{**asdict(item), **({"assertion_id": saved.assertion_ids[i]} if section == "assertions" else {})}
                                                for i, item in enumerate(items[offset:end], start=offset)],
                  "next_offset": end if end < len(items) else None}
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 65536:
            raise ImageRevisionPageTooLarge("request fewer reference assertions")
        self.authorization.require_current(scope)
        return ReferenceProposalPage(**{**result, "items": tuple(result["items"])})
