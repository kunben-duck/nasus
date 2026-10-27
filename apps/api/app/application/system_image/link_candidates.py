from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Optional

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.link_recall import LINK_RECALL_METHOD, LinkRecallInput, rank_link_candidates
from ...domain.system_image.reference_links import requirement_references
from .image_revision_queries import ImageRevisionQueryApplicationService


@dataclass(frozen=True)
class LinkCandidateEndpoint:
    object_id: str
    revision_id: str
    source_revision_id: str
    kind: str
    title: str
    content_hash: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LinkCandidate:
    endpoint: LinkCandidateEndpoint
    retrieval_score: float
    matched_terms: tuple[str, ...]
    signals: tuple[str, ...]
    calibrated_probability: Optional[float] = None
    status: str = "retrieved_not_asserted"


@dataclass(frozen=True)
class LinkCandidatePage:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    target: LinkCandidateEndpoint
    relation: str
    items: tuple[LinkCandidate, ...]
    eligible_count: int
    matched_count: int
    excluded: dict[str, int]
    truncated: bool
    method_version: str = LINK_RECALL_METHOD
    authority_status: str = "pending_confirmation"
    semantic_status: str = "retrieval_only_not_implementation_or_coverage"
    limitations: tuple[str, ...] = ("vector_recall_not_run", "structural_recall_not_run", "semantic_judgment_required",
                                    "source_specification_not_approved", "no_runtime_evidence")


@dataclass(frozen=True)
class LinkRecallCorpus:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    target: LinkCandidateEndpoint
    relation: str
    endpoints: dict
    ranked: tuple
    eligible_count: int
    excluded: dict
    payload: dict
    documents: dict
    scope: object


