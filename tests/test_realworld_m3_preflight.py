"""A partial protocol must not become a successful live M3 acceptance receipt."""
import importlib.util
import json
from pathlib import Path
import sys


def load_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts/verify-realworld-m3.py"
    spec = importlib.util.spec_from_file_location("m3_acceptance_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_preflight_reports_missing_capabilities_without_target_or_model_calls(tmp_path, monkeypatch, capsys):
    verifier = load_verifier()
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify-realworld-m3.py", "--phase", "full"])
    def forbidden(*args, **kwargs):
        raise AssertionError("blocked preflight must not call a model, target or migration")
    monkeypatch.setattr(verifier.subprocess, "run", forbidden)
    monkeypatch.setattr(verifier.subprocess, "call", forbidden)
    monkeypatch.setattr(verifier.subprocess, "check_output", forbidden)
    monkeypatch.setattr(verifier, "urlopen", forbidden)
    assert verifier.main() == 2
    result = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(result.pop("report_path")).read_text())
    assert result == saved
    assert saved["full_m3_verified"] is False and saved["status"] == "blocked"
    assert saved["execution_status"] == saved["cleanup_status"] == "not_started"
    assert "controlled_role_credentials_required" in saved["blockers"]
    assert "durable_environment_lease_and_reset_required" in saved["blockers"]
    assert "model_scope_draft_live_acceptance_required" in saved["blockers"]
    assert "formal_browser_runplan_required" in saved["blockers"]
    assert "encrypted_snapshots_and_restore_required" in saved["blockers"]
    assert "denial_readback_after_failed_assertion_required" not in saved["blockers"]


def test_acceptance_reports_do_not_overwrite_another_attempt(tmp_path, monkeypatch):
    verifier = load_verifier()
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    first, second = verifier.report_directory(), verifier.report_directory()
    assert first != second and first.is_dir() and second.is_dir()
    assert first.stat().st_mode & 0o077 == second.stat().st_mode & 0o077 == 0


def test_retained_mode_never_enters_disposable_store_or_live_model_fixture(monkeypatch):
    verifier = load_verifier()
    monkeypatch.setattr(sys, "argv", ["verify-realworld-m3.py", "--mode", "retained", "--acceptance-id", "m3-retained"])
    calls = []
    monkeypatch.setattr(verifier.subprocess, "call", lambda args, **kwargs: calls.append(args) or 2)
    monkeypatch.setattr(verifier, "report_directory", lambda: (_ for _ in ()).throw(AssertionError("not an isolated run")))
    assert verifier.main() == 2
    assert calls == [["node", "scripts/realworld-retained-observe.mjs", "--acceptance-id", "m3-retained"]]
