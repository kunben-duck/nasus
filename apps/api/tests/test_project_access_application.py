from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.project_access import (
    ConversationAccessScope,
    InvocationAccessScope,
    ProjectAccessApplicationService,
)
from apps.api.app.application.platform.project_models import ProjectRoleBinding
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import (
    AuditEventRecord,
    ConversationRecord,
    ProjectRecord,
    ToolInvocationRecord,
    USWorkItemRecord,
    VersionRecord,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.platform.project_access_read_model import (
    SQLAlchemyProjectAccessReadModel,
)
from apps.api.app.infrastructure.platform.scope_resolution import (
    SQLAlchemyProjectScopeReadModel,
)


def _user(user_id: str, role: str) -> UserProfile:
    return UserProfile(
        id=user_id,
        name=user_id,
        email=f"{user_id}@example.com",
        role=role,
    )


class InMemoryBindings:
    def __init__(self) -> None:
        self.bindings: dict[tuple[str, str], ProjectRoleBinding] = {}

    def upsert(self, binding: ProjectRoleBinding) -> ProjectRoleBinding:
        self.bindings[(binding.project_id, binding.user_id)] = binding
        return binding

    def get_project_binding(self, *, project_id: str, user_id: str) -> ProjectRoleBinding | None:
        return self.bindings.get((project_id, user_id))

    def list_for_user(self, user_id: str) -> list[ProjectRoleBinding]:
        return [binding for binding in self.bindings.values() if binding.user_id == user_id]

    def list_for_project(self, project_id: str) -> list[ProjectRoleBinding]:
        return [
            binding
            for binding in self.bindings.values()
            if binding.project_id == project_id and binding.status == "active"
        ]


class InMemoryAccessFacts:
    def __init__(self) -> None:
        self.projects = {"project-1", "project-2"}
        self.conversations = {
            "conversation-1": ConversationAccessScope("conversation-1", "project-1", "member-1")
        }
        self.invocations = {
            "invocation-1": InvocationAccessScope(
                "invocation-1",
                "conversation-1",
                {"version_id": "version-1"},
                (),
            )
        }
        self.created_by = {("invocation-denied", "member-1")}

    def project_exists(self, project_id: str) -> bool:
        return project_id in self.projects

    def list_project_ids(self) -> set[str]:
        return set(self.projects)

    def conversation_scope(self, conversation_id: str):
        return self.conversations.get(conversation_id)

    def invocation_scope(self, invocation_id: str):
        return self.invocations.get(invocation_id)

    def project_id_for_version(self, version_id: str) -> str | None:
        return "project-1" if version_id == "version-1" else None

    def project_id_for_us(self, us_id: str) -> str | None:
        return "project-2" if us_id == "us-2" else None

    def invocation_created_by(self, invocation_id: str, user_id: str) -> bool:
        return (invocation_id, user_id) in self.created_by


def _service(actor: UserProfile):
    bindings = InMemoryBindings()
    facts = InMemoryAccessFacts()
    return ProjectAccessApplicationService(bindings, facts, lambda: actor), bindings, facts


def test_platform_admin_reads_durable_project_catalog_and_missing_projects_fail_closed() -> None:
    service, _bindings, _facts = _service(_user("admin-1", "platform_admin"))

    assert service.visible_project_ids() == {"project-1", "project-2"}
    assert service.require_project_access("project-1") is None
    assert service.can_access_project("missing") is False
    with pytest.raises(KeyError):
        service.require_project_access("missing")


def test_project_binding_controls_effective_role_without_store_state() -> None:
    member = _user("member-1", "viewer")
    service, _bindings, _facts = _service(member)

    binding = service.grant_role(
        project_id="project-1",
        user_id=member.id,
        role="qa_lead",
        created_by="admin-1",
    )

    assert service.visible_project_ids() == {"project-1"}
    assert service.require_project_access("project-1") == binding
    assert service.effective_user_for_project("project-1").role == "qa_lead"
    with pytest.raises(PlatformApplicationError) as denied:
        service.require_project_access("project-2")
    assert denied.value.code == "project_access_denied"


def test_project_administrator_can_manage_members_without_platform_privileges() -> None:
    administrator = _user("admin-1", "qa_lead")
    service, _bindings, _facts = _service(administrator)
    service.grant_role(
        project_id="project-1",
        user_id=administrator.id,
        role="project_admin",
        created_by="platform-admin",
    )

    member = service.assign_project_member(
        project_id="project-1",
        user_id="member-2",
        role="tester",
        actor=administrator,
    )

    assert member.role == "tester"
    assert {item.user_id for item in service.list_project_members("project-1", administrator)} == {
        "admin-1",
        "member-2",
    }
    revoked = service.revoke_project_member(
        project_id="project-1",
        user_id="member-2",
        actor=administrator,
    )
    assert revoked.status == "revoked"


def test_project_member_management_rejects_non_admin_and_last_admin_revocation() -> None:
    member = _user("member-1", "tester")
    service, _bindings, _facts = _service(member)
    service.grant_role(
        project_id="project-1",
        user_id=member.id,
        role="tester",
        created_by="admin-1",
    )

    with pytest.raises(PlatformApplicationError) as denied:
        service.assign_project_member(
            project_id="project-1",
            user_id="member-2",
            role="viewer",
            actor=member,
        )
    assert denied.value.code == "project_admin_required"

    administrator = _user("admin-1", "qa_lead")
    service.grant_role(
        project_id="project-1",
        user_id=administrator.id,
        role="project_admin",
        created_by="platform-admin",
    )
    with pytest.raises(PlatformApplicationError) as last_admin:
        service.revoke_project_member(
            project_id="project-1",
            user_id=administrator.id,
            actor=administrator,
        )
    assert last_admin.value.code == "last_project_admin_required"

    with pytest.raises(PlatformApplicationError) as last_admin_demotion:
        service.assign_project_member(
            project_id="project-1",
            user_id=administrator.id,
            role="qa_lead",
            actor=administrator,
        )
    assert last_admin_demotion.value.code == "last_project_admin_required"


def test_conversation_invocation_and_audit_access_use_durable_scope_facts() -> None:
    member = _user("member-1", "tester")
    service, _bindings, facts = _service(member)
    service.grant_role(
        project_id="project-1",
        user_id=member.id,
        role="tester",
        created_by="admin-1",
    )
    invocation = facts.invocations["invocation-1"]

    assert service.can_access_conversation(facts.conversations["conversation-1"])
    assert service.project_id_for_invocation(invocation) == "project-1"
    assert service.can_access_invocation(invocation)
    assert service.can_access_audit_event(
        SimpleNamespace(
            tool_invocation_id="invocation-1",
            conversation_id=None,
            object_refs=[],
            actor="system",
        )
    )


def test_sqlalchemy_access_read_model_queries_authorization_facts_by_id() -> None:
    init_database()
    suffix = "project_access_adapter"
    ids = {
        "project": f"project-{suffix}",
        "version": f"version-{suffix}",
        "us": f"us-{suffix}",
        "conversation": f"conversation-{suffix}",
        "invocation": f"invocation-{suffix}",
        "event": f"event-{suffix}",
    }
    try:
        with session_scope() as session:
            session.add(
                ProjectRecord(
                    id=ids["project"],
                    name="Access project",
                    code="ACC",
                    summary="Authorization fixture",
                )
            )
            session.add(
                VersionRecord(
                    id=ids["version"],
                    project_id=ids["project"],
                    name="V1",
                    branch_name="release/v1",
                )
            )
            session.add(
                USWorkItemRecord(
                    id=ids["us"],
                    project_id=ids["project"],
                    title="Authorization",
                    owner="QA",
                )
            )
            session.add(
                ConversationRecord(
                    id=ids["conversation"],
                    session_id=f"session-{suffix}",
                    title="Access conversation",
                    space_type="project",
                    space_id=ids["project"],
                    project_id=ids["project"],
                    initiator_id="member-1",
                )
            )
            session.add(
                ToolInvocationRecord(
                    id=ids["invocation"],
                    conversation_id=ids["conversation"],
                    tool_id="project.get",
                    summary="Read project",
                    input_payload={"version_id": ids["version"]},
                    result_payload={"object_refs": [f"project:{ids['project']}"]},
                )
            )
            session.add(
                AuditEventRecord(
                    id=ids["event"],
                    occurred_at="2026-08-08T00:00:00+00:00",
                    actor="member-1",
                    action="tool.invocation.created",
                    entity_type="tool_invocation",
                    entity_id=ids["invocation"],
                    summary="Created",
                    tool_invocation_id=ids["invocation"],
                )
            )

        read_model = SQLAlchemyProjectAccessReadModel()
        scope_read_model = SQLAlchemyProjectScopeReadModel()

        assert read_model.project_exists(ids["project"])
        assert ids["project"] in read_model.list_project_ids()
        assert read_model.project_id_for_version(ids["version"]) == ids["project"]
        assert read_model.project_id_for_us(ids["us"]) == ids["project"]
        assert read_model.conversation_scope(ids["conversation"]).project_id == ids["project"]
        assert read_model.invocation_scope(ids["invocation"]).object_refs == (
            f"project:{ids['project']}",
        )
        assert read_model.invocation_created_by(ids["invocation"], "member-1")
        assert scope_read_model.project_id_for_version(ids["version"]) == ids["project"]
        assert scope_read_model.project_id_for_us(ids["us"]) == ids["project"]
        assert scope_read_model.first_version_id(ids["project"]) == ids["version"]
    finally:
        with session_scope() as session:
            session.execute(delete(AuditEventRecord).where(AuditEventRecord.id == ids["event"]))
            session.execute(
                delete(ToolInvocationRecord).where(ToolInvocationRecord.id == ids["invocation"])
            )
            session.execute(
                delete(ConversationRecord).where(ConversationRecord.id == ids["conversation"])
            )
            session.execute(delete(USWorkItemRecord).where(USWorkItemRecord.id == ids["us"]))
            session.execute(delete(VersionRecord).where(VersionRecord.id == ids["version"]))
            session.execute(delete(ProjectRecord).where(ProjectRecord.id == ids["project"]))