class LinkCandidateQueryApplicationService:
    """Recall inside one immutable image; do not create assertions or infer oracles."""

    def __init__(self, images: ImageRevisionQueryApplicationService):
        self.images = images

    def read(self, project_id, image_revision_id, target_object_id, *, relation, limit=30,
             method_version=LINK_RECALL_METHOD) -> LinkCandidatePage:
        if method_version != LINK_RECALL_METHOD or relation not in {"implements", "asserts"} or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid link candidate request")
        with self.images.verified_read_session(reuse=True):
            corpus = self._collect(project_id, image_revision_id, target_object_id, relation=relation)
            return self.page(corpus, limit=limit)

    def collect(self, project_id, image_revision_id, target_object_id, *, relation):
        if relation not in {"implements", "asserts"}:
            raise ValueError("invalid link candidate relation")
        with self.images.verified_read_session(reuse=True):
            return self._collect(project_id, image_revision_id, target_object_id, relation=relation)

    def _collect(self, project_id, image_revision_id, target_object_id, *, relation):
        scope = self.images.authorization.scope(project_id)
        header, payload = self.images.frozen_snapshot(project_id, image_revision_id)
        members = {item["object_id"]: item for item in payload["members"]}
        objects = {item["id"]: item for item in payload["objects"]}
        target_member = members.get(target_object_id)
        if not target_member or target_member["kind"] != "source_document":
            raise KeyError("link target is not a frozen source document")
        if sum(item["kind"] == "source_document" for item in members.values()) > 1000 or header.code_member_count > 10000:
            raise ImageRevisionPageTooLarge("link recall corpus exceeds the bounded query budget")
        documents, read_bytes = {}, 0

        def document(member):
            nonlocal read_bytes
            ident = member["object_id"]
            if ident in documents:
                return documents[ident]
            fields, evidence, offset = [], {}, 0
            while True:
                page = self.images.read_document(project_id, image_revision_id, ident, offset=offset, limit=90)
                read_bytes += len(json.dumps(page, ensure_ascii=False).encode("utf-8"))
                if read_bytes > 8 * 1024 * 1024:
                    raise ImageRevisionPageTooLarge("link recall document corpus exceeds 8 MiB")
                fields.extend(page["fields"])
                evidence.update({item["evidence_id"]: item for item in page["evidence"]})
                if page["next_offset"] is None:
                    break
                if page["next_offset"] <= offset:
                    raise ImageRevisionIntegrityError("link recall document cursor does not advance")
                offset = page["next_offset"]
            documents[ident] = {**page, "fields": fields, "evidence": list(evidence.values())}
            return documents[ident]

        target_doc = document(target_member)
        target_kind = target_doc["projection"]["kind"]
        if target_kind not in ({"acceptance_criterion"} if relation == "asserts" else {"acceptance_criterion", "business_rule"}):
            raise ValueError("link target must be an independent AC (or rule for implements)")
        target = self._document_endpoint(target_member, target_doc, target_kind)
        parent_id = target_doc["document"].get("parent_document_revision_id")
        parent_member = next((item for item in members.values() if item.get("document_revision_id") == parent_id), None)
        if not parent_id or parent_member is None:
            raise ImageRevisionIntegrityError("link target lacks a frozen requirement parent")
        parent = document(parent_member)
        parent_ref = parent["projection"].get("external_id")
        # Parent description gives disambiguating business context, not sibling ACs.
        context = [field["value"] for field in parent["fields"] if field["name"] == "description"]
        query = " ".join([target.title, *[field["value"] for field in target_doc["fields"]], *context])
        endpoints, candidates, excluded = {}, [], {}
        for ident, member in sorted(members.items()):
            if relation == "implements" and member["kind"] == "code_entity":
                if not member["evidence_ids"]:
                    excluded["missing_code_evidence"] = excluded.get("missing_code_evidence", 0) + 1
                    continue
                endpoint = LinkCandidateEndpoint(ident, member["entity_revision_id"], member["source_revision_id"], "code_entity",
                    objects[ident]["name"], member["object_hash"], tuple(sorted(member["evidence_ids"])))
                # v1 uses frozen symbol/path labels, not fabricated code summaries.
                candidates.append(LinkRecallInput(ident, endpoint.title))
            elif relation == "asserts" and member["kind"] == "source_document":
                doc = document(member)
                if doc["projection"]["kind"] != "test_case":
                    continue
                if not any(field["name"] == "expected_result" and field["value"].strip() for field in doc["fields"]):
                    excluded["missing_expected_result"] = excluded.get("missing_expected_result", 0) + 1
                    continue
                endpoint = self._document_endpoint(member, doc, "expected_result")
                text = " ".join([endpoint.title, *[f["value"] for f in doc["fields"] if f["name"] in {"step", "expected_result", "precondition"}]])
                refs = {ref for f in doc["fields"] if f["name"] == "reference" for ref in requirement_references(f["value"])}
                candidates.append(LinkRecallInput(ident, text, bool(parent_ref and parent_ref.upper() in refs)))
            else:
                continue
            endpoints[ident] = endpoint
        ranked = rank_link_candidates(query, tuple(candidates))
        self.images.authorization.require_current(scope)
        return LinkRecallCorpus(project_id, image_revision_id, header.artifact_hash, target, relation,
            endpoints, ranked, len(candidates), excluded, payload, documents, scope)

    def page(self, corpus, *, limit, ranked=None):
        ranked = corpus.ranked if ranked is None else ranked
        target, endpoints = corpus.target, corpus.endpoints
        project_id, image_revision_id = corpus.project_id, corpus.image_revision_id
        self.images.authorization.require_current(corpus.scope)
        selected = ranked[:limit]
        # Verify archived bytes for the selected oracle/code evidence; the next
        # evidence tool reads the complete span, not an invented semantic summary.
        evidence_endpoints = (target, *(endpoints[item.object_id] for item in selected))
        if sum(len(endpoint.evidence_ids) for endpoint in evidence_endpoints) > 512:
            raise ImageRevisionPageTooLarge("request fewer candidates; evidence verification exceeds 512 spans")
        self.images.verify_evidence_selection(project_id, image_revision_id,
            tuple((endpoint.object_id, evidence_id) for endpoint in evidence_endpoints for evidence_id in endpoint.evidence_ids))
        items = tuple(LinkCandidate(endpoints[item.object_id], item.retrieval_score, item.matched_terms, item.signals) for item in selected)
        result = LinkCandidatePage(project_id, image_revision_id, corpus.image_artifact_hash, target, corpus.relation, items,
                                   corpus.eligible_count, len(ranked), corpus.excluded, len(ranked) > len(selected))
        if len(json.dumps(asdict(result), ensure_ascii=False).encode("utf-8")) > 65536:
            raise ImageRevisionPageTooLarge("request fewer link candidates; response exceeds 64 KiB")
        self.images.authorization.require_current(corpus.scope)
        return result

    @staticmethod
    def _document_endpoint(member, doc, field_name):
        fields = [field for field in doc["fields"] if field["name"] == field_name and field["value"].strip()]
        matched = set()
        for field in fields:
            evidence = {item["evidence_id"] for item in doc["evidence"] if
                (item["start_line"], item["end_line"], item["snippet_hash"]) == (field["start_line"], field["end_line"], field["snippet_hash"])}
            if not evidence or not evidence <= set(member["evidence_ids"]):
                raise ImageRevisionIntegrityError("link candidate field lacks frozen evidence")
            matched.update(evidence)
        if not matched:
            raise ImageRevisionIntegrityError("link candidate has no expected field evidence")
        return LinkCandidateEndpoint(member["object_id"], member["document_revision_id"], member["source_revision_id"],
            doc["projection"]["kind"], doc["projection"]["title"], doc["payload_hash"], tuple(sorted(matched)))
