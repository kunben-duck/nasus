from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Literal

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.semantic_applicability import SemanticEndpointIdentity
from .link_candidates import LinkCandidate, LinkCandidatePage, LinkCandidateQueryApplicationService
from .semantic_screening import SemanticScreeningItem


SCREENED_RECALL_METHOD = "nasus.link-recall.reviewed.v2"
SCREENED_RECALL_TOOL = "query.system_image.links.screened_candidates"
BLOCKED_STATUSES = frozenset({"rejected_same_revisions", "identity_unresolved", "different_endpoints"})


@dataclass(frozen=True)
class ScreenedLinkCandidate(LinkCandidate):
    review_status: Literal["unreviewed", "requires_revalidation", "reviewed_not_approved"] = "unreviewed"


@dataclass(frozen=True)
class ScreenedLinkCandidatePage(LinkCandidatePage):
    items: tuple[ScreenedLinkCandidate, ...]
    method_version: Literal["nasus.link-recall.reviewed.v2"] = SCREENED_RECALL_METHOD
    requested_limit: int = 30
    pre_review_matched_count: int = 0
    review_scope_digest: str = ""
    review_screening: tuple[SemanticScreeningItem, ...] = ()
    review_scope: Literal["pinned_query_heads_not_live"] = "pinned_query_heads_not_live"


class ScreenedLinkCandidateQueryApplicationService:
    def __init__(self, images, screening):
        self.images, self.screening = images, screening
        self.recall = LinkCandidateQueryApplicationService(images)

    @staticmethod
    def _identity(corpus, member, bindings):
        object_id = member["object_id"]
        if len(bindings) != 1:
            raise ImageRevisionIntegrityError("screened recall source binding is ambiguous")
        binding = next(iter(bindings))
        if member["kind"] == "code_entity":
            return SemanticEndpointIdentity(object_id, binding, member["entity_id"], member["entity_revision_id"],
                member["source_revision_id"], "code_entity", "registered_symbol")
        doc = corpus.documents[object_id]
        if (doc["document"]["binding_id"] != binding or doc["document"]["document_revision_id"] != member["document_revision_id"]
                or doc["document"]["source_revision_id"] != member["source_revision_id"]):
            raise ImageRevisionIntegrityError("screened recall document identity mismatch")
        return SemanticEndpointIdentity(object_id, binding, doc["document"]["entity_id"], member["document_revision_id"],
            member["source_revision_id"], doc["projection"]["kind"], doc["projection"]["identity_status"])

    def read(self, project_id, image_revision_id, target_object_id, *, relation, limit=30,
             method_version=SCREENED_RECALL_METHOD, pinned_heads=None):
        if method_version != SCREENED_RECALL_METHOD or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid screened recall request")
        corpus = self.recall.collect(project_id, image_revision_id, target_object_id, relation=relation)
        return self.screen_corpus(corpus, limit=limit, pinned_heads=pinned_heads)

    def screen_corpus(self, corpus, *, limit, pinned_heads=None):
        """Screen the full supplied ranking before truncation, regardless of recall adapter."""
        project_id, image_revision_id, target_object_id = corpus.project_id, corpus.image_revision_id, corpus.target.object_id
        relation = corpus.relation
        members = {item["object_id"]: item for item in corpus.payload["members"]}
        bindings = {}
        for source in corpus.payload["source_members"]:
            bindings.setdefault(source["source_revision_id"], set()).add(source["binding_id"])
        def identity(object_id):
            member = members[object_id]
            return self._identity(corpus, member, bindings.get(member["source_revision_id"], set()))
        subjects = tuple(identity(item.object_id) for item in corpus.ranked)
        snapshot = self.screening.screen_endpoints(project_id, image_revision_id, corpus.image_artifact_hash, relation,
            subjects, identity(target_object_id), pinned_heads=pinned_heads)
        blocked, statuses = set(), {}
        for item in snapshot.items:
            if item.status in BLOCKED_STATUSES:
                blocked.add(item.subject_object_id)
            elif item.status == "stale_requires_review":
                statuses[item.subject_object_id] = "requires_revalidation"
            else:
                statuses.setdefault(item.subject_object_id, "reviewed_not_approved")
        ranked = tuple(item for item in corpus.ranked if item.object_id not in blocked)
        page = self.recall.page(corpus, limit=limit, ranked=ranked)
        values = {key: value for key, value in asdict(page).items() if key not in {"items", "target", "method_version"}}
        items = tuple(ScreenedLinkCandidate(item.endpoint, item.retrieval_score, item.matched_terms, item.signals,
            review_status=statuses.get(item.endpoint.object_id, "unreviewed")) for item in page.items)
        values["excluded"] = {**page.excluded, "historical_review": len(blocked)}
        result = ScreenedLinkCandidatePage(**values, target=page.target, items=items, requested_limit=limit,
            pre_review_matched_count=len(corpus.ranked), review_scope_digest=snapshot.digest, review_screening=snapshot.items)
        if len(json.dumps(asdict(result), ensure_ascii=False).encode("utf-8")) > 65536:
            raise ImageRevisionPageTooLarge("screened recall response exceeds 64 KiB")
        if pinned_heads is None:
            self.screening.require_current(snapshot)
        self.images.authorization.require_current(corpus.scope)
        return result
