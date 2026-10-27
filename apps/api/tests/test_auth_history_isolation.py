"""Account flow tests must not erase immutable system-image actor history."""
from sqlalchemy import select

from apps.api.app.infrastructure.persistence.db_models import (
    AccessSessionRecord, ProjectRoleBindingRecord, UserIdentityRecord,
)
from apps.api.app.infrastructure.persistence.investigation_models import InvestigationRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_investigation_api import investigation, investigate, read
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_api import (
    test_email_registration_login_and_logout_session_flow as registration_flow,
    test_request_actor_and_project_membership_isolate_users_end_to_end as membership_flow,
)


def test_existing_build_actor_membership_session_and_revision_survive_both_auth_flows(investigation):
    value = investigation
    command = investigate(value)
    assert command["status"] == "completed", command
    revision_id = command["result"]["investigation"]["revision_id"]
    saved = read(value, revision_id).json()
    actor_id = value["owner"]["id"]
    with session_scope() as session:
        actor = session.get(UserIdentityRecord, actor_id)
        actor_pin = (actor.email, actor.display_name, actor.role, actor.status)
        sessions = set(session.scalars(select(AccessSessionRecord.session_id).where(AccessSessionRecord.user_id == actor_id)))
        bindings = set(session.scalars(select(ProjectRoleBindingRecord.binding_id).where(ProjectRoleBindingRecord.user_id == actor_id)))
        revision = session.get(InvestigationRevisionRecord, revision_id)
        assert revision.created_by == actor_id and sessions and bindings
        revision_hash = revision.revision_hash
    registration_flow()
    membership_flow()
    with session_scope() as session:
        actor = session.get(UserIdentityRecord, actor_id)
        assert (actor.email, actor.display_name, actor.role, actor.status) == actor_pin
        assert sessions.issubset(set(session.scalars(select(AccessSessionRecord.session_id).where(AccessSessionRecord.user_id == actor_id))))
        assert bindings.issubset(set(session.scalars(select(ProjectRoleBindingRecord.binding_id).where(ProjectRoleBindingRecord.user_id == actor_id))))
        revision = session.get(InvestigationRevisionRecord, revision_id)
        assert revision.created_by == actor_id and revision.revision_hash == revision_hash
    assert read(value, revision_id).json() == saved
