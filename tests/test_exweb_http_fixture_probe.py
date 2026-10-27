"""Archive and dispatch-fence specimens. Real exweb execution is reported separately."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts.exweb_http_fixture_probe import (
    ProbeFixtureJournal, observe_exweb_http_fixtures, replay_exweb_http_fixtures,
)
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureDispatchAlreadyClaimed
from apps.api.tests.test_http_fixtures import Runner
from apps.api.tests.test_http_bindings import specimen


def report(tmp_path):
    runner = Runner()
    def response(command):
        phase, case = command.metadata["fixture_phase"], command.us_id
        if phase == "setup" and case == "setup_oracle_failure":
            return specimen(command, states=["passed", "passed", "passed", "failed"], status="failed")
        if phase == "cleanup:session" and case == "closed_read_cleanup_failure":
            return specimen(command, states=["passed", "passed", "passed", "passed", "failed"], status="failed")
        return specimen(command)
    runner.payload = response
    from apps.api.tests.test_http_fixtures import scope
    original = scope()
    result = observe_exweb_http_fixtures(runner,
        SimpleNamespace(project_id=original.project_id, environment_id=original.environment_id),
        SimpleNamespace(inventory_hash=original.inventory_hash), {"jar_hash": original.artifact_hash}, tmp_path, revision="explicit-protocol-revision")
    return {"http_runner": {"http_fixtures": result}}, runner


def test_private_probe_replay_rechecks_complete_original_bytes_without_an_execution_adapter(tmp_path):
    original, runner = report(tmp_path)
    assert len(runner.commands) == 6 and all(original["http_runner"]["http_fixtures"]["checks"].values())
    replay = replay_exweb_http_fixtures(original)
    assert not replay["target_reexecuted"] and not replay["formal_coverage_verified"]
    assert not replay["durable_postgresql_journal_verified"] and len(runner.commands) == 6
    assert replay["cases"][1]["setup_status"] == "failed"
    assert replay["cases"][2]["cleanup_verified"] is False


@pytest.mark.parametrize("fault", ["result", "request", "manifest", "scope", "count", "executor"])
def test_readonly_replay_rejects_missing_or_changed_original_data(tmp_path, fault):
    original, _ = report(tmp_path)
    item = original["http_runner"]["http_fixtures"]["cases"][0]
    from pathlib import Path
    if fault in {"result", "request"}:
        Path(item["phases"][0][fault + "_archive"]).write_bytes(b"{}")
    if fault == "manifest": Path(item["manifest_archive"]).write_bytes(b"{}")
    if fault == "scope": item["scope"]["inventory_hash"] = "sha256:" + "0" * 64
    if fault == "count": original["http_runner"]["http_fixtures"]["cases"].pop()
    if fault == "executor": original["http_runner"]["http_fixtures"]["executor_sources"][0]["content_hash"] = "sha256:" + "0" * 64
    with pytest.raises((ValueError, RuntimeError)):
        replay_exweb_http_fixtures(original)


def test_private_dispatch_claim_cannot_be_replaced_and_readonly_journal_never_claims(tmp_path):
    original, runner = report(tmp_path)
    from pathlib import Path
    from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
    item = original["http_runner"]["http_fixtures"]["cases"][0]
    current = HttpFixtureScope(**item["scope"])
    journal = ProbeFixtureJournal(Path(item["manifest_archive"]).parent, readonly=True)
    saved = journal.inspect(current, "setup")
    assert saved.command == runner.commands[0]
    with pytest.raises(ValueError, match="readonly"):
        journal.claim(current, "setup", saved.command, require_current=lambda: None)
    journal.readonly = False
    with pytest.raises(HttpFixtureDispatchAlreadyClaimed):
        journal.claim(current, "setup", saved.command, require_current=lambda: None)
    assert journal.inspect(current, "setup") == saved


def test_original_file_fence_is_not_namespaced_by_mutable_scope_digest(tmp_path):
    original, runner = report(tmp_path)
    from pathlib import Path
    from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
    item = original["http_runner"]["http_fixtures"]["cases"][0]
    current = HttpFixtureScope(**item["scope"])
    journal = ProbeFixtureJournal(Path(item["manifest_archive"]).parent, readonly=True)
    changed = replace(current, artifact_hash="sha256:" + "0" * 64)
    assert journal.paths(current, "setup") == journal.paths(changed, "setup")
    with pytest.raises(ValueError, match="scope differs"): journal.inspect(changed, "setup")
    assert len(runner.commands) == 6
