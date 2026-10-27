"""Installed-byte and source closure checks; no mutation of the developer venv."""
from importlib.metadata import PackagePath
from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.code_index import CodeIndexCancelled
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image import code_graph_dependencies as dependencies
from apps.api.app.infrastructure.system_image.code_graph_dependency_files import DependencyFiles
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessError


@pytest.fixture
def source_tree(tmp_path):
    package = tmp_path / "probe"
    package.mkdir()
    (package / "__init__.py").write_text("from .owner import NAME\n")
    (package / "owner.py").write_text("NAME = 'one'\n")
    (package / "entry.py").write_text("from .branch import action\nimport json\n")
    (package / "branch.py").write_text("from .leaf import value\n")
    (package / "leaf.py").write_text("value = 1\nraise RuntimeError('must not execute fingerprinted source')\n")
    return tmp_path


def source_manifest(root, entries=("probe.entry",)):
    reader = DependencyFiles()
    result = dependencies.projection_source_manifest(root, entries, reader)
    reader.finish()
    return result


def test_transitive_sources_and_parent_initializers_are_hashed_without_importing(source_tree):
    files, external = source_manifest(source_tree)
    assert set(files) == {"probe/__init__.py", "probe/owner.py", "probe/entry.py", "probe/branch.py", "probe/leaf.py"}
    assert external == {"json"}
    before = snapshot_digest(files)
    (source_tree / "probe/leaf.py").write_text("value = 2\n")
    assert snapshot_digest(source_manifest(source_tree)[0]) != before
    before = source_manifest(source_tree)[0]
    (source_tree / "probe/owner.py").write_text("NAME = 'two'\n")
    assert source_manifest(source_tree)[0] != before


def test_source_closure_is_order_independent_and_excludes_unrelated_files(source_tree):
    (source_tree / "probe/unrelated.py").write_text("unrelated = True\n")
    assert source_manifest(source_tree, ("probe.entry", "probe.leaf")) == source_manifest(
        source_tree, ("probe.leaf", "probe.entry", "probe.entry"))
    assert "probe/unrelated.py" not in source_manifest(source_tree)[0]


def test_nested_and_from_package_imports_are_included(source_tree):
    (source_tree / "probe/entry.py").write_text("from . import leaf\ndef action():\n    from .branch import action\n")
    files, _ = source_manifest(source_tree)
    assert {"probe/leaf.py", "probe/branch.py"}.issubset(files)


@pytest.mark.parametrize("body", ["from .missing import action\n", "def invalid(:\n", "from ....outside import value\n"])
def test_missing_invalid_or_outside_source_imports_fail_closed(source_tree, body):
    (source_tree / "probe/entry.py").write_text(body)
    with pytest.raises(CodeGraphProcessError):
        source_manifest(source_tree)


