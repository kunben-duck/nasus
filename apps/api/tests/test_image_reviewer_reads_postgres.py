"""Real PG revocations and locks, not model or business-coverage evidence."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from apps.api.app.application.quality_loop.test_design_scope_inputs import ScopeReviewInput
from apps.api.app.domain.quality_loop.test_design_scope import SCOPE_TOOL, TestDesignScopeIntegrityError
from apps.api.app.infrastructure.persistence.context_invalidation_repository import ContextInvalidationRepository
from apps.api.app.infrastructure.persistence.db_models import ProjectRoleBindingRecord, ToolInvocationRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.image_publication_repository import ImagePublicationRepository
from apps.api.app.infrastructure.persistence.test_design_scope_repository import TestDesignScopeRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_http_fixture_actor_reads_postgres import actor_journal


REVIEWERS = (
    pytest.param(TestDesignScopeRepository, id="test-design-scope"),
    pytest.param(ImagePublicationRepository, id="image-publication"),
    pytest.param(ContextInvalidationRepository, id="context-invalidation"),
)


@pytest.mark.parametrize("repository", REVIEWERS)
@pytest.mark.parametrize("revocation", (
    "actor_disabled", "project_role_revoked", "project_role_downgraded", "platform_role_downgraded",
))
def test_reviewer_freshness_refreshes_retained_identities_before_lock(actor_journal, repository, revocation):
    value = actor_journal
    if revocation == "platform_role_downgraded":
        with session_scope() as writer:
            writer.get(UserIdentityRecord, value.actor_id).role = "platform_admin"
            writer.scalar(select(ProjectRoleBindingRecord).where(
                ProjectRoleBindingRecord.user_id == value.actor_id)).role = "developer"
    with session_scope() as reader:
        reader.execute(text("SET LOCAL lock_timeout = '100ms'"))
        assert reader.scalar(text("SHOW transaction_isolation")) == "read committed"
        actor = reader.get(UserIdentityRecord, value.actor_id)
        role = reader.scalar(select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.user_id == value.actor_id))
        original = (actor.status, actor.role, role.status, role.role)
        with session_scope() as writer:
            if revocation == "actor_disabled":
                writer.get(UserIdentityRecord, value.actor_id).status = "disabled"
            elif revocation == "platform_role_downgraded":
                writer.get(UserIdentityRecord, value.actor_id).role = "qa_lead"
            else:
                binding = writer.get(ProjectRoleBindingRecord, role.binding_id)
                if revocation == "project_role_revoked":
                    binding.status = "revoked"
                else:
                    binding.role = "developer"
        # A second SQL query must not reuse these unchanged in-memory facts.
        assert (actor.status, actor.role, role.status, role.role) == original
        with pytest.raises(PermissionError):
            repository._actor(reader, value.scope.project_id, value.actor_id)


@pytest.mark.parametrize("repository", REVIEWERS)
@pytest.mark.parametrize("entity", ("account", "project_role"))
def test_reviewer_retains_original_row_locks_until_transaction_end(actor_journal, repository, entity):
    value = actor_journal
    query = (select(UserIdentityRecord).where(UserIdentityRecord.user_id == value.actor_id) if entity == "account" else
        select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.user_id == value.actor_id))
    with session_scope() as owner:
        repository._actor(owner, value.scope.project_id, value.actor_id)
        with pytest.raises(OperationalError) as raised:
            with session_scope() as competitor:
                competitor.scalar(query.with_for_update(nowait=True))
        assert raised.value.orig.sqlstate == "55P03"
    with session_scope() as competitor:
        assert competitor.scalar(query.with_for_update(nowait=True)) is not None


@pytest.mark.parametrize("repository", REVIEWERS)
@pytest.mark.parametrize("role", ("project_admin", "platform_admin"))
def test_reviewer_accepts_current_original_admin_policy(actor_journal, repository, role):
    value = actor_journal
    if role == "platform_admin":
        with session_scope() as writer:
            writer.get(UserIdentityRecord, value.actor_id).role = role
            writer.scalar(select(ProjectRoleBindingRecord).where(
                ProjectRoleBindingRecord.user_id == value.actor_id)).role = "developer"
    with session_scope() as reader:
        repository._actor(reader, value.scope.project_id, value.actor_id)


@pytest.mark.parametrize("repository", REVIEWERS)
def test_reviewer_preserves_distinct_qa_lead_publication_policy(actor_journal, repository):
    value = actor_journal
    with session_scope() as writer:
        writer.scalar(select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.user_id == value.actor_id)).role = "qa_lead"
    with session_scope() as reader:
        if repository is ImagePublicationRepository:
            with pytest.raises(PermissionError):
                repository._actor(reader, value.scope.project_id, value.actor_id)
        else:
            repository._actor(reader, value.scope.project_id, value.actor_id)


@pytest.fixture
def scope_command(actor_journal):
    value = actor_journal
    request = ScopeReviewInput(project_id=value.scope.project_id, context_id="explicit-command-guard-specimen",
        context_artifact_hash="sha256:" + "a" * 64, expected_previous_revision_id="explicit-previous-scope",
        decision="withdraw", contract=None, reason="Command guard only, not a real scope approval")
    invocation_id = "reviewer-command-" + uuid4().hex
    with session_scope() as writer:
        writer.add(ToolInvocationRecord(id=invocation_id, tool_id=SCOPE_TOOL, status="running", revision=0,
            summary="Explicit command guard protocol specimen", input_payload={**request.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": value.actor_id}))
    try:
        yield value, request, invocation_id
    finally:
        with session_scope() as writer:
            writer.execute(delete(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id))


@pytest.mark.parametrize("change", ("cancelled", "tool_changed", "actor_changed", "request_changed"))
def test_scope_command_freshness_rejects_changes_before_its_original_lock(scope_command, change):
    value, request, invocation_id = scope_command
    with session_scope() as reader:
        reader.execute(text("SET LOCAL lock_timeout = '100ms'"))
        assert reader.scalar(text("SHOW transaction_isolation")) == "read committed"
        held = reader.get(ToolInvocationRecord, invocation_id)
        original = held.status, held.tool_id, deepcopy(held.input_payload)
        with session_scope() as writer:
            command = writer.get(ToolInvocationRecord, invocation_id)
            if change == "cancelled":
                command.status = "cancelled"
            elif change == "tool_changed":
                command.tool_id = "explicit-incorrect-tool"
            else:
                payload = deepcopy(command.input_payload)
                payload["confirmed_actor_id" if change == "actor_changed" else "reason"] = "explicit-changed-value"
                command.input_payload = payload
        assert (held.status, held.tool_id, held.input_payload) == original
        with pytest.raises(TestDesignScopeIntegrityError):
            TestDesignScopeRepository._canonical(reader, request, invocation_id, value.actor_id)


def test_scope_command_preserves_original_lock_and_current_request(scope_command):
    value, request, invocation_id = scope_command
    with session_scope() as owner:
        held = owner.get(ToolInvocationRecord, invocation_id)
        assert TestDesignScopeRepository._canonical(owner, request, invocation_id, value.actor_id) is held
        with pytest.raises(OperationalError) as raised:
            with session_scope() as competitor:
                competitor.scalar(select(ToolInvocationRecord).where(
                    ToolInvocationRecord.id == invocation_id).with_for_update(nowait=True))
        assert raised.value.orig.sqlstate == "55P03"
    with session_scope() as competitor:
        assert competitor.scalar(select(ToolInvocationRecord).where(
            ToolInvocationRecord.id == invocation_id).with_for_update(nowait=True)) is not None
