import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("realworld_contract", ROOT / "scripts/realworld_contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def test_forbidden_response_alone_cannot_hide_a_write():
    before = dict(title="t", description="d", body="before", slug="s", author={"username": "a"})
    after = {"status": 200, "body": {"article": {**before, "body": "modified"}}}
    assertions = contract.evaluate("other_author_denied", {"status": 403}, before, after)
    assert assertions[0]["passed"] and not assertions[1]["passed"]


def test_status_200_without_persistence_cannot_pass():
    before = dict(title="t", description="d", body="before", slug="s", author={"username": "a"})
    assertions = contract.evaluate("partial_edit", {"status": 200}, before, {"status": 200, "body": {"article": before}})
    assert not all(item["passed"] for item in assertions)


def test_credentials_are_removed_from_evidence():
    assert contract.redact({"user": {"token": "secret", "password": "secret"}}) == {
        "user": {"token": "[redacted]", "password": "[redacted]"}}


def test_title_update_cannot_change_author_or_erase_unmodified_fields():
    before = dict(title="t", description="d", body="before", slug="s", author={"username": "a"})
    for field in ("author", "description", "body"):
        article = {**before, "title": "updated t", "slug": "updated-t", field: None}
        checks = contract.evaluate("title_slug", {"status": 200}, before, {"status": 200, "body": {"article": article}})
        assert not all(check["passed"] for check in checks)


@pytest.mark.parametrize("arguments,reason", [
    ([], "Full M1-M5 acceptance is not implemented"),
    (["--phase", "runtime"], "runtime verification requires --image and --pg-image"),
    (["--phase", "runtime", "--image", "mutable:latest", "--pg-image", "postgres:16"],
     "mutable image names are not accepted"),
])
def test_acceptance_cli_cannot_pass_incomplete_or_unpinned_work(arguments, reason):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/verify-realworld-loop.py"), *arguments],
                            cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert reason in result.stderr
