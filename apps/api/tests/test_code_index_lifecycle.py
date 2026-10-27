from dataclasses import replace

import pytest
from pydantic import ValidationError

from apps.api.app.application.system_image.code_index_lifecycle import (
    CodeIndexLifecycleApplicationService, CodeIndexListInput, CodeIndexListPage,
    CodeIndexStatusInput, CodeIndexCancelInput,
)
from apps.api.app.domain.system_image.code_index_generation import CodeIndexGenerationPin, CodeIndexGenerationStatus, CodeIndexLeaseLost
from apps.api.app.domain.system_image.source_access import SourceAccessSnapshot, SourceBindingAccess, SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def pin():
    data = dict(generation_id="cgen-one", project_id="project", binding_id="binding", source_revision_id="source-revision",
        source_manifest_hash="sha256:" + "1" * 64, snapshot_hash="sha256:" + "2" * 64,
        provider_fingerprint="sha256:" + "3" * 64, invocation_id="original")
    return CodeIndexGenerationPin(**data, content_hash=snapshot_digest(data))


class Authorization:
    def __init__(self, role="project_admin", allowed=True):
        self.value = SourceAccessSnapshot("project", 1, (SourceBindingAccess("binding", "source"),) if allowed else ()).for_actor("actor", role)
        self.changed = False

    def scope(self, project_id):
        assert project_id == "project"
        return self.value

    def require_current(self, scope):
        if self.changed:
            raise StaleSourceAccessScope("source changed")
        assert scope == self.value


class Repository:
    def __init__(self):
        self.pin = pin()
        self.reads, self.cancels = 0, 0

    def get(self, project_id, generation_id):
        self.reads += 1
        return self.pin

    def status(self, selected):
        assert selected == self.pin
        return CodeIndexGenerationStatus(selected, "idle", 1, "none", "running", "2026-10-07T00:00:00+00:00")

    def list(self, request):
        return CodeIndexListPage(request, (self.pin,), None)

    def cancel_confirmed(self, selected, *, invocation_id, require_current):
        require_current()
        assert invocation_id == "independent"
        self.cancels += 1
        return "cancelled", replace(self.status(selected), state="cancelled")


def test_status_and_discovery_are_provider_free_and_source_scoped():
    repo, access = Repository(), Authorization()
    app = CodeIndexLifecycleApplicationService(repo, access)
    assert app.list(CodeIndexListInput(project_id="project", binding_id="binding")).items == (repo.pin,)
    status = app.read(CodeIndexStatusInput(project_id="project", generation_id="cgen-one")).status
    assert status.entity_count is None and status.protocol is None and status.worker_state == "none"
    assert repo.cancels == 0
    access.changed = True
    with pytest.raises(StaleSourceAccessScope):
        app.read(CodeIndexStatusInput(project_id="project", generation_id="cgen-one"))


def test_legacy_status_receipt_remains_readable_without_cancellation_authority():
    from dataclasses import asdict
    from apps.api.app.application.platform.tool_models import ToolResult
    value = {"invocation_id": "query", "status": "completed", "summary": "Historical index observation",
        "code_index": {"request": {"project_id": "project", "generation_id": "cgen-one"},
            "status": asdict(Repository().status(pin()))}}
    restored = ToolResult.model_validate(value)
    assert restored.code_index.can_cancel is False
    assert restored.code_index.status.pin == pin()
    assert "can_cancel" not in value["code_index"]


@pytest.mark.parametrize("operation", ["list", "read", "cancel"])
def test_denied_binding_never_returns_metadata_or_mutates(operation):
    repo = Repository()
    app = CodeIndexLifecycleApplicationService(repo, Authorization(allowed=False))
    with pytest.raises(SourceAccessDenied):
        if operation == "list":
            app.list(CodeIndexListInput(project_id="project", binding_id="binding"))
        elif operation == "read":
            app.read(CodeIndexStatusInput(project_id="project", generation_id="cgen-one"))
        else:
            app.cancel(CodeIndexCancelInput(project_id="project", generation_id="cgen-one", expected_generation_hash=repo.pin.content_hash), invocation_id="independent")
    assert repo.cancels == 0


