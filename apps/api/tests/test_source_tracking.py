from __future__ import annotations

import subprocess

import pytest

from apps.api.app.application.system_image.source_ports import SourceSpec
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_tracking import require_tracked_ref
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/release/v1", "refs/tags/a",
    "refs/tags/v1.0.1", "refs/heads/-explicit", "refs/heads/研发", "refs/heads/a+b"])
def test_explicit_refs_agree_with_native_git_ref_format(ref):
    assert require_tracked_ref("code", ref) == ref
    assert subprocess.run(["git", "check-ref-format", ref], capture_output=True).returncode == 0
    assert SourceSpec("code", "https://example.com/repo.git", tracked_ref=ref).tracked_ref == ref


@pytest.mark.parametrize("ref", ["", "main", "HEAD", "a" * 40, "--upload-pack=evil", "refs/heads/",
    "refs/tags/", "refs/heads/a..b", "refs/heads/a//b", "refs/heads/.private", "refs/heads/a.lock",
    "refs/heads/a.lock/b", "refs/heads/a.", "refs/heads/a/", "refs/heads/a:b", "refs/heads/a b",
    "refs/heads/a\n", "refs/heads/a\x7f", "refs/heads/a^{}", "refs/heads/a~1", "refs/heads/a?",
    "refs/heads/a*", "refs/heads/a[1]", "refs/heads/a\\b", "refs/heads/a@{1}", "refs/remotes/origin/main",
    "refs/heads/" + "a" * 250, False, 12, ["refs/heads/main"]])
def test_invalid_or_ambiguous_ref_is_rejected_before_source_registration(ref):
    with pytest.raises(ValueError, match="tracked_ref"):
        SourceSpec("code", "https://example.com/repo.git", tracked_ref=ref)


@pytest.mark.parametrize("kind", ["us_doc", "test_asset"])
def test_only_code_sources_can_track_git_refs(kind):
    with pytest.raises(ValueError, match="tracked_ref"):
        SourceSpec(kind, "https://example.com/source", tracked_ref="refs/heads/main")


def test_normalization_preserves_explicit_ref_and_rejects_invalid_ref_as_a_whole(tmp_path):
    service = SourceIngestionService(connectors=[], snapshot_cache_dir=tmp_path / "cache")
    raw = {"source_type": "code", "source_uri": "https://example.com/repo.git", "tracked_ref": "refs/heads/main"}
    assert service.normalize_specs([raw])[0].tracked_ref == raw["tracked_ref"]
    assert service.normalize_specs([{key: value for key, value in raw.items() if key != "tracked_ref"}])[0].tracked_ref is None
    with pytest.raises(ValueError, match="tracked_ref"):
        service.normalize_specs([raw, {**raw, "tracked_ref": "HEAD"}])


def test_raw_asset_rejects_invalid_tracking_on_http_and_persistence_reads():
    with pytest.raises(ValueError, match="tracked_ref"):
        RawAssetRecord(id="source", project_id="project", source_type="code", source_uri="/repo", tracked_ref="main")
