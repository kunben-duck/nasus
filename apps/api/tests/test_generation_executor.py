import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.generation_budget import GenerationBudgetInvalid, GenerationModelPolicy, GenerationBudgetLimits, reserve_generation_budget, verify_generation_usage
from apps.api.app.application.quality_loop.generation_execution_inputs import GenerationExecutionSelection, generation_messages
from apps.api.app.application.quality_loop.generation_executor import GenerationExecutorApplicationService, GenerationOutcomeUnknown, NativeGenerationReply
from apps.api.app.application.quality_loop.test_design_results import GenerationResultRequest, TestDesignResultIntegrityError, response_digest
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.test_design_generation import compile_generation_input, TestDesignGenerationInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessScope
from apps.api.tests.test_semantic_link_model import resolved
from apps.api.tests.test_test_design_generation import generation_inputs, case_output


def budget(**changes):
    return GenerationBudgetLimits(**{**dict(currency="USD", max_calls=1, max_reserved_tokens=140000,
        max_reserved_cost_nanos=140000000, max_input_tokens_per_call=100000, max_output_tokens_per_call=8192), **changes})


def policy(binding, **changes):
    return GenerationModelPolicy(**{**dict(policy_id="operator-policy", revision="v1", config_id=binding.config_id,
        provider=binding.provider, model_name=binding.model_name, base_url=binding.base_url, currency="USD",
        context_tokens=128000, max_output_tokens=8192, input_nanos_per_token=1000, output_nanos_per_token=1000,
        framing_tokens=12, tokenizer_kind="tiktoken", tokenizer_id="cl100k_base", tokenizer_digest=acceptance_digest("fixture-tokenizer")), **changes})


class MemoryExecutionRepository:
    def __init__(self):
        self.stored = None
        self.calls = []
    def get(self, *args):
        return deepcopy(self.stored)
    def reserve(self, request, payload, *, require_current):
        require_current()
        if self.stored:
            raise GenerationOutcomeUnknown("already reserved")
        self.stored = {"reservation": deepcopy(payload), "reply": None}
    def record_reply(self, request, payload, ref, digest, call, *, require_current):
        require_current()
        self.calls.append(call)
        self.stored["reply"] = {"artifact_ref": ref, "artifact_hash": digest,
            "response_hash": response_digest(payload["content"]), "usage": deepcopy(payload["usage"])}
    def record_failure(self, request, invocation_id, call):
        self.calls.append(call)


def executor():
    prepared = compile_generation_input(*generation_inputs())
    model = resolved()
    class Authorization:
        revoked = False
        access = SourceAccessScope("p", "actor", "project_admin", 1, frozenset({"source"}), frozenset({"legacy"}), acceptance_digest("acl"), False)
        def scope(self, project_id):
            if self.revoked:
                raise PermissionError("revoked")
            return self.access
        def require_current(self, access):
            if self.revoked or access != self.access:
                raise PermissionError("revoked")
    class Artifacts:
        body = None
        def put(self, project_id, payload):
            self.body = deepcopy(payload)
            return "private-fixture", acceptance_digest(payload)
        def read(self, project_id, ref, digest):
            return deepcopy(self.body)
    class Provider:
        calls = 0
        usage = (123, 45)
        failure = None
        async def generate(self, system, content, model, *, max_output_tokens):
            self.calls += 1
            assert json.loads(content) == prepared and max_output_tokens == 8192
            assert "untrusted evidence" in system and "JSON Schema" in system
            if self.failure:
                raise self.failure
            return NativeGenerationReply(json.dumps(case_output(prepared)), *self.usage, "provider")
    class Results:
        fail = False
        calls = 0
        def commit(self, request, **args):
            self.calls += 1
            if self.fail:
                raise RuntimeError("injected result transaction failure")
            return {"generation_id": "draft", "status": "draft"}
    counter = SimpleNamespace(policy=policy(model.binding), count=lambda system, content: 32000)
    services = dict(generation=SimpleNamespace(prepare=lambda request: deepcopy(prepared)), results=Results(),
        profiles=SimpleNamespace(resolve=lambda ident: model), policies=SimpleNamespace(resolve=lambda binding: counter),
        authorization=Authorization(), sources=SimpleNamespace(bindings=lambda data: ("source",)),
        provider=Provider(), repository=MemoryExecutionRepository(), artifacts=Artifacts())
    application = GenerationExecutorApplicationService(**services)
    selection = GenerationExecutionSelection(project_id="p", scope_revision_id="scope-revision", scope_artifact_hash=prepared["scope_pin"]["artifact_hash"],
        model_config_id="model", budget=budget())
    return application, selection, services, prepared


def test_preview_does_not_egress_or_persist_and_never_returns_source_text():
    app, selection, deps, prepared = executor()
    view = app.preview(selection)
    assert deps["provider"].calls == 0 and deps["repository"].stored is None
    assert view["reservation"]["reserved_tokens"] == 136192 and view["reservation"]["reserved_cost_nanos"] == 136192000
    assert not view["generation_authorized"] and not view["execution_authorized"]
    assert view["request"]["execution"]["source_binding_ids"] == ["source"]
    assert "HTTP 400" not in json.dumps(view) and "private-provider-key" not in json.dumps(view)
    assert json.loads(generation_messages(prepared)[1]) == prepared


def test_native_reply_and_usage_are_saved_before_result_commit_and_recovery_never_resends():
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    deps["results"].fail = True
    with pytest.raises(RuntimeError, match="transaction failure"):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["provider"].calls == 1 and deps["repository"].stored["reply"]
    assert deps["repository"].calls[0].outcome == "success"
    deps["results"].fail = False
    assert asyncio.run(app.execute(request, invocation_id="invocation"))["status"] == "draft"
    assert deps["provider"].calls == 1 and deps["results"].calls == 2


