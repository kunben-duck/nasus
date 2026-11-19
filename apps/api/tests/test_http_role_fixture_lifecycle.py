"""Journal/native port specimens only; no target registration or business tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from threading import Event, Lock

import pytest

from apps.api.app.application.quality_loop.http_role_credentials import (
    HttpRoleCredential, HttpRoleCredentialAccessDenied, HttpRoleFixtureLifecycleService, HttpRoleFixtureOutcomeUnknown,
    HttpRoleResourceBinding, NativeHttpRoleFixtureResult,
)
from apps.api.app.domain.quality_loop.http_role_fixtures import HttpRoleFixtureInvalid
from apps.api.tests.test_http_role_credentials import AUTHOR_SECRET, NOW, SCOPE, assert_redacted, credential_service
from apps.api.tests.test_http_role_fixtures_v2 import role_manifest


class Journal:
    def __init__(self):
        self.records, self.lock = {}, Lock()
        self.fail_complete = self.fail_claim = self.fail_inspect = False

    @staticmethod
    def key(scope, phase):
        return scope.project_id, scope.batch_id, scope.case_id, phase

    def inspect(self, scope, phase):
        if self.fail_inspect: raise RuntimeError(AUTHOR_SECRET)
        return self.records.get(self.key(scope, phase))

    def claim(self, record, *, require_current):
        with self.lock:
            require_current()
            key = self.key(record.scope, record.phase)
            if key in self.records: raise RuntimeError(AUTHOR_SECRET)
            self.records[key] = record
            if self.fail_claim: raise RuntimeError(AUTHOR_SECRET)

    def complete(self, record, *, require_current):
        with self.lock:
            require_current()
            key = self.key(record.scope, record.phase)
            assert self.records[key] == replace(record, result=None)
            if self.fail_complete: raise RuntimeError(AUTHOR_SECRET)
            self.records[key] = record


class NativeAdapter:
    """A side-effect counter only, not a native target implementation."""
    def __init__(self):
        self.calls = []
        self.failure = None
        self.after_write = lambda: None
        self.result = NativeHttpRoleFixtureResult("succeeded", "sha256:" + "c" * 64,
                                                  (HttpRoleResourceBinding("article", "original-article"),))

    def validate_recipes(self, manifest):
        assert all(item["recipe_id"] == "article.v1" for item in manifest["resource_bindings"].values())

    def setup(self, scope, manifest, *, credentials, require_current):
        require_current()
        self.calls.append(("setup", scope, deepcopy(manifest)))
        self.after_write()
        if self.failure: raise self.failure
        require_current()
        return self.result

    def cleanup(self, scope, manifest, prepared, *, credentials, require_current):
        require_current()
        self.calls.append(("cleanup", scope, deepcopy(manifest), prepared))
        self.after_write()
        if self.failure: raise self.failure
        require_current()
        return replace(self.result, resources=prepared.resources)


def lifecycle():
    credentials, _, backend, authority, clock = credential_service()
    native, journal = NativeAdapter(), Journal()
    app = HttpRoleFixtureLifecycleService(credentials, native, journal)
    return app, credentials, native, journal, backend, authority, clock


def test_exact_original_resources_and_result_replay_without_native_resend():
    app, credentials, native, journal, _, _, _ = lifecycle()
    original = role_manifest()
    prepared = app.prepare(SCOPE, original)
    cleaned = app.cleanup(SCOPE, original)
    assert prepared.status == cleaned.status == "succeeded"
    assert native.calls[-1][-1].resources == (HttpRoleResourceBinding("article", "original-article"),)
    restarted = HttpRoleFixtureLifecycleService(credentials, native, journal)
    assert restarted.prepare(SCOPE, original) == prepared
    assert restarted.cleanup(SCOPE, original) == cleaned
    assert len(native.calls) == 2 and original == role_manifest()
    assert "original-article" not in repr([prepared, cleaned, list(journal.records.values())])


@pytest.mark.parametrize("phase", ["setup", "cleanup"])
@pytest.mark.parametrize("failure", ["transport", "commit", "claim", "unknown", "bad_result", "revocation"])
def test_unknown_writes_are_not_resent_after_restart(phase, failure):
    app, credentials, native, journal, _, authority, _ = lifecycle()
    if phase == "cleanup": app.prepare(SCOPE, role_manifest())
    if failure == "transport": native.failure = TimeoutError(AUTHOR_SECRET)
    if failure == "commit": journal.fail_complete = True
    if failure == "claim": journal.fail_claim = True
    if failure == "unknown": native.result = replace(native.result, status="unknown")
    if failure == "bad_result": native.result = {"token": AUTHOR_SECRET}
    if failure == "revocation": native.after_write = lambda: setattr(authority, "allowed", False)
    operation = app.prepare if phase == "setup" else app.cleanup
    with pytest.raises(HttpRoleFixtureOutcomeUnknown) as caught: operation(SCOPE, role_manifest())
    assert_redacted(caught.value)
    count = len(native.calls)
    native.failure, journal.fail_complete, journal.fail_claim, authority.allowed = None, False, False, True
    restarted = HttpRoleFixtureLifecycleService(credentials, native, journal)
    operation = restarted.prepare if phase == "setup" else restarted.cleanup
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): operation(SCOPE, role_manifest())
    assert len(native.calls) == count


def test_unknown_setup_cannot_be_cleaned_by_guessing_resources():
    app, _, native, _, _, _, _ = lifecycle()
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.cleanup(SCOPE, role_manifest())
    native.failure = TimeoutError(AUTHOR_SECRET)
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.prepare(SCOPE, role_manifest())
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.cleanup(SCOPE, role_manifest())
    assert len(native.calls) == 1


@pytest.mark.parametrize("field,value", [("version_id", "new-version"), ("environment_id", "new-env"),
                                         ("environment_epoch", 2), ("inventory_hash", "sha256:" + "b" * 64),
                                         ("expires_at", (NOW + timedelta(hours=1)).isoformat())])
def test_same_batch_case_cannot_rebind_scope_to_evade_unknown_claim(field, value):
    app, _, native, _, _, authority, _ = lifecycle()
    native.failure = TimeoutError(AUTHOR_SECRET)
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.prepare(SCOPE, role_manifest())
    authority.scope = replace(SCOPE, **{field: value})
    with pytest.raises(HttpRoleFixtureInvalid): app.prepare(authority.scope, role_manifest())
    assert len(native.calls) == 1


def test_manifest_change_cannot_evade_original_claim_even_with_fresh_authority():
    app, _, native, _, _, authority, _ = lifecycle()
    native.failure = TimeoutError(AUTHOR_SECRET)
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.prepare(SCOPE, role_manifest())
    changed = role_manifest()
    changed["roles"]["author"]["credential_ref"] = "credential:" + "9" * 32
    authority.manifest = changed
    with pytest.raises(HttpRoleFixtureInvalid): app.prepare(SCOPE, changed)
    assert len(native.calls) == 1


def test_current_lease_and_independent_confirmation_required_even_for_saved_results():
    app, _, native, journal, _, authority, _ = lifecycle()
    authority.confirmed.remove("fixture_setup")
    with pytest.raises(HttpRoleCredentialAccessDenied): app.prepare(SCOPE, role_manifest())
    assert not native.calls and not journal.records
    authority.confirmed.add("fixture_setup")
    app.prepare(SCOPE, role_manifest())
    authority.confirmed.remove("fixture_cleanup")
    with pytest.raises(HttpRoleCredentialAccessDenied): app.cleanup(SCOPE, role_manifest())
    authority.allowed = False
    with pytest.raises(HttpRoleCredentialAccessDenied): app.prepare(SCOPE, role_manifest())
    assert len(native.calls) == 1


def test_cleanup_confirmation_does_not_reauthorize_setup_dispatch():
    app, _, native, _, _, authority, _ = lifecycle()
    app.prepare(SCOPE, role_manifest())
    authority.confirmed.remove("fixture_setup")
    assert app.cleanup(SCOPE, role_manifest()).status == "succeeded"
    assert len(native.calls) == 2


def test_unsupported_native_recipe_and_unreadable_journal_never_dispatch():
    app, _, native, journal, _, authority, _ = lifecycle()
    changed = role_manifest()
    changed["resource_bindings"]["article"]["recipe_id"] = "unregistered.v1"
    authority.manifest = changed
    with pytest.raises(HttpRoleFixtureInvalid): app.prepare(SCOPE, changed)
    authority.manifest = role_manifest()
    journal.fail_inspect = True
    with pytest.raises(HttpRoleFixtureOutcomeUnknown) as caught: app.prepare(SCOPE, role_manifest())
    assert_redacted(caught.value)
    assert not native.calls and not journal.records


def test_failed_original_result_stays_failed_and_cleanup_uses_only_known_resources():
    app, _, native, _, _, _, _ = lifecycle()
    native.result = replace(native.result, status="failed")
    assert app.prepare(SCOPE, role_manifest()).status == "failed"
    native.result = replace(native.result, status="succeeded")
    assert app.prepare(SCOPE, role_manifest()).status == "failed"
    assert app.cleanup(SCOPE, role_manifest()).status == "succeeded"
    assert len(native.calls) == 2


@pytest.mark.parametrize("resources", [(), (HttpRoleResourceBinding("foreign", "id"),),
                                       (HttpRoleResourceBinding("article", "https://foreign.example"),),
                                       (HttpRoleResourceBinding("article", "id"), HttpRoleResourceBinding("article", "id2"))])
def test_invalid_native_result_reserves_phase_without_leaking_or_redispatch(resources):
    app, _, native, _, _, _, _ = lifecycle()
    native.result = replace(native.result, resources=resources)
    for _ in range(2):
        with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.prepare(SCOPE, role_manifest())
    assert len(native.calls) == 1


def test_forged_cleanup_resource_cannot_replace_original_native_binding():
    app, _, _, journal, _, _, _ = lifecycle()
    app.prepare(SCOPE, role_manifest())
    result = app.cleanup(SCOPE, role_manifest())
    key = journal.key(SCOPE, "cleanup")
    journal.records[key] = replace(journal.records[key], result=replace(result,
        resources=(HttpRoleResourceBinding("article", "foreign-article"),)))
    with pytest.raises(HttpRoleFixtureInvalid): app.cleanup(SCOPE, role_manifest())


def test_concurrent_reserved_phase_is_unknown_and_dispatches_only_once():
    app, _, native, _, _, _, _ = lifecycle()
    entered, release = Event(), Event()
    def wait_after_write():
        entered.set()
        assert release.wait(5)
    native.after_write = wait_after_write
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(app.prepare, SCOPE, role_manifest())
        try:
            assert entered.wait(5)
            with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.prepare(SCOPE, role_manifest())
        finally:
            release.set()
        assert first.result().status == "succeeded"
    assert len(native.calls) == 1


def test_lost_completion_acknowledgement_reads_original_without_resending():
    app, _, native, journal, _, _, _ = lifecycle()
    complete = journal.complete
    def lost_ack(record, *, require_current):
        complete(record, require_current=require_current)
        raise TimeoutError(AUTHOR_SECRET)
    journal.complete = lost_ack
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.prepare(SCOPE, role_manifest())
    assert app.prepare(SCOPE, role_manifest()).status == "succeeded"
    assert len(native.calls) == 1


def test_boolean_allowlist_denial_is_not_treated_as_permission():
    app, _, native, journal, _, _, _ = lifecycle()
    native.validate_recipes = lambda manifest: False
    with pytest.raises(HttpRoleFixtureInvalid): app.prepare(SCOPE, role_manifest())
    assert not native.calls and not journal.records


def test_native_port_private_handoff_never_places_credentials_in_journal():
    app, credentials, native, journal, backend, _, _ = lifecycle()
    setup = native.setup
    def private_setup(scope, manifest, *, credentials, require_current):
        credentials.store(scope, manifest, "author", HttpRoleCredential("token", token=AUTHOR_SECRET))
        assert credentials.resolve(scope, manifest, "author").credential.token == AUTHOR_SECRET
        assert credentials.resolve(scope, manifest, "anonymous").credential is None
        return setup(scope, manifest, credentials=credentials, require_current=require_current)
    native.setup = private_setup
    result = app.prepare(SCOPE, role_manifest())
    assert result.status == "succeeded" and len(backend.values) == 1
    assert AUTHOR_SECRET not in repr(journal.records) + repr(result) + repr(backend.values)
    assert credentials.resolve(SCOPE, role_manifest(), "author").credential.token == AUTHOR_SECRET