@pytest.mark.parametrize("role", ["viewer", "tester"])
def test_source_read_permission_does_not_grant_cancellation(role):
    repo = Repository()
    app = CodeIndexLifecycleApplicationService(repo, Authorization(role=role))
    assert app.read(CodeIndexStatusInput(project_id="project", generation_id="cgen-one")).status.pin == repo.pin
    assert app.read(CodeIndexStatusInput(project_id="project", generation_id="cgen-one")).can_cancel is False
    with pytest.raises(SourceAccessDenied):
        app.cancel(CodeIndexCancelInput(project_id="project", generation_id="cgen-one", expected_generation_hash=repo.pin.content_hash), invocation_id="independent")
    assert repo.cancels == 0


@pytest.mark.parametrize("role", ["qa_lead", "project_admin", "platform_admin"])
@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled"])
def test_cancel_control_requires_current_reviewer_and_nonterminal_command(role, status):
    repo = Repository()
    observed = replace(repo.status(repo.pin), invocation_status=status)
    repo.status = lambda selected: observed
    app = CodeIndexLifecycleApplicationService(repo, Authorization(role=role))
    assert app.read(CodeIndexStatusInput(project_id="project", generation_id="cgen-one")).can_cancel is (status == "running")
    assert repo.cancels == 0


def test_cancellation_requires_exact_generation_hash():
    repo = Repository()
    app = CodeIndexLifecycleApplicationService(repo, Authorization())
    with pytest.raises(CodeIndexLeaseLost, match="pin changed"):
        app.cancel(CodeIndexCancelInput(project_id="project", generation_id="cgen-one", expected_generation_hash="sha256:" + "4" * 64), invocation_id="independent")
    result = app.cancel(CodeIndexCancelInput(project_id="project", generation_id="cgen-one", expected_generation_hash=repo.pin.content_hash), invocation_id="independent")
    assert result.outcome == "cancelled" and result.status.state == "cancelled" and repo.cancels == 1


@pytest.mark.parametrize("changes", [{"limit": True}, {"limit": 31}, {"limit": "10"}, {"after_id": "x" * 129}, {"execute_repository": True}])
def test_discovery_input_has_strict_finite_bounds(changes):
    with pytest.raises(ValidationError):
        CodeIndexListInput(project_id="project", binding_id="binding", **changes)


@pytest.mark.parametrize("changes", [{"state": "ready"}, {"worker_state": "active"}, {"projection_hash": "sha256:" + "4" * 64}, {"epoch": True}])
def test_status_does_not_fabricate_prepared_workers_or_counts(changes):
    with pytest.raises((CodeIndexLeaseLost, ValueError)):
        replace(Repository().status(pin()), **changes)


def test_resource_policy_uses_the_supplied_actor_and_never_queries_provider_status():
    from apps.api.app.application.platform.account_models import UserProfile
    from apps.api.app.application.platform.actor_context import current_actor
    from apps.api.app.application.platform.tool_code_indexes import CodeIndexInvocationResourcePolicy
    from apps.api.app.application.platform.tool_models import ToolInvocation
    seen = []
    class Owner:
        def require_receipt_access(self, request):
            seen.append((current_actor().user.id, request.generation_id))
    policy = CodeIndexInvocationResourcePolicy(Owner())
    actor = UserProfile(id="explicit", name="Reader", email="reader@example.com", role="viewer")
    invocation = ToolInvocation(id="query", tool_id="query.system_image.code_indexes.status", status="completed",
        summary="checked", input_payload={"project_id": "project", "generation_id": "cgen-one"})
    assert policy.can_access(invocation, actor) and seen == [("explicit", "cgen-one")]
    public = policy.broadcast_view(invocation)
    assert public.input_payload == {} and invocation.input_payload["generation_id"] == "cgen-one"
    unrelated = invocation.model_copy(update={"tool_id": "project.create"})
    assert policy.can_access(unrelated, actor) and policy.broadcast_view(unrelated) is unrelated
    assert seen == [("explicit", "cgen-one")]


@pytest.mark.parametrize("error", [SourceAccessDenied("private"), StaleSourceAccessScope("changed"), KeyError("missing")])
def test_resource_policy_fails_closed_on_denied_stale_or_missing_receipt(error):
    from apps.api.app.application.platform.account_models import UserProfile
    from apps.api.app.application.platform.tool_code_indexes import CodeIndexInvocationResourcePolicy
    from apps.api.app.application.platform.tool_models import ToolInvocation
    class Owner:
        def require_receipt_access(self, request):
            raise error
    invocation = ToolInvocation(id="query", tool_id="query.system_image.code_indexes.status", status="completed",
        summary="checked", input_payload={"project_id": "project", "generation_id": "cgen-one"})
    assert not CodeIndexInvocationResourcePolicy(Owner()).can_access(invocation,
        UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer"))
