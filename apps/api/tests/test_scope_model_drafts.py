"""Safety regressions, not live product acceptance."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.scope_draft_inputs import ScopeDraftSelection, ScopeDraftRequest, validate_scope_draft
from apps.api.app.application.quality_loop.scope_drafts import ScopeDraftApplicationService
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown, NativeGenerationReply
from apps.api.app.application.quality_loop.test_design_scope_inputs import ScopeReviewInput
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.system_image.source_access import SourceAccessScope
from apps.api.tests.test_generation_executor import budget, policy
from apps.api.tests.test_semantic_link_model import resolved
from apps.api.tests.test_test_design_generation import generation_inputs


def setup():
    context, approved = generation_inputs()
    model = resolved()
    access = SourceAccessScope("p", "operator", "project_admin", 1, frozenset({"source"}), frozenset(), acceptance_digest("acl"), False)
    class Authorization:
        revoked = False
        def scope(self, _):
            self.require_current(access)
            return access
        def require_current(self, _):
            if self.revoked:
                raise PermissionError("revoked")
    class Repository:
        values = None
        def __init__(self):
            self.values, self.calls = {}, []
        def events(self, *_):
            return deepcopy(self.values)
        def history(self, *_):
            return [deepcopy(self.values["reserved"])] if self.values else []
        def record(self, request, invocation_id, actor_id, kind, payload, *, require_current, call=None):
            require_current()
            if kind == "reserved" and self.values:
                raise GenerationOutcomeUnknown("reserved")
            value = dict(invocation_id=invocation_id, actor_id=actor_id, payload=deepcopy(payload), recorded_at="now")
            self.values[kind] = value
            if call:
                self.calls.append(call)
            return value
    class Artifacts:
        payload = None
        def put(self, _, value):
            self.payload = deepcopy(value)
            return "private", acceptance_digest(value)
        def read(self, *_):
            return deepcopy(self.payload)
    class Provider:
        calls = 0
        fail = False
        async def generate(self, system, content, model, *, max_output_tokens):
            self.calls += 1
            assert "untrusted data" in system
            if self.fail:
                raise RuntimeError("disconnected")
            prepared = json.loads(content)["input"]
            contract = deepcopy(approved["request"]["contract"])
            contract["authority_basis"] = "model_suggestion"
            for example in contract["examples"]:
                example["positive"] = deepcopy(next(item["oracle"] for item in prepared["context"]["required_constraints"]
                    if item["object_id"] == example["constraint_id"]))
            return NativeGenerationReply(json.dumps({"input_digest": prepared["input_digest"], "contract": contract}), 123, 45, "provider")
    auth, repo, artifacts, provider = Authorization(), Repository(), Artifacts(), Provider()
    app = ScopeDraftApplicationService(SimpleNamespace(authorization=auth,
        contexts=SimpleNamespace(read=lambda *_: deepcopy(context))),
        SimpleNamespace(resolve=lambda *args, **kwargs: model),
        SimpleNamespace(resolve=lambda _: SimpleNamespace(policy=policy(model.binding), count=lambda *_: 4000)),
        SimpleNamespace(bindings=lambda _: ("source",)), provider, repo, artifacts)
    selection = ScopeDraftSelection(project_id="p", context_id="context", context_artifact_hash=context["metadata"]["artifact_hash"],
        model_config_id="model", budget=budget())
    return app, selection, repo, artifacts, provider, auth, context


def test_model_draft_is_retained_but_does_not_approve_scope():
    app, selection, repo, _, provider, _, _ = setup()
    preview = app.preview(selection)
    assert provider.calls == 0 and not repo.values
    request = ScopeDraftRequest.model_validate(preview["request"])
    value = asyncio.run(app.execute(request, invocation_id="invocation"))
    assert provider.calls == 1 and set(repo.values) == {"reserved", "replied", "draft"}
    assert value["contract"]["authority_basis"] == "model_suggestion" and value["review_required"]
    assert not value["generation_authorized"] and not value["execution_authorized"]
    assert repo.calls[0].purpose == "quality.test_design_scope.draft"
    assert asyncio.run(app.execute(request, invocation_id="invocation")) == value
    assert provider.calls == 1


def test_unknown_call_never_retries_or_becomes_mock_success():
    app, selection, repo, _, provider, _, _ = setup()
    request = ScopeDraftRequest.model_validate(app.preview(selection)["request"])
    provider.fail = True
    with pytest.raises(RuntimeError):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    with pytest.raises(GenerationOutcomeUnknown):
        asyncio.run(app.execute(request, invocation_id="invocation"))
    assert provider.calls == 1 and set(repo.values) == {"reserved", "failed"}


@pytest.mark.parametrize("change", ["oracle", "missing_constraint", "authority", "digest"])
def test_model_cannot_rewrite_oracles_omit_constraints_or_grant_authority(change):
    app, selection, _, artifacts, _, _, _ = setup()
    request = ScopeDraftRequest.model_validate(app.preview(selection)["request"])
    asyncio.run(app.execute(request, invocation_id="invocation"))
    output = json.loads(artifacts.payload["content"])
    if change == "oracle":
        output["contract"]["examples"][0]["positive"]["expected_result"] = "Always pass"
    elif change == "missing_constraint":
        output["contract"]["examples"].pop()
    elif change == "authority":
        output["contract"]["authority_basis"] = "user_confirmed_test_design_scope"
    else:
        output["input_digest"] = acceptance_digest("foreign")
    with pytest.raises(ValueError):
        validate_scope_draft(app._prepare(selection)[1], json.dumps(output))


def test_revoked_sources_hide_historical_drafts():
    app, selection, _, _, _, auth, _ = setup()
    request = ScopeDraftRequest.model_validate(app.preview(selection)["request"])
    asyncio.run(app.execute(request, invocation_id="invocation"))
    auth.revoked = True
    with pytest.raises(PermissionError):
        app.read("p", "invocation")
    with pytest.raises(PermissionError):
        app.history("p", "context")


def test_legacy_scope_request_hash_shape_is_unchanged():
    payload = dict(project_id="p", context_id="context", context_artifact_hash=acceptance_digest("context"),
        expected_previous_revision_id="prior", decision="withdraw", contract=None,
        reason="withdraw", policy_revision="nasus.test-design-scope.v1")
    assert ScopeReviewInput.model_validate(payload).model_dump(mode="json") == payload
