import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...domain.system_image.context_partition import MAX_CONSTRAINTS
from ...domain.system_image.context_retrieval_plan import CONTEXT_QUERY_METHOD, ContextRetrievalQuery, source_query, query_plan_budget
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.source_snapshots import snapshot_digest

CONTEXT_RETRIEVAL_PREVIEW_TOOL = "query.system_image.context.retrieval_preview"


class ContextRetrievalSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: str = Field(min_length=1, max_length=128)
    publication_id: str = Field(min_length=1, max_length=128)
    generation_id: str = Field(min_length=1, max_length=128)
    method_version: Literal["nasus.context-retrieval-plan.v1"] = CONTEXT_QUERY_METHOD


class ContextRetrievalInputs:
    """All ACs, only source fields covered by the selected index's egress consent."""

    def __init__(self, images):
        self.images = images

    def prepare(self, selection, pin, index, artifact_hash):
        with self.images.verified_read_session():
            queries = self._queries(selection.project_id, pin, index)
        budget = query_plan_budget(queries)
        body = {"request": selection.model_dump(), "publication_pin": pin.model_dump(),
            "index_artifact_hash": artifact_hash, "model": index["model"], **budget,
            "source_binding_ids": sorted({query.binding_id for query in queries}),
            "state": "prepared" if queries else "missing_requirements",
            "source_policy": "frozen_ac_and_parent_description_only",
            "execution_available": True, "model_calls_made": 0, "cost_estimate_available": False,
            "relationship_authority": False, "quality_generation_authorized": False,
            "rerank_egress_authorized": False}
        return queries, {**body, "plan_digest": snapshot_digest(body)}

    def _queries(self, project_id, pin, index):
        header, payload = self.images.frozen_snapshot(project_id, pin.image_revision_id)
        if (header.artifact_hash, header.manifest_id, header.manifest_hash) != (
                pin.image_artifact_hash, pin.manifest_id, pin.manifest_hash):
            raise ImageRevisionIntegrityError("context query image pin mismatch")
        members = {member["object_id"]: member for member in payload["members"]}
        revisions = {member["document_revision_id"]: member for member in members.values() if member["kind"] == "source_document"}
        targets = sorted(obj["id"] for obj in payload["objects"] if obj["type"] == "SourceAcceptanceCriterion")
        constraints = sum(obj["type"] in {"SourceAcceptanceCriterion", "SourceBusinessRule"} for obj in payload["objects"])
        if constraints > MAX_CONSTRAINTS:
            raise ImageRevisionPageTooLarge("mandatory constraints exceed the context policy; no AC was omitted")
        bindings = {member["source_revision_id"]: member["binding_id"] for member in payload["source_members"]}
        indexed = {(item["document"]["object_id"], item["document"]["evidence_id"]): item["document"] for item in index["documents"]}
        documents, read_bytes = {}, 0

        def document(member):
            nonlocal read_bytes
            ident = member["object_id"]
            if ident not in documents:
                fields, evidence, offset = [], {}, 0
                while True:
                    page = self.images.read_document(project_id, pin.image_revision_id, ident, offset=offset, limit=90)
                    read_bytes += len(json.dumps(page, ensure_ascii=False).encode("utf-8"))
                    if read_bytes > 8 * 1024 * 1024:
                        raise ImageRevisionPageTooLarge("context query source documents exceed 8 MiB")
                    fields.extend(page["fields"])
                    evidence.update({item["evidence_id"]: item for item in page["evidence"]})
                    if page["next_offset"] is None:
                        break
                    if page["next_offset"] <= offset:
                        raise ImageRevisionIntegrityError("context query document cursor does not advance")
                    offset = page["next_offset"]
                documents[ident] = {**page, "fields": fields, "evidence": list(evidence.values())}
            return documents[ident]

        def source_fields(member, doc, name):
            fields = tuple(field for field in doc["fields"] if field["name"] == name)
            proofs = set()
            for field in fields:
                matches = {item["evidence_id"] for item in doc["evidence"] if
                    (item["start_line"], item["end_line"], item["snippet_hash"]) ==
                    (field["start_line"], field["end_line"], field["snippet_hash"])}
                if not matches or not matches <= set(member["evidence_ids"]):
                    raise ImageRevisionIntegrityError("context query field lacks frozen evidence")
                for evidence_id in matches:
                    entry = indexed.get((member["object_id"], evidence_id))
                    expected = (member["document_revision_id"], member["source_revision_id"], bindings[member["source_revision_id"]], "source_document")
                    if not entry or tuple(entry[key] for key in ("revision_id", "source_revision_id", "binding_id", "kind")) != expected:
                        raise ImageRevisionIntegrityError("context query field is outside the consented index")
                    proofs.add((member["object_id"], evidence_id))
            return tuple(field["value"] for field in fields), proofs

        queries = []
        for target in targets:
            member = members.get(target)
            if not member or member["kind"] != "source_document":
                raise ImageRevisionIntegrityError("context AC is not a frozen source document")
            doc = document(member)
            parent_member = revisions.get(doc["document"].get("parent_document_revision_id"))
            if (doc["projection"]["kind"] != "acceptance_criterion" or not parent_member
                    or parent_member["source_revision_id"] != member["source_revision_id"]):
                raise ImageRevisionIntegrityError("context AC lacks an exact frozen requirement parent")
            parent = document(parent_member)
            if parent["projection"]["kind"] != "requirement":
                raise ImageRevisionIntegrityError("context AC parent is not a requirement")
            values, proofs = source_fields(member, doc, "acceptance_criterion")
            descriptions, parent_proofs = source_fields(parent_member, parent, "description")
            queries.append(ContextRetrievalQuery(target, member["document_revision_id"], parent_member["object_id"],
                parent_member["document_revision_id"], member["source_revision_id"], bindings[member["source_revision_id"]],
                tuple(sorted(proofs | parent_proofs)), source_query(values, descriptions)))
        evidence = sorted({proof for query in queries for proof in query.evidence_selections})
        for offset in range(0, len(evidence), 512):
            self.images.verify_evidence_selection(project_id, pin.image_revision_id, tuple(evidence[offset:offset + 512]))
        return tuple(queries)
