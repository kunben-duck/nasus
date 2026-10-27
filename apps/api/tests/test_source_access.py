from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.source_access import SourceAccessApplicationService
from apps.api.app.application.system_image.retrieval_scope import AuthorizedRetrievalSubjects, RetrievalSubjectProvenance
from apps.api.app.domain.system_image.source_access import (
    SourceAccessDenied, SourceAccessRule, SourceAccessSnapshot, SourceBindingAccess, StaleSourceAccessScope,
)


def snapshot(epoch=1):
    return SourceAccessSnapshot("project", epoch, (
        SourceBindingAccess("public", "code-public"),
        SourceBindingAccess("private", "code-private", SourceAccessRule("restricted", ("reader",))),
    ))


@pytest.mark.parametrize("role,actor,allowed", [
    ("viewer", "reader", True), ("viewer", "other", False), ("tester", "other", False),
    ("qa_lead", "other", False), ("project_admin", "admin", True), ("platform_admin", "admin", True),
    ("revoked", "reader", False), ("viewer", "", False),
])
def test_source_rules_are_additional_to_current_project_membership(role, actor, allowed):
    scope = snapshot().for_actor(actor, role)
    assert ("private" in scope.binding_ids) == allowed
    if not allowed:
        with pytest.raises(SourceAccessDenied):
            scope.require_binding("private")
    with pytest.raises(SourceAccessDenied):
        scope.require_binding("unknown")


@pytest.mark.parametrize("visibility,readers", [
    ("invalid", ()), ("project", ("user",)), ("restricted", "user"),
    ("restricted", ("",)), ("restricted", (None,)), ("restricted", tuple(str(i) for i in range(129))),
])
def test_invalid_policies_rejected(visibility, readers):
    with pytest.raises(ValueError):
        SourceAccessRule(visibility, readers)


def test_scope_is_stable_but_changes_for_policy_inventory_actor_and_membership():
    rule = SourceAccessRule("restricted", ("b", "a", "a"))
    assert rule.reader_user_ids == ("a", "b")
    original = snapshot()
    scope = original.for_actor("reader", "viewer")
    assert replace(original, bindings=tuple(reversed(original.bindings))).for_actor("reader", "viewer") == scope
    variants = [replace(original, acl_epoch=2), replace(original, bindings=original.bindings[:1]),
                replace(original, bindings=(*original.bindings, SourceBindingAccess("new", "new-source")))]
    assert all(item.for_actor("reader", "viewer").fingerprint != scope.fingerprint for item in variants)
    assert original.for_actor("other", "viewer").fingerprint != scope.fingerprint
    assert original.for_actor("reader", "project_admin").fingerprint != scope.fingerprint
    assert not scope.permits_sources(()) and not scope.permits_sources(("unknown",))


def test_authorization_rechecks_membership_and_rejects_stale_contexts():
    current = snapshot()
    actor = SimpleNamespace(id="reader", role="viewer")
    allowed = True

    class Authorization:
        def current_actor(self):
            return actor

    def load(project_id, actor_id, *, platform_administrator):
        assert project_id == "project" and actor_id == actor.id and not platform_administrator
        return current, actor.role if allowed else None
    app = SourceAccessApplicationService(SimpleNamespace(load_authorized_snapshot=load), Authorization())
    scope = app.scope("project")
    app.require_current(scope)
    current = replace(current, acl_epoch=2)
    with pytest.raises(StaleSourceAccessScope):
        app.require_current(scope)
    actor = SimpleNamespace(id="other", role="viewer")
    with pytest.raises(PlatformApplicationError) as error:
        app.require_binding_access("project", "private")
    assert error.value.status_code == 403
    allowed = False
    with pytest.raises(PlatformApplicationError):
        app.scope("project")


def test_complete_provenance_requires_all_sources_not_any_one_source():
    scope = snapshot().for_actor("other", "viewer")
    subjects = [
        RetrievalSubjectProvenance("project", "context_object:public", ("code-public",), True),
        RetrievalSubjectProvenance("project", "context_object:cross-source", ("code-public", "code-private"), True),
        RetrievalSubjectProvenance("project", "context_object:incomplete", ("code-public",), False),
        RetrievalSubjectProvenance("project", "context_object:unknown", ("unknown",), True),
        RetrievalSubjectProvenance("project", "context_object:legacy", (), True),
    ]
    result = AuthorizedRetrievalSubjects.compile(scope, subjects)
    assert result.subject_refs == ("context_object:public",)
    assert result.scope_fingerprint == scope.fingerprint
    with pytest.raises(ValueError, match="project mismatch"):
        AuthorizedRetrievalSubjects.compile(scope, [replace(subjects[0], project_id="other")])


