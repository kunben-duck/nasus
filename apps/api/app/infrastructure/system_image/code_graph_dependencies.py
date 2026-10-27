"""Projection source and installed dependency bytes, not a hermetic OS image."""
import ast
from importlib import metadata, util
from pathlib import Path, PurePosixPath
import re
import sys
import sysconfig

from packaging.requirements import InvalidRequirement, Requirement

from .code_graph_dependency_files import DependencyFiles
from .code_graph_process import CodeGraphProcessError


PROJECT_ROOT = Path(__file__).resolve().parents[5]
ENTRYPOINTS = (
    "apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence",
    "apps.api.app.infrastructure.system_image.composite_code_intelligence",
    "apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence",
    "apps.api.app.application.system_image.code_entity_registry",
)
MAX_SOURCE_FILES = 2048
MAX_DISTRIBUTIONS = 256
MAX_INSTALLED_DISTRIBUTIONS = 8192
MAX_INSTALLED_FILE_REFERENCES = 262144


def _module_path(root, name):
    if not name or any(not part.isidentifier() for part in name.split(".")):
        raise CodeGraphProcessError("invalid code projection module")
    path = root.joinpath(*name.split("."))
    if path.with_suffix(".py").exists():
        return path.with_suffix(".py")
    if (path / "__init__.py").exists():
        return path / "__init__.py"
    if path.is_dir():
        return None
    raise CodeGraphProcessError("code projection source dependency is missing")


def projection_source_manifest(root, entries, reader):
    root = Path(root).resolve()
    prefixes = {entry.split(".")[0] for entry in entries}
    pending, seen, files, external = set(entries), set(), {}, set()
    while pending:
        reader.check_current()
        name = min(pending)
        pending.remove(name)
        if name in seen:
            continue
        seen.add(name)
        if len(seen) > MAX_SOURCE_FILES:
            raise CodeGraphProcessError("code projection source closure exceeds its budget")
        path = _module_path(root, name)
        parts = name.split(".")
        for length in range(1, len(parts)):
            if root.joinpath(*parts[:length], "__init__.py").exists():
                pending.add(".".join(parts[:length]))
        if path is None:
            continue
        key = path.relative_to(root).as_posix()
        digest, data = reader.read(path, capture=True, limit=2 * 1024 * 1024)
        files[key] = digest
        try:
            tree = ast.parse(data, filename=key)
        except (SyntaxError, ValueError, UnicodeError) as error:
            raise CodeGraphProcessError("code projection source dependency cannot be parsed") from error
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                try:
                    base = util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
                except (ImportError, ValueError) as error:
                    raise CodeGraphProcessError("code projection source import is outside its package") from error
                imports = [base] if base else []
                if base and base.split(".")[0] in prefixes:
                    for alias in node.names:
                        candidate = root.joinpath(*base.split("."), alias.name)
                        if candidate.with_suffix(".py").exists() or candidate.is_dir():
                            imports.append(base + "." + alias.name)
            else:
                continue
            for imported in imports:
                if imported.split(".")[0] in prefixes:
                    pending.add(imported)
                elif imported != "__future__":
                    external.add(imported.split(".")[0])
    return dict(sorted(files.items())), external


def _normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _package_module(path):
    parts = PurePosixPath(str(path)).parts
    if not parts or ".." in parts or parts[0].endswith((".dist-info", ".egg-info")):
        return None
    top = parts[0].removesuffix(".py")
    return top if top.isidentifier() else None


def _stdlib_module(name):
    if name in sys.builtin_module_names:
        return True
    spec = util.find_spec(name)
    if spec is None:
        return False
    if spec.origin in {"built-in", "frozen"}:
        return True
    if not spec.origin:
        return False
    origin = Path(spec.origin).resolve()
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    return stdlib in origin.parents and not any(part in {"site-packages", "dist-packages"} for part in origin.parts)


