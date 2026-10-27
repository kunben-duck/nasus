from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope, current_actor
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.project_access import InvocationAccessScope
from apps.api.app.application.platform.tool_case_approvals import CaseApprovalInvocationResourcePolicy
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.case_approval import CASE_APPROVAL_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_case_approvals import admission_ports


def policy_ports():
    _, request, _ = admission_ports()
    checked = []
    def verify(selection):
        checked.append((selection, current_actor().user.id))
    application = SimpleNamespace(require_access=verify,
        read=lambda project, ident: {"revision": {"invocation_id": "command",
            "request_hash": acceptance_digest(request.model_dump(mode="json"))}})
    previous = SimpleNamespace(applies=lambda *_: False, can_access=lambda *_: True, broadcast_view=lambda value: value)
    command = ToolInvocation(id="command", tool_id=CASE_APPROVAL_TOOL, status="completed", summary="Opaque original admission",
        input_payload=request.model_dump(mode="json"), result=ToolResult(invocation_id="command", status="completed", summary="Recorded",
            object_refs=["test_design_case_approval:revision"]), idempotency_key="private-attempt")
    actor = UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer")
    return CaseApprovalInvocationResourcePolicy(application, previous), command, actor, checked


@pytest.mark.parametrize("scope_only", [False, True])
def test_admission_authorization_uses_current_actor_and_original_resource(scope_only):
    policy, command, actor, checked = policy_ports()
    if scope_only:
        command = InvocationAccessScope(id=command.id, conversation_id=None, input_payload=command.input_payload,
            object_refs=tuple(command.result.object_refs), tool_id=command.tool_id, status=command.status, result=command.result)
    parent = actor.model_copy(update={"id": "parent"})
    with actor_scope(parent):
        assert policy.can_access(command, actor)
        assert current_actor().user.id == "parent"
    assert checked[0][1] == "reader"


@pytest.mark.parametrize("fault,expected", [(SourceAccessDenied("withdrawn"), None), (KeyError("missing"), None),
    (ValueError("bad receipt"), 502), (RuntimeError("verification offline"), 503)])
def test_resource_policy_does_not_hide_corruption_or_unavailable_verification(fault, expected):
    policy, command, actor, _ = policy_ports()
    def fail(_):
        raise fault
    policy.application.require_access = fail
    if expected is None:
        assert not policy.can_access(command, actor)
    else:
        with pytest.raises(PlatformApplicationError) as result:
            policy.can_access(command, actor)
        assert result.value.status_code == expected


@pytest.mark.parametrize("fault", ["no_result", "wrong_invocation", "wrong_kind", "extra_ref", "wrong_original_request"])
def test_completed_admission_receipt_cannot_substitute_resource(fault):
    policy, command, actor, _ = policy_ports()
    if fault == "no_result": command.result = None
    elif fault == "wrong_invocation": command.result.invocation_id = "another"
    elif fault == "wrong_kind": command.result.object_refs = ["test_design_mapping:revision"]
    elif fault == "extra_ref": command.result.object_refs.append("test_design_case_approval:another")
    else: policy.application.read = lambda *_: {"revision": {"invocation_id": command.id, "request_hash": acceptance_digest("another")}}
    with pytest.raises(PlatformApplicationError) as result:
        policy.can_access(command, actor)
    assert result.value.status_code == 502


def test_broadcast_scrubs_admission_selection_and_private_idempotency():
    policy, command, _, _ = policy_ports()
    original = command.model_dump(mode="json")
    value = policy.broadcast_view(command)
    assert value.input_payload == {} and value.result is None and value.idempotency_key is None
    assert command.model_dump(mode="json") == original
    assert policy.broadcast_view(command.model_copy(update={"tool_id": "another"})).input_payload == command.input_payload


def test_denied_command_remains_readable_only_after_current_source_verification():
    policy, command, actor, checked = policy_ports()
    command.status = "failed"
    command.input_payload["authorization_denied"] = True
    command.input_payload["authorization_required_roles"] = ["qa_lead"]
    command.input_payload["authorization_user_role"] = "qa_engineer"
    command.result = ToolResult(invocation_id=command.id, status="failed", summary="Access denied", followup_reason="authorization_denied")
    assert policy.can_access(command, actor) and checked
    def deny(_):
        raise SourceAccessDenied("current source withdrawn")
    policy.application.require_access = deny
    assert not policy.can_access(command, actor)


def test_denial_marker_cannot_be_added_to_completed_or_pending_command():
    policy, command, actor, _ = policy_ports()
    command.input_payload["authorization_denied"] = True
    with pytest.raises(PlatformApplicationError) as error:
        policy.can_access(command, actor)
    assert error.value.status_code == 502
    command.status = "waiting_confirmation"
    assert not policy.can_access(command, actor)