@pytest.mark.parametrize("error", [RuntimeError("provider disconnect"), asyncio.CancelledError()])
def test_unknown_or_cancelled_call_retains_reservation_and_is_not_repeated(error):
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    deps["provider"].failure = error
    with pytest.raises(type(error)):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["repository"].stored and deps["repository"].calls[0].outcome == "error"
    with pytest.raises(GenerationOutcomeUnknown):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["provider"].calls == 1 and deps["results"].calls == 0


def test_dependency_change_after_preview_fails_before_any_reservation():
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    deps["policies"].resolve = lambda binding: SimpleNamespace(policy=policy(binding, revision="changed"), count=lambda *args: 32000)
    with pytest.raises(TestDesignGenerationInvalid, match="consent changed"):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["repository"].stored is None and deps["provider"].calls == 0


def test_reservation_rechecks_dependencies_and_model_request_budget_cannot_be_forged():
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    request = request.model_copy(update={"execution": request.execution.model_copy(update={"budget": budget(max_reserved_cost_nanos=1)})})
    with pytest.raises(GenerationBudgetInvalid):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["repository"].stored is None and deps["provider"].calls == 0


@pytest.mark.parametrize("counts", [(0, 45), (123, 9000), (128001, 45)])
def test_unknown_or_excessive_usage_does_not_fake_cost_or_retry(counts):
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    deps["provider"].usage = counts
    with pytest.raises(GenerationBudgetInvalid):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert not deps["repository"].stored["reply"] and deps["results"].calls == 0
    with pytest.raises(GenerationOutcomeUnknown):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["provider"].calls == 1


def test_reservation_counts_whole_capacity_not_only_optimistic_token_estimate():
    model = resolved()
    p = policy(model.binding)
    reserve = reserve_generation_budget(p, budget(), [3000])
    assert reserve["reserved_cost_nanos"] == 136192000
    assert verify_generation_usage(p, budget(), 123, 45)["cost_nanos_at_policy_rates"] == 168000
    for limits in (budget(currency="CNY"), budget(max_reserved_tokens=10000), budget(max_reserved_cost_nanos=100), budget(max_input_tokens_per_call=512)):
        with pytest.raises(GenerationBudgetInvalid):
            reserve_generation_budget(p, limits, [32000])
    with pytest.raises(GenerationBudgetInvalid):
        reserve_generation_budget(p, budget(), [32000, 32000])
    with pytest.raises(GenerationBudgetInvalid):
        reserve_generation_budget(p, budget(), [True])


def test_legacy_request_hash_remains_unchanged_and_new_execution_requires_explicit_consent():
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    legacy = request.model_copy(update={"execution": None})
    assert "execution" not in legacy.model_dump(mode="json")
    with pytest.raises(GenerationBudgetInvalid, match="explicit"):
        asyncio.run(app.execute(legacy, invocation_id="invocation"))
    assert deps["provider"].calls == 0


def test_source_revocation_during_provider_call_blocks_response_archive(monkeypatch):
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    original = deps["provider"].generate
    async def revoke(*args, **kwargs):
        reply = await original(*args, **kwargs)
        deps["authorization"].revoked = True
        return reply
    monkeypatch.setattr(deps["provider"], "generate", revoke)
    with pytest.raises(PermissionError, match="revoked"):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["provider"].calls == 1 and deps["repository"].stored
    assert deps["artifacts"].body is None and deps["repository"].stored["reply"] is None
    assert deps["results"].calls == 0 and deps["repository"].calls[-1].outcome == "error"


def test_source_revocation_during_artifact_write_blocks_receipt_commit(monkeypatch):
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    original = deps["artifacts"].put
    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        deps["authorization"].revoked = True
        return result
    monkeypatch.setattr(deps["artifacts"], "put", revoke)
    with pytest.raises(PermissionError, match="revoked"):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["provider"].calls == 1 and deps["repository"].stored["reply"] is None
    assert deps["results"].calls == 0 and deps["repository"].calls[-1].outcome == "error"


def test_recovery_checks_source_visibility_before_reading_private_reply(monkeypatch):
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    deps["results"].fail = True
    with pytest.raises(RuntimeError, match="transaction failure"):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    access = deps["authorization"].access
    deps["authorization"].access = SourceAccessScope(access.project_id, access.actor_id, access.effective_project_role,
        access.acl_epoch + 1, frozenset(), frozenset(), acceptance_digest("revoked-source"), False)
    reads = []
    original = deps["artifacts"].read
    monkeypatch.setattr(deps["artifacts"], "read", lambda *args: reads.append(args) or original(*args))
    deps["results"].fail = False
    with pytest.raises(PermissionError):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert not reads and deps["provider"].calls == 1 and deps["results"].calls == 1


def test_recovery_rejects_usage_metadata_different_from_archived_native_reply():
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    deps["results"].fail = True
    with pytest.raises(RuntimeError, match="transaction failure"):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    deps["repository"].stored["reply"]["usage"]["input_tokens"] += 1
    deps["results"].fail = False
    with pytest.raises(TestDesignResultIntegrityError, match="usage"):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["provider"].calls == 1 and deps["results"].calls == 1


@pytest.mark.parametrize("counts", [(-1, 45), (True, 45), (None, 45)])
def test_invalid_usage_cannot_mask_failure_audit_or_release_reservation(counts):
    app, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    deps["provider"].usage = counts
    with pytest.raises(GenerationBudgetInvalid):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    call = deps["repository"].calls[-1]
    assert call.outcome == "error" and call.usage_source == "none"
    assert call.input_token_count == call.output_token_count == 0
    assert deps["repository"].stored["reply"] is None
    with pytest.raises(GenerationOutcomeUnknown):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert deps["provider"].calls == 1
