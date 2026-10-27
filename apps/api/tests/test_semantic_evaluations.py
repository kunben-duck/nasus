import asyncio
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.semantic_evaluations import SemanticEvaluationApplicationService, SemanticEvaluationRequest, SemanticSelection
from apps.api.app.application.system_image.semantic_model_port import SemanticModelReply
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_semantic_links import prepared_input, response
from apps.api.tests.test_semantic_link_model import resolved


@pytest.fixture
def service():
    scope = SimpleNamespace(actor_id="admin", effective_project_role="project_admin")
    rows, artifacts, audit, calls = {}, {}, [], []
    prepared = prepared_input()
    model = resolved()
    def reserve(request, preview, prepared, *, invocation_id, actor_id, require_current):
        assert invocation_id not in rows
        require_current()
        rows[invocation_id] = {"request": request.model_dump(), "preview": preview.model_dump()}
    def put(project_id, payload):
        digest = snapshot_digest(payload)
        artifacts[digest] = payload
        return digest, digest
    def complete(request, *, invocation_id, artifact_ref, artifact_hash, require_current):
        require_current()
        rows[invocation_id].update(artifact_ref=artifact_ref, artifact_hash=artifact_hash)
    async def generate(prepared, pinned):
        calls.append(pinned.binding)
        return SemanticModelReply(json.dumps(response(prepared)), 10, 20, "provider")
    authorization = SimpleNamespace(scope=lambda project: scope, require_current=lambda scope: None)
    application = SemanticEvaluationApplicationService(SimpleNamespace(authorization=authorization),
        SimpleNamespace(resolve=lambda config: model), SimpleNamespace(generate=generate),
        SimpleNamespace(get=lambda project, ident: rows.get(ident), reserve=reserve, complete=complete),
        SimpleNamespace(put=put, read=lambda project, ref, digest: artifacts[digest]),
        SimpleNamespace(persist_llm_call=audit.append))
    application._prepare = lambda request: prepared
    screening = SimpleNamespace(digest=snapshot_digest({"heads": []}), items=(), require_eligible=lambda: None)
    application.decision_guard = SimpleNamespace(screen=lambda request: screening, require_current=lambda snapshot: None)
    preview = application.preview(SemanticSelection(project_id="p", image_revision_id="image", target_object_id="ac",
        subject_object_ids=["subject"], relation="asserts", expected_image_hash=prepared.image_artifact_hash,
        model_config_id="model"))
    return SimpleNamespace(application=application, request=preview.request, rows=rows, artifacts=artifacts,
                           calls=calls, audit=audit, scope=scope, prepared=prepared)


def test_commit_then_retry_replays_without_model_or_new_audit(service):
    v = service
    result = asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))
    assert len(v.calls) == len(v.audit) == 1
    assert v.audit[0].outcome == "success" and v.audit[0].model_calls == 1
    assert asyncio.run(v.application.evaluate(v.request, invocation_id="invocation")) == result
    assert len(v.calls) == len(v.audit) == 1
    assert "quote" not in json.dumps(asdict(v.audit[0]), default=str)


def test_reserved_unknown_outcome_cannot_be_retried(service):
    v = service
    async def fail(prepared, model):
        v.calls.append(True)
        raise RuntimeError("unknown network outcome")
    v.application.provider.generate = fail
    with pytest.raises(RuntimeError):
        asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))
    assert len(v.calls) == len(v.audit) == 1 and v.audit[0].outcome == "error"
    with pytest.raises(ValueError, match="not retried"):
        asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))
    assert len(v.calls) == len(v.audit) == 1 and not v.artifacts


def test_model_rotation_after_reservation_burns_grant_without_egress(service):
    v = service
    initial = v.application.models.resolve
    count = []
    def rotate(config):
        count.append(True)
        return initial(config) if len(count) == 1 else resolved(key="new-key")
    v.application.models.resolve = rotate
    with pytest.raises(ImageRevisionIntegrityError, match="model changed"):
        asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))
    assert "invocation" in v.rows and not v.calls and not v.audit
    with pytest.raises(ValueError, match="not retried"):
        asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))


def test_cancellation_preserves_reservation_and_records_failure(service):
    v = service
    async def run():
        started = asyncio.Event()
        async def slow(prepared, model):
            v.calls.append(True)
            started.set()
            await asyncio.sleep(60)
        v.application.provider.generate = slow
        task = asyncio.create_task(v.application.evaluate(v.request, invocation_id="invocation"))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert "invocation" in v.rows and not v.artifacts and len(v.audit) == 1
    assert v.audit[0].outcome == "error"
    with pytest.raises(ValueError, match="not retried"):
        asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))


def test_permission_revocation_after_artifact_put_prevents_commit(service):
    v = service
    original = v.application.artifacts.put
    def put(*args):
        stored = original(*args)
        def deny(scope):
            raise SourceAccessDenied("revoked")
        v.application.images.authorization.require_current = deny
        return stored
    v.application.artifacts.put = put
    with pytest.raises(SourceAccessDenied):
        asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))
    assert not v.rows["invocation"].get("artifact_ref")
    assert len(v.calls) == 1
    with pytest.raises(KeyError):
        v.application.read("p", "invocation")


def test_archive_result_is_revalidated_not_trusted_on_read(service):
    v = service
    result = asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))
    payload = v.artifacts[result["artifact_hash"]]
    payload["evaluation"]["status"] = "accepted"
    with pytest.raises(ImageRevisionIntegrityError, match="result mismatch"):
        v.application.read("p", "invocation")
    payload["model_output"] = "invalid-json-do-not-echo"
    with pytest.raises(ImageRevisionIntegrityError, match="archived semantic output failed validation"):
        v.application.read("p", "invocation")


def test_legacy_archived_requests_remain_readable_but_cannot_start_new_calls(service):
    v = service
    result = asyncio.run(v.application.evaluate(v.request, invocation_id="invocation"))
    payload = v.artifacts[result["artifact_hash"]]
    payload["request"].pop("review_scope_digest")
    payload["preview"]["request"].pop("review_scope_digest")
    payload["preview"].pop("review_screening")
    saved = v.rows["invocation"]
    saved["request"].pop("review_scope_digest")
    saved["preview"]["request"].pop("review_scope_digest")
    saved["preview"].pop("review_screening")
    legacy = SemanticEvaluationRequest.model_validate(saved["request"])
    assert "review_scope_digest" not in legacy.model_dump()
    assert v.application.read("p", "invocation")["request"] == saved["request"]
    assert asyncio.run(v.application.evaluate(legacy, invocation_id="invocation"))["request"] == saved["request"]
    with pytest.raises(ImageRevisionIntegrityError, match="review consent changed"):
        asyncio.run(v.application.evaluate(legacy, invocation_id="new-invocation"))
    assert len(v.calls) == 1 and "new-invocation" not in v.rows


def test_unwired_review_guard_does_not_silently_skip_screening(service):
    service.application.decision_guard = None
    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(service.application.evaluate(service.request, invocation_id="new-invocation"))
    assert not service.calls and not service.rows
