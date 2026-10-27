from __future__ import annotations

from dataclasses import asdict
import json

from ...domain.system_image.evidence import text_digest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge, require_digest
from ...domain.system_image.semantic_link_input import GroundedExcerpt, SemanticEndpoint, SemanticLinkInput, MAX_INPUT_BYTES, require_identifier
from ...domain.system_image.source_snapshots import snapshot_digest
from .image_revision_queries import ImageRevisionQueryApplicationService
from .link_candidates import LinkCandidateQueryApplicationService
from .image_query_models import ImageScreenedCandidatesReceipt


class SemanticLinkInputApplicationService:
    """Prepare source-grounded inputs; reading permission is NOT model-egress permission."""

    def __init__(self, images: ImageRevisionQueryApplicationService):
        self.images = images
        self.recall = LinkCandidateQueryApplicationService(images)

    def prepare(self, project_id: str, image_revision_id: str, target_object_id: str, *, relation: str,
                subject_object_ids: tuple[str, ...], expected_image_hash: str, recall_limit: int = 30,
                recall_receipt=None) -> SemanticLinkInput:
        for value in (project_id, image_revision_id, target_object_id):
            require_identifier(value)
        require_digest(expected_image_hash)
        if (type(subject_object_ids) is not tuple or not 1 <= len(subject_object_ids) <= 30
                or len(set(subject_object_ids)) != len(subject_object_ids)):
            raise ValueError("select 1..30 unique recalled subjects")
        for value in subject_object_ids:
            require_identifier(value)
        # The snapshot ends before model egress; every read still checks live ACL.
        with self.images.verified_read_session():
            return self._prepare(project_id, image_revision_id, target_object_id, relation=relation,
                subject_object_ids=subject_object_ids, expected_image_hash=expected_image_hash,
                recall_limit=recall_limit, recall_receipt=recall_receipt)

    def _prepare(self, project_id, image_revision_id, target_object_id, *, relation,
                 subject_object_ids, expected_image_hash, recall_limit, recall_receipt):
        scope = self.images.authorization.scope(project_id)
        header, _ = self.images.frozen_snapshot(project_id, image_revision_id)
        if header.artifact_hash != expected_image_hash:
            raise ImageRevisionIntegrityError("semantic selection image digest mismatch")
        if recall_receipt is None:
            recall = self.recall.read(project_id, image_revision_id, target_object_id, relation=relation, limit=recall_limit)
            if recall.image_artifact_hash != expected_image_hash:
                raise ImageRevisionIntegrityError("semantic recall image digest mismatch")
            selected = {item.endpoint.object_id: item.endpoint for item in recall.items}
            target_value, method, digest, truncated = recall.target, recall.method_version, snapshot_digest(asdict(recall)), recall.truncated
        else:
            if not isinstance(recall_receipt, ImageScreenedCandidatesReceipt):
                raise ValueError("a canonical screened recall receipt is required")
            pinned = recall_receipt.request
            if ((pinned.project_id, pinned.image_revision_id, pinned.target_object_id, pinned.relation, pinned.limit) !=
                    (project_id, image_revision_id, target_object_id, relation, recall_limit)
                    or recall_receipt.artifact_hash != expected_image_hash):
                raise ImageRevisionIntegrityError("semantic recall receipt scope mismatch")
            selected = {item.object_id: item for item in recall_receipt.candidates}
            target_value, method = recall_receipt.target, pinned.method_version
            digest, truncated = snapshot_digest(recall_receipt.model_dump(mode="json")), recall_receipt.truncated
        if not set(subject_object_ids) <= set(selected):
            raise ValueError("semantic subjects must belong to the explicit recalled selection")

        def endpoint(value):
            fields = value.model_dump() if hasattr(value, "model_dump") else asdict(value)
            fields.pop("title", None)
            fields["evidence_ids"] = tuple(fields["evidence_ids"])
            return SemanticEndpoint(**fields)

        target = endpoint(target_value)
        subjects = tuple(endpoint(selected[key]) for key in sorted(subject_object_ids))
        excerpts, bytes_read = [], 0
        for item in (target, *subjects):
            fields = self._fields(project_id, image_revision_id, item) if item.kind != "code_entity" else ()
            for evidence_id in item.evidence_ids:
                self.images.authorization.require_current(scope)
                evidence, raw = self._source(project_id, image_revision_id, item.object_id, evidence_id)
                if evidence.source_revision_id != item.source_revision_id:
                    raise ImageRevisionIntegrityError("semantic evidence source mismatch")
                values = [(None, raw, "source_excerpt", "implementation")] if item.kind == "code_entity" else [
                    (index, field["value"], "projected_field", field["name"]) for index, field in fields
                    if (field["start_line"], field["end_line"], field["snippet_hash"]) ==
                       (evidence.locator.start_line, evidence.locator.end_line, evidence.snippet_hash)]
                if not values:
                    raise ImageRevisionIntegrityError("semantic evidence does not locate the selected field")
                for index, text, basis, role in values:
                    value = GroundedExcerpt(item.object_id, item.revision_id, item.source_revision_id, evidence_id,
                        evidence.binding_id, evidence.locator.relative_path, evidence.locator.start_line, evidence.locator.end_line,
                        evidence.file_hash, evidence.snippet_hash, raw, text, basis, role, index, evidence.decoder_version)
                    bytes_read += len(json.dumps(asdict(value), ensure_ascii=False).encode("utf-8"))
                    if bytes_read > MAX_INPUT_BYTES or len(excerpts) >= 128:
                        raise ImageRevisionPageTooLarge("semantic input evidence budget exceeded; reduce the selection")
                    excerpts.append(value)
        result = SemanticLinkInput(project_id, image_revision_id, expected_image_hash, relation, target, subjects,
            tuple(excerpts), method, digest, truncated)
        self.images.authorization.require_current(scope)
        return result

    def _fields(self, project_id, image_revision_id, endpoint):
        offset, fields, byte_count, total = 0, [], 0, None
        role = "expected_result" if endpoint.kind == "test_case" else endpoint.kind
        while True:
            page = self.images.read_document(project_id, image_revision_id, endpoint.object_id, offset=offset, limit=90)
            if (page["document"]["document_revision_id"] != endpoint.revision_id
                    or page["document"]["source_revision_id"] != endpoint.source_revision_id
                    or page["projection"]["kind"] != endpoint.kind or page["payload_hash"] != endpoint.content_hash):
                raise ImageRevisionIntegrityError("semantic document endpoint mismatch")
            if total is None:
                total = page["total_fields"]
            if type(total) is not int or not 1 <= total <= 90 or page["total_fields"] != total:
                raise ImageRevisionIntegrityError("semantic field count mismatch")
            byte_count += len(json.dumps(page, ensure_ascii=False).encode("utf-8"))
            if byte_count > MAX_INPUT_BYTES:
                raise ImageRevisionPageTooLarge("semantic document metadata exceeds budget")
            fields.extend((offset + i, field) for i, field in enumerate(page["fields"])
                          if field["name"] == role and field["value"].strip())
            following = page["next_offset"]
            if following is None:
                if offset + len(page["fields"]) != total:
                    raise ImageRevisionIntegrityError("semantic fields are truncated")
                break
            if (type(following) is not int or following != offset + len(page["fields"])
                    or not offset < following < total):
                raise ImageRevisionIntegrityError("semantic field pagination is not contiguous")
            offset = following
        if not fields:
            raise ImageRevisionIntegrityError("semantic endpoint lacks required fields")
        return tuple(fields)

    def _source(self, project_id, image_revision_id, object_id, evidence_id):
        offset, evidence, parts, byte_count = None, None, [], 0
        while True:
            page = self.images.read_evidence(project_id, image_revision_id, object_id, evidence_id, start_line=offset, max_lines=200)
            if evidence is None:
                evidence = page.evidence
                offset = evidence.locator.start_line
            if (page.evidence != evidence or page.evidence.evidence_id != evidence_id or page.integrity != "verified"
                    or page.start_line != offset or not offset <= page.end_line <= evidence.locator.end_line
                    or evidence.locator.precision != "exact" or page.end_line - offset >= 200
                    or page.excerpt_hash != text_digest(page.content)):
                raise ImageRevisionIntegrityError("semantic source page integrity mismatch")
            byte_count += len(page.content.encode("utf-8"))
            if byte_count > 65536:
                raise ImageRevisionPageTooLarge("semantic source span exceeds 64 KiB; no partial evidence accepted")
            parts.append(page.content)
            if len(parts) > 512:
                raise ImageRevisionPageTooLarge("semantic source pagination exceeds budget")
            following = page.next_start_line
            if following is None:
                if page.end_line != evidence.locator.end_line:
                    raise ImageRevisionIntegrityError("semantic source span is truncated")
                break
            if type(following) is not int or following != page.end_line + 1 or following > evidence.locator.end_line:
                raise ImageRevisionIntegrityError("semantic source cursor is invalid")
            offset = following
        raw = "".join(parts)
        if text_digest(raw) != evidence.snippet_hash:
            raise ImageRevisionIntegrityError("semantic full source span hash mismatch")
        return evidence, raw
