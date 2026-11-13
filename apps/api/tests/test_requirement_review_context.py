from contextlib import nullcontext
from types import SimpleNamespace

from apps.api.app.application.quality_loop.requirement_review_context import RequirementReviewContext


def test_document_context_uses_whole_record_not_uuid_first_field():
    seen = []
    locator = {"relative_path": "spec.md", "start_line": 1, "end_line": 80}
    class Images:
        def frozen_snapshot(self, *_):
            return SimpleNamespace(artifact_hash="hash"), {
                "members": [{"object_id": "doc", "evidence_ids": ["a-random-field", "z-whole-record"]}],
                "objects": [{"id": "doc", "name": "Article update specification", "document_reference": {"revision": "docrev"}}],
            }
        def verified_read_session(self, **_):
            return nullcontext()
        def read_document(self, *_, **kwargs):
            return {"projection": {"locator": locator}, "evidence": [
                {**locator, "evidence_id": "a-random-field", "start_line": 70, "end_line": 70},
                {**locator, "evidence_id": "z-whole-record"}]}
        def read_evidence(self, project, image, object_id, evidence_id, **_):
            seen.append(evidence_id)
            return SimpleNamespace(content="PUT article specification", excerpt_hash="hash", start_line=1, end_line=60, next_start_line=61)
    revision = SimpleNamespace(project_id="p", version_id="v", revision_id="r", image_revision_id="i",
        image_artifact_hash="hash", content_hash="hash", title="Article editing", text="Support editing", clarification_answers=[])
    payload, _ = RequirementReviewContext(Images()).prepare(revision)
    assert seen == ["z-whole-record"]
    assert payload["evidence"][-1]["text"] == "PUT article specification"
    assert payload["evidence"][-1]["next_start_line"] == 61