def distribution_fixture(root, name, *, module=None, version="1.0", requires=()):
    module = module or name.replace("-", "_")
    package, info = root / module, root / f"{module}-{version}.dist-info"
    package.mkdir(exist_ok=True)
    info.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("version = 'unchanged'\n")
    (package / "binding.so").write_bytes(b"controlled installed binary bytes")
    (info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n" + "".join(f"Requires-Dist: {r}\n" for r in requires))
    paths = tuple(PackagePath(str(p.relative_to(root))) for p in (package / "__init__.py", package / "binding.so", info / "METADATA"))
    return SimpleNamespace(metadata={"Name": name}, version=version, requires=requires, files=paths,
        locate_file=lambda path: root / str(path))


@pytest.fixture
def projection_runtime(source_tree, monkeypatch):
    (source_tree / "probe/entry.py").write_text("from .branch import action\nimport toy_grammar\n")
    dist = distribution_fixture(source_tree, "toy-grammar")
    monkeypatch.setattr(dependencies, "PROJECT_ROOT", source_tree)
    monkeypatch.setattr(dependencies, "ENTRYPOINTS", ("probe.entry",))
    monkeypatch.setattr(dependencies.metadata, "distributions", lambda: iter([dist]))
    return source_tree


def installed_manifest(monkeypatch, distributions, modules):
    monkeypatch.setattr(dependencies.metadata, "distributions", lambda: iter(distributions))
    reader = DependencyFiles()
    result = dependencies.installed_dependency_manifest(modules, reader)
    reader.finish()
    return result


def test_same_version_different_installed_bytes_change_dependency_pin(tmp_path, monkeypatch):
    dist = distribution_fixture(tmp_path, "toy-grammar")
    before = installed_manifest(monkeypatch, [dist], {"toy_grammar"})
    (tmp_path / "toy_grammar/binding.so").write_bytes(b"a different same-version build")
    after = installed_manifest(monkeypatch, [dist], {"toy_grammar"})
    assert before != after and before["toy-grammar"]["version"] == after["toy-grammar"]["version"] == "1.0"


def test_transitive_installed_requirements_and_markers_are_resolved(tmp_path, monkeypatch):
    core = distribution_fixture(tmp_path, "toy-core")
    grammar = distribution_fixture(tmp_path, "toy-grammar", requires=("toy-core==1.0", "absent; python_version < '3'", "optional; extra == 'docs'"))
    assert set(installed_manifest(monkeypatch, [grammar, core], {"toy_grammar", "json"})) == {"toy-grammar", "toy-core"}
    before = installed_manifest(monkeypatch, [grammar, core], {"toy_grammar"})
    (tmp_path / "toy_core/binding.so").write_bytes(b"changed transitive binary")
    assert before != installed_manifest(monkeypatch, [grammar, core], {"toy_grammar"})


@pytest.mark.parametrize("requirement", ["absent>=1", "toy-core==2.0", "not a requirement !!!"])
def test_missing_mismatched_or_invalid_dependencies_do_not_get_a_fingerprint(tmp_path, monkeypatch, requirement):
    grammar = distribution_fixture(tmp_path, "toy-grammar", requires=(requirement,))
    core = distribution_fixture(tmp_path, "toy-core")
    with pytest.raises(CodeGraphProcessError):
        installed_manifest(monkeypatch, [grammar, core], {"toy_grammar"})


def test_missing_record_file_and_ambiguous_module_owner_are_rejected(tmp_path, monkeypatch):
    first = distribution_fixture(tmp_path, "toy-first", module="shared")
    second = distribution_fixture(tmp_path, "toy-second", module="shared")
    with pytest.raises(CodeGraphProcessError):
        installed_manifest(monkeypatch, [first, second], {"shared"})
    (tmp_path / "shared/binding.so").unlink()
    with pytest.raises(CodeGraphProcessError):
        installed_manifest(monkeypatch, [first], {"shared"})


@pytest.mark.parametrize("failure", [CodeIndexCancelled, PermissionError, KeyboardInterrupt])
def test_metadata_inventory_keeps_application_control_failures_distinct(tmp_path, monkeypatch, failure):
    grammar = distribution_fixture(tmp_path, "toy-grammar")
    metadata_started = []
    def distributions():
        metadata_started.append(True)
        yield grammar
    def check():
        if metadata_started:
            raise failure("authority changed during distribution inventory")
    monkeypatch.setattr(dependencies.metadata, "distributions", distributions)
    reader = DependencyFiles(check_current=check)
    monkeypatch.setattr(reader, "check_current", lambda **_: check())
    with pytest.raises(failure):
        dependencies.installed_dependency_manifest({"toy_grammar"}, reader)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "oversized"])
def test_dependency_reads_reject_nonregular_or_unbounded_files(tmp_path, kind):
    import os
    path = tmp_path / "dependency"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"source")
        path.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        with path.open("wb") as file:
            file.truncate(65 * 1024 * 1024)
    with pytest.raises(CodeGraphProcessError):
        DependencyFiles().read(path)


def test_replaced_file_is_detected_at_end_of_whole_manifest(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b"one")
    reader = DependencyFiles()
    reader.read(path)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"one")
    replacement.replace(path)
    with pytest.raises(CodeGraphProcessError):
        reader.finish()


