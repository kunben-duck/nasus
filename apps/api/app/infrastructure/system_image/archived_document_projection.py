from __future__ import annotations

from collections import Counter

from ...domain.system_image.document_projection import DOCUMENT_EXTRACTOR
from ...domain.system_image.document_components import component_payloads
from ...domain.system_image.source_snapshots import snapshot_digest


class ArchivedDocumentProjection:
    def __init__(self, archive, artifacts, repository, *, max_files=5000, max_bytes=100 * 1024 * 1024,
                 max_file_bytes=10 * 1024 * 1024):
        self.archive, self.artifacts, self.repository = archive, artifacts, repository
        self.max_files, self.max_bytes, self.max_file_bytes = max_files, max_bytes, max_file_bytes

    def record(self, source, result, units, *, captured_at):
        if not self.archive.owns_ref(source.content_ref):
            return ()
        manifest = self.archive.read_manifest(source.content_ref, project_id=source.project_id, source_id=source.id,
            content_hash=source.content_hash, max_files=self.max_files, max_bytes=self.max_bytes, max_file_bytes=self.max_file_bytes)
        files = {item["path"]: item for item in manifest["files"]}
        by_path = {item.relative_path: item for item in units}
        statuses = {item["path"]: item for item in result.files}
        if len(by_path) != len(units) or len(statuses) != len(result.files) or not statuses.keys() <= by_path.keys() <= files.keys():
            raise ValueError("document extraction scope mismatch")
        for path, unit in by_path.items():
            if (files[path]["content_hash"] != unit.content_hash or files[path]["byte_count"] != unit.byte_count
                    or (unit.text_is_lossless and snapshot_digest_bytes(unit.text.encode()) != unit.content_hash)):
                raise ValueError("document text fingerprint mismatch")
        items = []
        for observation in result.observations:
            unit = by_path.get(observation.relative_path)
            if unit is None or not unit.text_is_lossless or statuses[unit.relative_path]["status"] != "parsed":
                raise ValueError("document projection has no exact parsed source")
            payload = {**observation.payload(unit.text, unit.content_hash), "project_id": source.project_id,
                       "source_id": source.id, "source_manifest_hash": snapshot_digest(manifest)}
            ref, digest = self.artifacts.put(source.project_id, payload)
            items.append((observation.identity_key, payload, ref, digest))
            for key, child in component_payloads(observation, payload, unit.text):
                ref, digest = self.artifacts.put(source.project_id, child)
                items.append((key, child, ref, digest))
            if len(items) > 10000:
                raise ValueError("document projection exceeds entity limit including components")
        inventory = [statuses.get(path, {"path": path, "status": "not_analyzed", "reason": "text_not_extracted"})
                     for path in sorted(files)]
        per_file = Counter(p["locator"]["relative_path"] for _, p, _, _ in items)
        if any(count > 1000 for count in per_file.values()):
            raise ValueError("document projection exceeds per-file entity limit including components")
        inventory = [{**item, "entity_count": per_file[item["path"]]} if item["status"] == "parsed" else item
                     for item in inventory]
        counts = Counter(item["status"] for item in inventory)
        summary = {"file_count": len(files), "entity_count": len(items), **{key: counts[key] for key in
                   ("parsed", "unsupported", "failed", "not_analyzed")}}
        report = {"schema": "nasus.source-document-extraction.v1", "project_id": source.project_id,
                  "source_id": source.id, "source_manifest_hash": snapshot_digest(manifest),
                  "extractor_version": DOCUMENT_EXTRACTOR, "files": inventory, "summary": summary,
                  "payload_hashes": sorted(item[3] for item in items)}
        report_ref, report_hash = self.artifacts.put(source.project_id, report)
        return self.repository.record(source, items, manifest_hash=snapshot_digest(manifest),
            report_ref=report_ref, report_hash=report_hash, summary=summary, captured_at=captured_at)


def snapshot_digest_bytes(body):
    import hashlib
    return "sha256:" + hashlib.sha256(body).hexdigest()
