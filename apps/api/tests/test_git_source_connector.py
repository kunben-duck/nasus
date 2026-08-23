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


def test_git_connector_clones_revision_and_refreshes_managed_checkout(tmp_path: Path) -> None:
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

    assert second.local_path == first.local_path
    assert second.revision == updated_revision
    assert second.revision != initial_revision
    assert "total_with_tax" in (second.local_path / "checkout.py").read_text(encoding="utf-8")


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
