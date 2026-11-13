import json
import re

from ...domain.system_image.source_snapshots import snapshot_digest


class RequirementReviewContext:
    def __init__(self, images):
        self.images = images

    def prepare(self, revision):
        header, snapshot = self.images.frozen_snapshot(revision.project_id, revision.image_revision_id)
        if header.artifact_hash != revision.image_artifact_hash:
            raise ValueError("Requirement image digest changed")
        evidence = [{"ref": "requirement:" + revision.revision_id, "kind": "user_requirement",
            "text": revision.text, "title": revision.title}]
        evidence.extend({"ref": f"answer:{index + 1}", "kind": "user_answer", **item.model_dump()}
            for index, item in enumerate(revision.clarification_answers))
        query = (revision.title + " " + revision.text).lower()
        terms = set(re.findall(r"[a-z][a-z0-9_]{2,}", query)) - {"the", "and", "for", "with", "support"}
        operations = set()
        for pattern, words in ((r"edit|updat|modify|修改|编辑|更新", {"update", "edit", "patch", "put"}),
                (r"creat|新增|创建", {"create", "post"}), (r"delet|remov|删除", {"delete", "remove"}),
                (r"permission|authoriz|权限|越权", {"auth", "permission", "owner"})):
            if re.search(pattern, query):
                operations.update(words)
        members = {item["object_id"]: item for item in snapshot["members"]}
        candidates = [item for item in snapshot["objects"] if members[item["id"]].get("evidence_ids")]
        def score(item):
            name = item["name"].lower()
            symbol = name.split(" (")[0]
            return (bool(item.get("document_reference")),
                sum(term in name for term in terms) + 4 * sum(word in symbol for word in operations)
                - (3 if "/migrations/" in name or "/management/" in name else 0), name, item["id"])
        candidates.sort(key=score, reverse=True)
        selected = []
        with self.images.verified_read_session(reuse=True):
            for item in candidates[:16]:
                member = members[item["id"]]
                evidence_id = member["evidence_ids"][0]
                if item.get("document_reference"):
                    # Evidence IDs are UUID-sorted, not ordered by source location.
                    # Select the document span instead of a random individual field.
                    document = self.images.read_document(revision.project_id, revision.image_revision_id, item["id"], limit=1)
                    locator = document["projection"]["locator"]
                    whole = next((row for row in document["evidence"] if
                        (row["start_line"], row["end_line"], row["relative_path"]) ==
                        (locator["start_line"], locator["end_line"], locator["relative_path"])), None)
                    if whole is None:
                        raise ValueError("Frozen document has no verified whole-record evidence")
                    evidence_id = whole["evidence_id"]
                span = self.images.read_evidence(revision.project_id, revision.image_revision_id,
                    item["id"], evidence_id, max_lines=60)
                entry = {"ref": "evidence:" + item["id"] + ":" + evidence_id,
                    "kind": "source_document" if item.get("document_reference") else "implementation_not_oracle",
                    "object_id": item["id"], "evidence_id": evidence_id, "title": item["name"],
                    "text": span.content, "excerpt_hash": span.excerpt_hash,
                    "start_line": span.start_line, "end_line": span.end_line,
                    "next_start_line": span.next_start_line}
                if len(json.dumps(evidence + [entry], ensure_ascii=False).encode()) > 40000:
                    break
                evidence.append(entry)
                selected.append(item["id"])
        payload = {"project_id": revision.project_id, "version_id": revision.version_id,
            "revision_id": revision.revision_id, "requirement_hash": revision.content_hash,
            "image_revision_id": revision.image_revision_id, "image_artifact_hash": revision.image_artifact_hash,
            "evidence": evidence, "bounded_retrieval": True, "omitted_objects": len(candidates) - len(selected)}
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 48000:
            raise ValueError("Requirement and clarification exceed the review context budget")
        return payload, snapshot_digest(payload)
