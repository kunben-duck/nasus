from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from apps.api.app.application.system_image.context_extraction import ContextExtractionService
from apps.api.app.application.system_image.source_ports import MaterializedSource
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.infrastructure.system_image.git_source_connector import (
    EnvironmentSourceCredentialResolver,
    GitSourceConnector,
    GitSourceConnectorError,
)
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import (
    TreeSitterCodeIntelligenceAdapter,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_repository(repo: Path) -> str:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "nasus-test@example.com")
    _git(repo, "config", "user.name", "Nasus Test")
    (repo / "checkout.py").write_text("def checkout(cart):\n    return cart.total\n", encoding="utf-8")
    _git(repo, "add", "checkout.py")
    _git(repo, "commit", "-m", "initial")
    return _git(repo, "rev-parse", "HEAD")


def _source(source_uri: str, *, credential_ref: str | None = None) -> RawAssetRecord:
    return RawAssetRecord(
        id="raw_project_code",
        project_id="project",
        source_type="code",
        source_uri=source_uri,
        credential_ref=credential_ref,
        ingestion_status="indexed",
    )


def test_git_connector_refresh_preserves_the_previous_revision_snapshot(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    initial_revision = _create_repository(origin)
    connector = GitSourceConnector(
        cache_dir=tmp_path / "cache",
        allowed_schemes={"file"},
        timeout_seconds=15,
    )
    source = _source(origin.as_uri())

    first = connector.materialize(source, refresh=True)

    assert first.revision == initial_revision
    assert first.local_path != origin
    assert (first.local_path / "checkout.py").read_text(encoding="utf-8").startswith("def checkout")
    assert "connector:git" in first.evidence_refs
    assert f"git:revision:{initial_revision}" in first.evidence_refs

    (origin / "checkout.py").write_text(
        "def checkout(cart):\n    return cart.total_with_tax\n",
        encoding="utf-8",
    )
    _git(origin, "add", "checkout.py")
    _git(origin, "commit", "-m", "update checkout")
    updated_revision = _git(origin, "rev-parse", "HEAD")

    second = connector.materialize(source, refresh=True)

    assert second.local_path != first.local_path
    assert second.revision == updated_revision
    assert second.revision != initial_revision
    assert "total_with_tax" in (second.local_path / "checkout.py").read_text(encoding="utf-8")
    assert "total_with_tax" not in (first.local_path / "checkout.py").read_text(encoding="utf-8")
    assert _git(first.local_path, "rev-parse", "HEAD") == initial_revision


def test_git_connector_restores_a_persisted_revision_after_restart(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    revision = _create_repository(origin)
    source = _source(origin.as_uri())
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    first = connector.materialize(source, refresh=True)
    source.evidence_refs = list(first.evidence_refs)
    (origin / "checkout.py").write_text("def replacement():\n    return 2\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "new head")
    connector.materialize(source, refresh=True)

    restarted = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    restored = restarted.materialize(source, refresh=False)

    assert restored.revision == revision
    assert restored.local_path == first.local_path
    assert "def checkout" in (restored.local_path / "checkout.py").read_text(encoding="utf-8")


def test_explicit_branch_and_tag_ignore_default_head_and_restore_old_commit(tmp_path):
    origin = tmp_path / "origin"
    first_revision = _create_repository(origin)
    _git(origin, "branch", "release/v1")
    _git(origin, "branch", "-M", "main")
    _git(origin, "tag", "-a", "v1", "-m", "annotated release")
    (origin / "checkout.py").write_text("def new_main():\n    return 2\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "main advanced")
    main_revision = _git(origin, "rev-parse", "HEAD")
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    source = _source(origin.as_uri())
    branch = source.model_copy(update={"tracked_ref": "refs/heads/release/v1"})
    tag = source.model_copy(update={"tracked_ref": "refs/tags/v1"})
    first = connector.materialize(branch, refresh=True)
    tagged = connector.materialize(tag, refresh=True)
    assert first.revision == tagged.revision == first_revision != main_revision
    assert first.local_path != tagged.local_path
    assert "git:tracked-ref:refs/heads/release/v1" in first.evidence_refs
    old = branch.model_copy(update={"evidence_refs": list(first.evidence_refs)})
    _git(origin, "update-ref", "refs/heads/release/v1", main_revision)
    advanced = connector.materialize(branch, refresh=True)
    assert advanced.revision == main_revision and advanced.local_path != first.local_path
    assert connector.materialize(tag, refresh=True).revision == first_revision
    fresh = GitSourceConnector(cache_dir=tmp_path / "fresh-cache", allowed_schemes={"file"})
    restored = fresh.materialize(old, refresh=False)
    assert restored.revision == first_revision
    assert "def checkout" in (restored.local_path / "checkout.py").read_text()
    assert connector.materialize(old, refresh=False).local_path == first.local_path


def test_missing_explicit_ref_fails_without_default_branch_or_cache_fallback(tmp_path):
    origin = tmp_path / "origin"
    _create_repository(origin)
    _git(origin, "branch", "release")
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    source = _source(origin.as_uri()).model_copy(update={"tracked_ref": "refs/heads/release"})
    first = connector.materialize(source, refresh=True)
    old = source.model_copy(update={"evidence_refs": list(first.evidence_refs)})
    _git(origin, "branch", "-D", "release")
    with pytest.raises(GitSourceConnectorError):
        connector.materialize(source, refresh=True)
    assert connector.materialize(old, refresh=False).revision == first.revision
    fresh = GitSourceConnector(cache_dir=tmp_path / "fresh-cache", allowed_schemes={"file"})
    with pytest.raises(GitSourceConnectorError):
        fresh.materialize(source, refresh=True)


def test_invalid_tracked_ref_never_invokes_git_even_after_unvalidated_model_copy(tmp_path, monkeypatch):
    connector = GitSourceConnector(cache_dir=tmp_path / "cache")
    source = _source("https://github.com/example/repo.git").model_copy(update={"tracked_ref": "HEAD"})
    monkeypatch.setattr(connector, "_run_git", lambda *args, **kwargs: pytest.fail("invalid ref invoked Git"))
    with pytest.raises(ValueError, match="tracked_ref"):
        connector.materialize(source, refresh=True)


def test_tracked_local_git_is_read_from_commit_not_working_tree(tmp_path):
    origin = tmp_path / "origin"
    revision = _create_repository(origin)
    _git(origin, "branch", "release")
    (origin / "checkout.py").write_text("uncommitted private work\n")
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    ingestion = SourceIngestionService(connectors=[connector], allowed_local_roots=[origin],
        snapshot_cache_dir=tmp_path / "snapshots")
    source = _source(origin.as_uri()).model_copy(update={"tracked_ref": "refs/heads/release"})
    captured = ingestion.ingest(source)
    assert f"git:revision:{revision}" in captured.evidence_refs
    archived = source.model_copy(update={"content_ref": captured.content_ref, "content_hash": captured.content_hash})
    assert ingestion.extract_text_units(archived)[0].text == "def checkout(cart):\n    return cart.total\n"
    assert (origin / "checkout.py").read_text() == "uncommitted private work\n"
    with pytest.raises(OSError, match="no source connector"):
        SourceIngestionService(connectors=[], allowed_local_roots=[origin],
            snapshot_cache_dir=tmp_path / "unavailable").ingest(source)


def test_git_connector_can_recover_an_old_revision_into_a_new_cache(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    revision = _create_repository(origin)
    (origin / "checkout.py").write_text("def replacement():\n    return 2\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "new head")
    source = _source(origin.as_uri())
    source.evidence_refs = [f"git:revision:{revision}"]

    result = GitSourceConnector(
        cache_dir=tmp_path / "fresh-cache", allowed_schemes={"file"},
    ).materialize(source, refresh=False)

    assert result.revision == revision
    assert "def checkout" in (result.local_path / "checkout.py").read_text(encoding="utf-8")


def test_git_snapshots_are_isolated_by_project_and_binding(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _create_repository(origin)
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    first_source = _source(origin.as_uri())
    another_project = first_source.model_copy(update={"project_id": "other-project"})
    another_binding = first_source.model_copy(update={"id": "other-binding"})

    snapshots = [connector.materialize(item, refresh=True) for item in (first_source, another_project, another_binding)]

    assert len({item.local_path for item in snapshots}) == 3
    assert len({item.revision for item in snapshots}) == 1


def test_git_snapshot_refuses_modified_contents_instead_of_reusing_them(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _create_repository(origin)
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    source = _source(origin.as_uri())
    snapshot = connector.materialize(source, refresh=True)
    source.evidence_refs = list(snapshot.evidence_refs)
    (snapshot.local_path / "checkout.py").write_text("altered\n", encoding="utf-8")

    with pytest.raises(OSError, match="contents changed"):
        connector.materialize(source, refresh=False)


@pytest.mark.parametrize("ignore_file", [".gitignore", ".git/info/exclude"])
def test_git_snapshot_refuses_ignored_untracked_files(tmp_path, ignore_file):
    origin = tmp_path / "origin"
    _create_repository(origin)
    if ignore_file == ".gitignore":
        (origin / ignore_file).write_text("injected.py\n")
        _git(origin, "add", ignore_file)
        _git(origin, "commit", "-m", "ignore runtime files")
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    source = _source(origin.as_uri())
    snapshot = connector.materialize(source, refresh=True)
    source.evidence_refs = list(snapshot.evidence_refs)
    if ignore_file != ".gitignore":
        (snapshot.local_path / ignore_file).write_text("injected.py\n")
    (snapshot.local_path / "injected.py").write_text("uncommitted knowledge\n")
    assert not _git(snapshot.local_path, "status", "--porcelain", "--untracked-files=all")
    with pytest.raises(OSError, match="contents changed"):
        connector.materialize(source, refresh=False)
    assert (snapshot.local_path / "injected.py").exists()


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_git_snapshot_refuses_index_flags_that_hide_changed_files(tmp_path, flag):
    origin = tmp_path / "origin"
    _create_repository(origin)
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    source = _source(origin.as_uri())
    snapshot = connector.materialize(source, refresh=True)
    source.evidence_refs = list(snapshot.evidence_refs)
    _git(snapshot.local_path, "update-index", flag, "checkout.py")
    (snapshot.local_path / "checkout.py").write_text("uncommitted knowledge\n")
    assert not _git(snapshot.local_path, "status", "--porcelain")
    with pytest.raises(OSError, match="index skips"):
        connector.materialize(source, refresh=False)


def test_git_snapshot_refuses_symlinked_repository_metadata(tmp_path):
    origin = tmp_path / "origin"
    _create_repository(origin)
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    source = _source(origin.as_uri())
    snapshot = connector.materialize(source, refresh=True)
    metadata = snapshot.local_path / ".git"
    moved = snapshot.local_path.parent / "moved-metadata"
    metadata.rename(moved)
    metadata.symlink_to(moved, target_is_directory=True)
    with pytest.raises(OSError, match="not a detached repository"):
        connector.materialize(source, refresh=False)


@pytest.mark.parametrize("revision", ["HEAD", "--upload-pack=evil", "abc123", "a" * 40 + "\n"])
def test_git_connector_rejects_invalid_persisted_revisions(tmp_path: Path, revision: str) -> None:
    source = _source("https://github.com/example/project.git")
    source.evidence_refs = [f"git:revision:{revision}"]
    connector = GitSourceConnector(cache_dir=tmp_path / "cache")

    with pytest.raises(GitSourceConnectorError, match="invalid pinned revision"):
        connector.materialize(source, refresh=False)


def test_ingestion_cache_keeps_two_revisions_of_the_same_binding(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _create_repository(origin)
    connector = GitSourceConnector(cache_dir=tmp_path / "cache", allowed_schemes={"file"})
    ingestion = SourceIngestionService(connectors=[connector], allowed_external_schemes={"https"})
    # HTTPS identifies a remote source while the test connector resolves it locally.
    source = _source("https://git.example.com/payments.git")

    class LocalRemote:
        def supports(self, _source: RawAssetRecord) -> bool:
            return True

        def materialize(self, current: RawAssetRecord, *, refresh: bool) -> MaterializedSource:
            return connector.materialize(current.model_copy(update={"source_uri": origin.as_uri()}), refresh=refresh)

    ingestion.connectors = (LocalRemote(),)
    first = ingestion.ingest(source)
    old = source.model_copy(update={"evidence_refs": first.evidence_refs, "content_hash": first.content_hash})
    (origin / "checkout.py").write_text("def replacement():\n    return 2\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "replace")
    second = ingestion.ingest(old)
    new = old.model_copy(update={"evidence_refs": second.evidence_refs, "content_hash": second.content_hash})

    assert "def checkout" in ingestion.extract_text_units(old)[0].text
    assert "def replacement" in ingestion.extract_text_units(new)[0].text


def test_source_ingestion_rejects_symlinks_before_reading_outside_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("not authorized", encoding="utf-8")
    (root / "linked.txt").symlink_to(secret)
    service = SourceIngestionService(connectors=[], allowed_local_roots=[root])

    with pytest.raises(PermissionError, match="symbolic link"):
        service.ingest(_source(str(root)))
    with pytest.raises(PermissionError, match="symbolic link"):
        service.extract_text_units(_source(str(root)))


def test_git_connector_enforces_safe_uri_and_host_allowlist(tmp_path: Path) -> None:
    connector = GitSourceConnector(
        cache_dir=tmp_path / "cache",
        allowed_hosts={"github.com"},
        allowed_schemes={"https"},
        git_binary="git",
    )

    with pytest.raises(PermissionError, match="credential_ref"):
        connector.materialize(_source("https://token@github.com/acme/repo.git"), refresh=True)

    with pytest.raises(PermissionError, match="host is not allowed"):
        connector.materialize(_source("https://git.example.com/acme/repo.git"), refresh=True)


def test_environment_credential_resolver_only_accepts_explicit_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = EnvironmentSourceCredentialResolver()
    monkeypatch.setenv("NASUS_TEST_GIT_TOKEN", "secret-token")

    assert resolver.resolve("env:NASUS_TEST_GIT_TOKEN") == "secret-token"
    with pytest.raises(GitSourceConnectorError, match="unsupported"):
        resolver.resolve("secret-token")
    with pytest.raises(GitSourceConnectorError, match="unavailable"):
        resolver.resolve("env:NASUS_MISSING_GIT_TOKEN")


class _RemoteCheckoutConnector:
    connector_kind = "test-git"

    def __init__(self, checkout: Path) -> None:
        self.checkout = checkout
        self.calls: list[bool] = []

    def supports(self, source: RawAssetRecord) -> bool:
        return source.source_uri.startswith("https://git.example.com/")

    def materialize(self, source: RawAssetRecord, *, refresh: bool) -> MaterializedSource:
        self.calls.append(refresh)
        return MaterializedSource(
            local_path=self.checkout,
            connector_kind=self.connector_kind,
            source_ref=source.source_uri,
            revision="a" * 40,
            evidence_refs=("connector:test-git", f"git:revision:{'a' * 40}"),
        )


def test_remote_checkout_drives_ingestion_chunks_and_context_extraction(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "payments.py").write_text(
        "class PaymentService:\n    def authorize(self, payment):\n        return payment.approved\n",
        encoding="utf-8",
    )
    connector = _RemoteCheckoutConnector(checkout)
    ingestion = SourceIngestionService(
        connectors=[connector],
        allowed_external_schemes={"https"},
    )
    source = _source("https://git.example.com/acme/payments.git")

    ingested = ingestion.ingest(source)
    source.content_hash = ingested.content_hash
    units = ingestion.extract_text_units(source)
    extracted = ContextExtractionService(
        ingestion,
        TreeSitterCodeIntelligenceAdapter(),
    ).extract(
        project_id="project",
        project_name="Payments",
        baseline_id="baseline",
        sources=[source],
        version_id=None,
        captured_at="2026-07-23T00:00:00Z",
    )

    assert ingested.file_count == 1
    assert ingested.byte_count > 0
    assert "connector:test-git" in ingested.evidence_refs
    assert units[0].relative_path == "payments.py"
    assert units[0].source_root == str(checkout)
    assert connector.calls == [True]
    assert any(item.type == "CodeClass" and "PaymentService" in item.name for item in extracted.objects)
    assert any(item.type == "CodeMethod" and "authorize" in item.name for item in extracted.objects)
    assert any(item.relationship_type == "belongs_to" for item in extracted.relationships)
    assert any(ref.startswith("parser:tree-sitter:") for ref in source.evidence_refs)