def installed_dependency_manifest(module_names, reader):
    owners, available = {}, {}
    file_references = 0
    try:
        distributions = iter(metadata.distributions())
    except (TypeError, OSError) as error:
        raise CodeGraphProcessError("code projection installed metadata is unavailable") from error
    while True:
        reader.check_current()
        try:
            dist = next(distributions)
            name = _normalized(dist.metadata["Name"])
            paths = dist.files or ()
        except StopIteration:
            break
        except (KeyError, TypeError, OSError) as error:
            raise CodeGraphProcessError("code projection installed metadata is unavailable") from error
        if name in available or len(available) >= MAX_INSTALLED_DISTRIBUTIONS:
            raise CodeGraphProcessError("code projection has duplicate installed distributions")
        available[name] = dist
        for path in paths:
            reader.check_current()
            file_references += 1
            if file_references > MAX_INSTALLED_FILE_REFERENCES:
                raise CodeGraphProcessError("code projection installed metadata exceeds its budget")
            module = _package_module(path)
            if module:
                owners.setdefault(module, set()).add(name)
    pending = {}
    for module in sorted(module_names):
        names = owners.get(module, set())
        if len(names) > 1:
            raise CodeGraphProcessError("code projection module has ambiguous installed ownership")
        if names:
            pending[next(iter(names))] = set()
        elif not _stdlib_module(module):
            raise CodeGraphProcessError("code projection module has no installed dependency record")
    result, processed_extras = {}, {}
    while pending:
        reader.check_current()
        name = min(pending)
        extras = pending.pop(name)
        if name in processed_extras and extras.issubset(processed_extras[name]):
            continue
        extras = extras | processed_extras.get(name, set())
        processed_extras[name] = extras
        if len(processed_extras) > MAX_DISTRIBUTIONS or name not in available:
            raise CodeGraphProcessError("code projection installed dependency closure is incomplete")
        dist = available[name]
        if name not in result:
            files, skipped = {}, 0
            for item in dist.files or ():
                relative = PurePosixPath(str(item))
                if relative.suffix == ".pyc" or "__pycache__" in relative.parts:
                    continue
                # Console entry points outside site-packages are not executed by
                # this adapter; its separately pinned native executable is.
                if ".." in relative.parts:
                    if len(relative.parts) > 2 and relative.parts[-2] == "bin" and all(part == ".." for part in relative.parts[:-2]):
                        skipped += 1
                        continue
                    raise CodeGraphProcessError("code projection installed file is outside its package root")
                if relative.is_absolute() or relative.as_posix() in files:
                    raise CodeGraphProcessError("invalid code projection installed file inventory")
                digest, _ = reader.read(Path(dist.locate_file(item)))
                files[relative.as_posix()] = digest
            if not files:
                raise CodeGraphProcessError("code projection dependency has no installed files")
            result[name] = {"version": dist.version, "files": dict(sorted(files.items())), "external_entrypoints_excluded": skipped}
        for raw in dist.requires or ():
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as error:
                raise CodeGraphProcessError("invalid code projection dependency requirement") from error
            if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in extras | {""}):
                continue
            dependency = _normalized(requirement.name)
            if (dependency not in available or requirement.url
                    or not requirement.specifier.contains(available[dependency].version, prereleases=True)):
                raise CodeGraphProcessError("code projection installed dependency does not match its requirement")
            if dependency not in processed_extras or not set(requirement.extras).issubset(processed_extras[dependency]):
                pending.setdefault(dependency, set()).update(requirement.extras)
    return dict(sorted(result.items()))


def projection_dependency_manifest(*, check_current=None, entrypoints=None):
    reader = DependencyFiles(check_current=check_current)
    sources, external = projection_source_manifest(PROJECT_ROOT, ENTRYPOINTS if entrypoints is None else entrypoints, reader)
    packages = installed_dependency_manifest(external, reader)
    reader.finish()
    return {"schema": "nasus.code-projection-dependencies.v1", "sources": sources, "python_packages": packages,
        "python": {"implementation": sys.implementation.name, "version": sys.version,
                   "cache_tag": sys.implementation.cache_tag, "platform": sys.platform},
        "inventory": {"source_files": len(sources), "installed_files": sum(len(item["files"]) for item in packages.values()),
                      "bytes_hashed": reader.bytes_read},
        "scope": "static_import_closure_and_record_listed_requirements_not_hermetic_runtime"}
