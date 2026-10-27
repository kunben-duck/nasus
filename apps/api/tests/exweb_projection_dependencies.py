"""Evidence for the local projection build, not exweb's runtime dependencies."""
import hashlib
from importlib.metadata import distribution
from pathlib import Path

from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image.code_graph_dependencies import PROJECT_ROOT, projection_dependency_manifest
from apps.api.app.infrastructure.system_image.code_graph_executable import code_graph_executable_digest


def verify_projection_dependencies(native):
    manifest = projection_dependency_manifest()
    assert manifest["schema"] == "nasus.code-projection-dependencies.v1"
    assert manifest["scope"] == "static_import_closure_and_record_listed_requirements_not_hermetic_runtime"
    for name in ("apps/api/app/application/system_image/code_entity_registry.py",
                 "apps/api/app/domain/system_image/code_identity.py",
                 "apps/api/app/infrastructure/system_image/code_graph_dependencies.py",
                 "apps/api/app/infrastructure/system_image/code_graph_dependency_files.py"):
        assert manifest["sources"][name] == hashlib.sha256((PROJECT_ROOT / name).read_bytes()).hexdigest()
    grammar_files = 0
    for name in ("tree-sitter", "tree-sitter-python", "tree-sitter-java",
                 "tree-sitter-javascript", "tree-sitter-typescript", "tree-sitter-go"):
        package = manifest["python_packages"][name]
        files = [path for path in package["files"] if Path(path).suffix in {".so", ".pyd"}]
        assert files, name
        installed = distribution(name)
        for path in files:
            assert package["files"][path] == hashlib.sha256(Path(installed.locate_file(path)).read_bytes()).hexdigest()
            grammar_files += 1
    expected = snapshot_digest({"provider": native.provider,
        "binary_sha256": code_graph_executable_digest(native.prepared_executable()), "dependencies": manifest,
        "index_mode": native.config.index_mode, "max_entities": native.config.max_entities,
        "max_relationships": native.config.max_relationships, "max_relationship_queries": native.config.max_relationship_queries,
        "page_size": native.config.page_size, "schema": "nasus.code-index-generation.v2"})
    assert native.projection_fingerprint() == expected
    return {"fingerprint_schema": "nasus.code-index-generation.v2", "provider_fingerprint": expected,
        "manifest_schema": manifest["schema"], "manifest_digest": snapshot_digest(manifest),
        **manifest["inventory"], "installed_distributions": len(manifest["python_packages"]),
        "grammar_binary_files_verified": grammar_files, "scope": manifest["scope"],
        "hermetic_runtime": False, "target_runtime_dependencies_resolved": False}
