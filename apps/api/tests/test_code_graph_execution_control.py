from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time

import pytest

from apps.api.app.application.system_image.source_ports import (
    SourceTextUnit, analyze_with_control,
)
from apps.api.app.application.system_image.structure_builds import StructureBuildCancelled
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import (
    CodebaseMemoryCodeIntelligenceAdapter, CodebaseMemoryError,
)
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessOutput
from apps.api.tests.test_code_graph_enrichment import _config, _source_unit, _adapter, _fake_codebase_memory


def stalled_provider(tmp_path):
    binary = tmp_path / "stalled-provider"
    marker = tmp_path / "pid"
    binary.write_text(f"#!{sys.executable}\nimport os,pathlib,sys,time\n"
        "if sys.argv[1:] == ['--version']:\n print('contract-fixture'); raise SystemExit(0)\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n")
    binary.chmod(0o755)
    return binary, marker


@pytest.mark.parametrize("failure", [StructureBuildCancelled("cancelled"), PermissionError("revoked"), TimeoutError("budget")])
def test_optional_provider_cannot_swallow_execution_control_errors(tmp_path, failure):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    binary, marker = stalled_provider(tmp_path)
    enhanced = CodebaseMemoryCodeIntelligenceAdapter(_config(binary))
    adapter = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), enhanced, mode="optional")

    def check_current():
        if marker.exists():
            raise failure

    started = time.monotonic()
    with pytest.raises(type(failure)) as caught:
        adapter.analyze_controlled([_source_unit(root)], check_current=check_current)
    assert caught.value is failure
    assert time.monotonic() - started < 3
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_native_adapter_uses_minimal_environment_for_version_index_and_queries(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    binary = tmp_path / "environment-provider"
    log = tmp_path / "env.jsonl"
    binary.write_text(f"#!{sys.executable}\nimport os,json,sys\n"
        f"with open({str(log)!r},'a') as handle: handle.write(json.dumps(dict(os.environ))+'\\n')\n"
        "if sys.argv[1:] == ['--version']: print('contract-fixture'); raise SystemExit(0)\n"
        "if sys.argv[2] == 'index_repository': print(json.dumps({'project':'fixture','status':'indexed'}))\n"
        "else: print(json.dumps({'results':[],'has_more':False}))\n")
    binary.chmod(0o755)
    for name in ("NASUS_MODEL_API_KEY", "HTTPS_PROXY", "CBM_ALLOWED_ROOT", "CBM_CACHE_DIR", "FAKE_CBM_SECRET"):
        monkeypatch.setenv(name, "MUST-NOT-INHERIT")
    adapter = CodebaseMemoryCodeIntelligenceAdapter(replace(_config(binary), cache_dir=tmp_path / "private-cache"))
    adapter.analyze_controlled([_source_unit(root)], check_current=lambda: None)
    environments = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(environments) == 3
    staged_roots = {env["CBM_ALLOWED_ROOT"] for env in environments}
    assert len(staged_roots) == 1
    staged = Path(next(iter(staged_roots)))
    assert staged != root and staged.name.startswith("nasus-cbm-") and not staged.exists()
    for env in environments:
        assert "MUST-NOT-INHERIT" not in str(env)
        cache = Path(env["CBM_CACHE_DIR"])
        assert cache.parent == tmp_path / "private-cache"
        assert not cache.exists()


def test_source_mutation_during_provider_execution_rejects_result(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    unit = _source_unit(root)
    original = _adapter(_config(binary))
    native_call = original._call

    def call(tool, payload, **kwargs):
        result = native_call(tool, payload, **kwargs)
        if tool == "index_repository":
            (root / "payments.py").write_text("def changed():\n    return False\n")
        return result

    monkeypatch.setattr(original, "_call", call)
    with pytest.raises(CodebaseMemoryError, match="source changed"):
        original.analyze([unit])


def test_tree_sitter_checks_control_between_source_files(monkeypatch):
    adapter = TreeSitterCodeIntelligenceAdapter()
    units = [SourceTextUnit(f"{index}.py", "def pay():\n    return True\n", 27, "") for index in range(2)]
    original = adapter._analyze_tree_sitter_unit
    parsed = []

    def parse(unit, *args):
        parsed.append(unit.relative_path)
        return original(unit, *args)

    monkeypatch.setattr(adapter, "_analyze_tree_sitter_unit", parse)

    def check_current():
        if parsed:
            raise StructureBuildCancelled("stop before next file")

    with pytest.raises(StructureBuildCancelled):
        adapter.analyze_controlled(units, check_current=check_current)
    assert parsed == ["0.py"]


def test_legacy_port_only_has_pre_and_post_checks_not_fake_mid_execution_support():
    calls = []

    class Legacy:
        def analyze(self, units):
            calls.append("legacy")
            return "result"

    assert analyze_with_control(Legacy(), (), lambda: calls.append("check")) == "result"
    assert calls == ["check", "legacy", "check"]


def test_candidate_preparation_forwards_live_checks_to_extraction():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from apps.api.app.application.system_image.image_candidate_preparation import ImageCandidatePreparation
    from apps.api.tests.test_context_extraction import frozen_extract
    context, manifest, source, _, _ = frozen_extract()
    snapshots = SimpleNamespace(materialization_sources=Mock(return_value=[source]))
    extraction = SimpleNamespace(extract=Mock(return_value=context))
    candidates = SimpleNamespace(freeze=Mock(return_value="candidate"))
    check = Mock()
    result = ImageCandidatePreparation(snapshots, extraction, candidates).prepare(manifest, project_name="project",
        baseline_id="baseline", version_id=None, invocation_id="invocation", recorded_at="now", check_phase=check)
    assert extraction.extract.call_args.kwargs["check_phase"] is check
    assert extraction.extract.call_args.kwargs["source_manifest"] == manifest
    assert extraction.extract.call_args.kwargs["sources"] == [source]
    assert check.call_count == 3
    assert result.context is context and result.sources == (source,)
    assert candidates.freeze.call_args.kwargs["objects"] == context.objects


def test_candidate_preparation_does_not_freeze_unregistered_compatibility_objects():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from apps.api.app.application.system_image.image_candidate_preparation import ImageCandidatePreparation
    from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
    from apps.api.tests.test_context_extraction import frozen_extract
    context, manifest, source, _, _ = frozen_extract()
    context.objects[0] = context.objects[0].model_copy(update={"code_reference": None})
    snapshots = SimpleNamespace(materialization_sources=Mock(return_value=[source]))
    extraction = SimpleNamespace(extract=Mock(return_value=context))
    candidates = SimpleNamespace(freeze=Mock())
    check = Mock()
    with pytest.raises(ImageRevisionIntegrityError, match="source-pinned"):
        ImageCandidatePreparation(snapshots, extraction, candidates).prepare(manifest, project_name="project",
            baseline_id="baseline", version_id=None, invocation_id="invocation", recorded_at="now", check_phase=check)
    assert extraction.extract.call_args.kwargs["check_phase"] is check
    assert check.call_count == 2
    candidates.freeze.assert_not_called()


class SnapshotProbeRunner:
    """Protocol fixture inspecting the actual adapter-owned source snapshot."""

    def __init__(self, failure=None):
        self.failure = failure
        self.roots = []
        self.caches = []
        self.files = None
        self.file_modes = None

    def run(self, args, *, env, **kwargs):
        root = Path(env["CBM_ALLOWED_ROOT"])
        self.roots.append(root)
        cache = Path(env["CBM_CACHE_DIR"])
        self.caches.append(cache)
        if args[1:] == ["--version"]:
            return CodeGraphProcessOutput("snapshot-contract-fixture", "", 0)
        if args[2] == "index_repository":
            (cache / "private-provider-index").write_text("PRIVATE-DERIVED-SOURCE")
            paths = sorted(path for path in root.rglob("*") if path.is_file())
            self.files = {path.relative_to(root).as_posix(): path.read_bytes() for path in paths}
            self.file_modes = {path.relative_to(root).as_posix(): path.stat().st_mode & 0o777 for path in paths}
            if self.failure is not None:
                raise self.failure
            return CodeGraphProcessOutput(json.dumps({"project": "fixture", "status": "indexed"}), "", 0)
        return CodeGraphProcessOutput(json.dumps({"results": [], "has_more": False}), "", 0)


def test_snapshot_contains_only_approved_raw_bytes_and_is_removed(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    raw = "# 中文\r\ndef pay():\r\n    return True\r\n".encode("utf-8")
    (root / "payments.py").write_bytes(raw)
    (root / "not-approved.py").write_text("PRIVATE-NOT-APPROVED")
    (root / ".git").mkdir()
    (root / ".git/config").write_text("PRIVATE-CREDENTIAL")
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    adapter.analyze([_source_unit(root)])
    assert runner.files == {"payments.py": raw}
    assert runner.file_modes == {"payments.py": 0o400}
    assert len(set(runner.roots)) == 1 and runner.roots[0] != root
    assert all(not path.exists() for path in runner.roots)
    assert all(not path.exists() for path in runner.caches)
    assert (root / "payments.py").read_bytes() == raw
    assert (root / "not-approved.py").read_text() == "PRIVATE-NOT-APPROVED"


@pytest.mark.parametrize("error", [CodebaseMemoryError("provider failure"), StructureBuildCancelled("cancelled"), KeyboardInterrupt()])
def test_snapshot_removed_after_failure_and_control_context_is_reset(tmp_path, error):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    runner = SnapshotProbeRunner(failure=error)
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    with pytest.raises(type(error)) as caught:
        adapter.analyze_controlled([_source_unit(root)], check_current=lambda: None)
    assert caught.value is error
    assert runner.roots and all(not path.exists() for path in runner.roots)
    assert all(not path.exists() for path in runner.caches)
    assert adapter._execution_check.get() is None and adapter._execution_root.get() is None
    assert adapter._execution_cache.get() is None
    runner.failure = None
    adapter.analyze([_source_unit(root)])
    assert all(not path.exists() for path in runner.roots)


@pytest.mark.parametrize("duplicate", ["payments.py", "./payments.py"])
def test_duplicate_normalized_snapshot_paths_rejected_before_provider_launch(tmp_path, duplicate):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    unit = _source_unit(root)
    with pytest.raises(CodebaseMemoryError, match="duplicate"):
        adapter.analyze([unit, replace(unit, relative_path=duplicate)])
    assert not runner.roots


def test_every_snapshot_unit_requires_the_same_declared_source_root(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    (root / "undeclared.py").write_bytes((root / "payments.py").read_bytes())
    unit = _source_unit(root)
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    with pytest.raises(CodebaseMemoryError, match="repository root"):
        adapter.analyze([unit, replace(unit, relative_path="undeclared.py", source_root=None)])
    assert not runner.roots


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_snapshot_symlinks_rejected_before_provider_launch(tmp_path, kind):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    unit = _source_unit(root)
    if kind == "file":
        (root / "link.py").symlink_to(root / "payments.py")
        unit = replace(unit, relative_path="link.py")
    else:
        (root / "nested").symlink_to(root, target_is_directory=True)
        unit = replace(unit, relative_path="nested/payments.py")
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    with pytest.raises(CodebaseMemoryError, match="symbolic links"):
        adapter.analyze([unit])
    assert not runner.roots


def test_provider_project_changes_do_not_change_normalized_snapshot_entities(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    monkeypatch.setenv("FAKE_CBM_SCHEMA", "flat")
    monkeypatch.setenv("FAKE_CBM_LOCATIONS", "true")
    adapter = _adapter(_config(binary))
    monkeypatch.setenv("FAKE_CBM_PROJECT", "first-private-root")
    first = adapter.analyze([_source_unit(root)])
    monkeypatch.setenv("FAKE_CBM_PROJECT", "second-private-root")
    second = adapter.analyze([_source_unit(root)])
    assert first == second
    index_roots = [Path(item["payload"]["repo_path"]) for item in map(json.loads, log.read_text().splitlines())
                   if item["tool"] == "index_repository"]
    assert len(set(index_roots)) == 2 and all(not path.exists() for path in index_roots)


def test_private_index_cleanup_preserves_other_cache_entries(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    cache_parent = tmp_path / "cache"
    cache_parent.mkdir()
    retained = cache_parent / "other-project-index"
    retained.write_text("DO-NOT-DELETE")
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(replace(_config(Path(sys.executable)), cache_dir=cache_parent),
                                                   process_runner=runner)
    adapter.analyze([_source_unit(root)])
    assert all(path.parent == cache_parent and not path.exists() for path in runner.caches)
    assert list(cache_parent.iterdir()) == [retained] and retained.read_text() == "DO-NOT-DELETE"


@pytest.mark.parametrize("field,value", [("content_hash", ""), ("content_hash", "sha256:invalid"),
                                        ("byte_count", 0), ("byte_count", True)])
def test_snapshot_requires_valid_digest_and_exact_byte_count_before_launch(tmp_path, field, value):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    with pytest.raises(CodebaseMemoryError):
        adapter.analyze([replace(_source_unit(root), **{field: value})])
    assert not runner.roots


def test_symlink_replacement_at_file_open_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "payments.py"
    source.write_text("def pay():\n    return True\n")
    unit = _source_unit(root)
    outside = tmp_path / "private.py"
    outside.write_text("PRIVATE-OUTSIDE-SNAPSHOT")
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    original_open = os.open
    swapped = []

    def swap_before_open(path, flags, *args, **kwargs):
        if Path(path).name == "payments.py" and not swapped:
            swapped.append(True)
            source.unlink()
            source.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_open)
    with pytest.raises(CodebaseMemoryError) as caught:
        adapter.analyze([unit])
    assert swapped and not runner.roots
    assert "PRIVATE-OUTSIDE-SNAPSHOT" not in str(caught.value)


def test_waiting_for_another_index_can_be_cancelled_without_launching_provider(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    error = StructureBuildCancelled("cancel while queued")
    staged_roots = []
    caches = []

    def check_current():
        staged = adapter._execution_root.get()
        if staged is not None:
            staged_roots.append(staged)
            caches.append(adapter._execution_cache.get())
            raise error

    started = time.monotonic()
    with adapter._lock, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(adapter.analyze_controlled, [_source_unit(root)], check_current=check_current)
        with pytest.raises(StructureBuildCancelled) as caught:
            future.result(timeout=2)
    assert caught.value is error and time.monotonic() - started < 2
    assert staged_roots and not runner.roots
    assert all(not path.exists() for path in staged_roots + caches)
    adapter.analyze([_source_unit(root)])
    assert runner.roots


def test_snapshot_file_descriptors_close_when_execution_control_fails(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    unit = _source_unit(root)
    runner = SnapshotProbeRunner()
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(Path(sys.executable)), process_runner=runner)
    opened, closed = [], []
    original_open, original_close = os.open, os.close
    error = PermissionError("access changed during copy")

    def tracked_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def tracked_close(fd):
        closed.append(fd)
        original_close(fd)

    def check_current():
        if len(opened) == 2:
            raise error

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    with pytest.raises(PermissionError) as caught:
        adapter.analyze_controlled([unit], check_current=check_current)
    assert caught.value is error and len(opened) == 2
    assert sorted(opened) == sorted(closed) and not runner.roots
