from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...domain.system_image.evidence import text_digest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.retrieval_index import INDEX_METHOD, MAX_DOCUMENTS, MAX_INPUT_BYTES, IndexDocument, split_utf8
from ...domain.system_image.source_snapshots import snapshot_digest
from .frozen_evidence_span import read_frozen_evidence_span

INDEX_PREVIEW_TOOL = "query.system_image.index.preview"
INDEX_BUILD_TOOL = "system_image.index.build"


class IndexSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: str = Field(min_length=1, max_length=128)
    publication_id: str = Field(min_length=1, max_length=128)
    model_config_id: str = Field(min_length=1, max_length=128)
    method_version: Literal["nasus.frozen-evidence-index.v1"] = INDEX_METHOD


class IndexBuildRequest(IndexSelection):
    input_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model_config_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class FrozenIndexInputs:
    def __init__(self, images):
        self.images = images

    def prepare(self, project_id, pin):
        with self.images.verified_read_session():
            header, payload = self.images.frozen_snapshot(project_id, pin.image_revision_id)
            if (header.artifact_hash, header.manifest_id, header.manifest_hash) != (
                    pin.image_artifact_hash, pin.manifest_id, pin.manifest_hash):
                raise ImageRevisionIntegrityError("index image pin mismatch")
            documents, byte_count = [], 0
            bindings = {member["source_revision_id"]: member["binding_id"] for member in payload["source_members"]}
            for member in sorted(payload["members"], key=lambda item: item["object_id"]):
                if member["kind"] not in {"code_entity", "source_document"}:
                    continue
                if not member["evidence_ids"]:
                    raise ImageRevisionIntegrityError("index member lacks source evidence")
                for evidence_id in sorted(member["evidence_ids"]):
                    evidence, raw = read_frozen_evidence_span(self.images, project_id, pin.image_revision_id,
                        member["object_id"], evidence_id)
                    if evidence.binding_id != bindings[member["source_revision_id"]]:
                        raise ImageRevisionIntegrityError("index evidence binding mismatch")
                    for ordinal, part in enumerate(split_utf8(raw)):
                        revision = member.get("entity_revision_id") or member.get("document_revision_id")
                        key = snapshot_digest([INDEX_METHOD, pin.image_revision_id, member["object_id"], revision, evidence_id, ordinal])
                        documents.append(IndexDocument(key, member["object_id"], revision, member["source_revision_id"],
                            evidence.binding_id, evidence_id, member["kind"], ordinal, part, text_digest(part)))
                        byte_count += len(part.encode("utf-8"))
                        if len(documents) > MAX_DOCUMENTS or byte_count > MAX_INPUT_BYTES:
                            raise ImageRevisionPageTooLarge("index input exceeds the confirmed build budget; nothing was sent")
            if not documents or not any(item.kind == "code_entity" for item in documents):
                raise ImageRevisionIntegrityError("index requires verified code members")
            digest = snapshot_digest({"method": INDEX_METHOD, "publication": pin.model_dump(),
                "documents": [asdict(item) for item in documents]})
            return tuple(documents), digest