def test_scope_uses_current_project_role_not_account_role_and_detects_actor_switch():
    actor = SimpleNamespace(id="reader", role="project_admin")
    calls = []
    def load(project_id, actor_id, *, platform_administrator):
        calls.append((project_id, actor_id, platform_administrator))
        return snapshot(), "viewer"
    app = SourceAccessApplicationService(SimpleNamespace(load_authorized_snapshot=load),
        SimpleNamespace(current_actor=lambda: actor))
    assert app.scope("project").effective_project_role == "viewer"
    assert app.scope("project").effective_project_role == "viewer"
    assert calls == [("project", "reader", False)] * 2  # Fresh read, no authorization cache.
    actors = iter((actor, SimpleNamespace(id="other", role="project_admin")))
    app.authorization = SimpleNamespace(current_actor=lambda: next(actors))
    with pytest.raises(StaleSourceAccessScope, match="actor changed"):
        app.scope("project")


@pytest.mark.parametrize("actor_id,role,allowed", [
    ("reader", "viewer", True), ("other", "viewer", False),
    ("other", "tester", False), ("admin", "project_admin", True),
])
def test_whole_project_receipts_require_every_registered_source(actor_id, role, allowed):
    repository = SimpleNamespace(load_authorized_snapshot=lambda *args, **kwargs: (snapshot(), role),
        load_snapshot=lambda project_id: snapshot())
    actor = SimpleNamespace(id=actor_id, role="viewer")
    service = SourceAccessApplicationService(repository, SimpleNamespace(current_actor=lambda: actor))
    if allowed:
        service.require_all_sources_access("project")
    else:
        with pytest.raises(SourceAccessDenied):
            service.require_all_sources_access("project")


def test_whole_project_source_check_rejects_a_policy_change_during_inventory_read():
    current = snapshot()
    actor = SimpleNamespace(id="reader", role="viewer")

    def change_during_read(project_id):
        nonlocal current
        original = current
        current = replace(current, acl_epoch=2)
        return original

    repository = SimpleNamespace(load_authorized_snapshot=lambda *args, **kwargs: (current, "viewer"),
        load_snapshot=change_during_read)
    service = SourceAccessApplicationService(repository, SimpleNamespace(current_actor=lambda: actor))
    with pytest.raises(StaleSourceAccessScope):
        service.require_all_sources_access("project")


def batch_service():
    actor = SimpleNamespace(id="reader", role="viewer")
    values = {ident: (replace(snapshot(), project_id=ident), "viewer") for ident in ("first", "second")}
    calls = []

    def load(project_ids, actor_id, *, platform_administrator):
        calls.append((project_ids, actor_id, platform_administrator))
        return values

    service = SourceAccessApplicationService(SimpleNamespace(load_authorized_snapshots=load),
        SimpleNamespace(current_actor=lambda: actor))
    scopes = tuple(value.for_actor(actor.id, role) for value, role in values.values())
    return service, values, scopes, calls


def test_authorization_batch_rechecks_all_projects_in_one_repository_call():
    service, _, scopes, calls = batch_service()
    service.require_current_many(tuple(reversed(scopes)))
    assert calls == [(('first', 'second'), "reader", False)]
    service.require_current_many(scopes)
    assert len(calls) == 2  # A cohort is an observation, not an authorization cache.
    service.require_current_many(())
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["policy", "inventory", "membership", "role", "project", "missing", "extra"])
def test_authorization_batch_discards_the_whole_cohort_on_any_scope_change(change):
    service, values, scopes, calls = batch_service()
    value, role = values["first"]
    if change == "policy":
        values["first"] = replace(value, acl_epoch=value.acl_epoch + 1), role
    elif change == "inventory":
        values["first"] = replace(value, bindings=value.bindings[:1]), role
    elif change == "membership":
        values["first"] = value, None
    elif change == "role":
        values["first"] = value, "project_admin"
    elif change == "project":
        values["first"] = replace(value, project_id="second"), role
    elif change == "missing":
        del values["first"]
    else:
        values["extra"] = replace(value, project_id="extra"), role
    with pytest.raises(StaleSourceAccessScope):
        service.require_current_many(scopes)
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["different_actor", "actor_during_read", "role_during_read", "duplicate", "oversized"])
def test_authorization_batch_rejects_actor_switch_and_invalid_cohorts(change):
    service, _, scopes, calls = batch_service()
    actor = service.authorization.current_actor()
    if change == "different_actor":
        service.authorization = SimpleNamespace(current_actor=lambda: SimpleNamespace(id="other", role="viewer"))
    elif change in {"actor_during_read", "role_during_read"}:
        changed = SimpleNamespace(id="other" if change == "actor_during_read" else actor.id,
            role="platform_admin" if change == "role_during_read" else actor.role)
        actors = iter((actor, changed))
        service.authorization = SimpleNamespace(current_actor=lambda: next(actors))
    elif change == "duplicate":
        scopes = (scopes[0], scopes[0])
    else:
        scopes = tuple(replace(scopes[0], project_id=f"project-{index}") for index in range(129))
    with pytest.raises(StaleSourceAccessScope):
        service.require_current_many(scopes)
    assert len(calls) == (1 if change in {"actor_during_read", "role_during_read"} else 0)