def test_ancestor_symlink_and_total_read_budget_are_rejected(tmp_path, monkeypatch):
    from apps.api.app.infrastructure.system_image import code_graph_dependency_files as file_module
    parent = tmp_path / "actual"
    parent.mkdir()
    (parent / "file").write_bytes(b"source")
    alias = tmp_path / "alias"
    alias.symlink_to(parent, target_is_directory=True)
    with pytest.raises(CodeGraphProcessError):
        DependencyFiles().read(alias / "file")
    monkeypatch.setattr(file_module, "MAX_DEPENDENCY_BYTES", 5)
    with pytest.raises(CodeGraphProcessError):
        DependencyFiles().read(parent / "file")


def test_final_callback_is_not_skipped_after_fast_reads(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"source")
    calls = []
    def check():
        calls.append(True)
        if len(calls) > 1:
            raise CodeIndexCancelled("cancelled before returning the complete manifest")
    reader = DependencyFiles(check_current=check)
    reader.read(path)
    with pytest.raises(CodeIndexCancelled):
        reader.finish()


@pytest.mark.parametrize("failure", [CodeIndexCancelled, PermissionError, KeyboardInterrupt])
def test_dependency_scan_does_not_swallow_current_authority_or_cancellation(tmp_path, failure):
    path = tmp_path / "source"
    path.write_bytes(b"source")
    def check():
        raise failure("controlled current-state rejection")
    with pytest.raises(failure):
        DependencyFiles(check_current=check).read(path)


@pytest.mark.parametrize("path", ["probe/leaf.py", "toy_grammar/binding.so"])
def test_adapter_generation_fingerprint_tracks_actual_dependencies(projection_runtime, tmp_path, monkeypatch, path):
    from apps.api.tests.test_code_index_session import fixture
    adapter, _, log = fixture(tmp_path, monkeypatch)
    before = adapter.projection_fingerprint()
    dependency = projection_runtime / path
    original = dependency.read_bytes()
    dependency.write_bytes(original + b"\n# changed same-version projection dependency\n")
    assert adapter.projection_fingerprint() != before
    dependency.write_bytes(original)
    assert adapter.projection_fingerprint() == before
    assert not log.exists()


@pytest.mark.parametrize("path", ["probe/leaf.py", "toy_grammar/binding.so"])
def test_changed_dependency_cannot_prepare_the_original_generation(projection_runtime, tmp_path, monkeypatch, path):
    from apps.api.app.infrastructure.system_image import codebase_memory_index_session as sessions
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryError
    from apps.api.tests.test_code_index_session import fixture
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    copies = []
    stage = sessions.stage_code_graph_executable
    def owned_copy(*args, **kwargs):
        copied = stage(*args, **kwargs)
        copies.append(copied)
        return copied
    monkeypatch.setattr(sessions, "stage_code_graph_executable", owned_copy)
    index = adapter.open_index([unit], check_current=lambda: None, namespace="nasus_" + "a" * 32,
        provider_fingerprint=adapter.projection_fingerprint())
    dependency = projection_runtime / path
    dependency.write_bytes(dependency.read_bytes() + b"\n# different dependency\n")
    with pytest.raises(CodebaseMemoryError, match="projection policy changed"):
        index.prepare_index()
    assert index.status().state == "failed" and not log.exists()
    assert not index._root.exists() and not index._cache.exists()
    assert len(copies) == 1 and not copies[0].exists() and not copies[0].parent.exists()
    index.close()


@pytest.mark.parametrize("failure", [CodeIndexCancelled, PermissionError, KeyboardInterrupt])
def test_adapter_fingerprint_rechecks_authority_during_the_dependency_inventory(projection_runtime, tmp_path, monkeypatch, failure):
    from apps.api.tests.test_code_index_session import fixture
    adapter, _, log = fixture(tmp_path, monkeypatch)
    def check():
        if dependencies.PROJECT_ROOT / "probe/entry.py" in current_reader.records:
            raise failure("stopped after the inventory began")
    current_reader = DependencyFiles(check_current=check)
    monkeypatch.setattr(dependencies, "DependencyFiles", lambda **_: current_reader)
    with pytest.raises(failure):
        adapter.projection_fingerprint(check_current=check)
    assert not log.exists()
