"""An operator-owned registry, never a request-selected Docker ID or filesystem path."""
from dataclasses import fields
import json
import os
from pathlib import Path
import stat

from ...domain.quality_loop.native_environment import NativeEnvironmentInvalid, OwnedDependency, OwnedEnvironment, _require
from .native_maven_build import bounded_command
from .owned_target_environment import OwnedTargetEnvironmentInspector


REGISTRY_SCHEMA = "nasus.owned-target-registry.v1"
MAX_REGISTRY_BYTES = 256 * 1024


def read_registry(path):
    _require(type(path) is str and path and Path(path).is_absolute())
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value)
            value[key] = item
        return value
    def invalid(_):
        raise NativeEnvironmentInvalid("invalid operator registry")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as file:
            before = os.fstat(file.fileno())
            _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_mode & 0o077 == 0 and 0 < before.st_size <= MAX_REGISTRY_BYTES)
            body = file.read(MAX_REGISTRY_BYTES + 1)
            after = os.fstat(file.fileno())
            _require(len(body) == before.st_size and (before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_ino, after.st_size, after.st_mtime_ns))
        raw = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=unique, parse_constant=invalid)
        _require(type(raw) is dict and set(raw) == {"schema", "environments"} and raw["schema"] == REGISTRY_SCHEMA
            and type(raw["environments"]) is list and 1 <= len(raw["environments"]) <= 32)
        specs, identities, resources = [], set(), set()
        for entry in raw["environments"]:
            _require(type(entry) is dict and set(entry) == {item.name for item in fields(OwnedEnvironment)}
                and type(entry["dependencies"]) is list)
            dependencies = []
            for item in entry["dependencies"]:
                _require(type(item) is dict and set(item) == {field.name for field in fields(OwnedDependency)})
                dependencies.append(OwnedDependency(**item))
            spec = OwnedEnvironment(**{**entry, "dependencies": tuple(dependencies)})
            key = (spec.project_id, spec.environment_id)
            cohort = {spec.prefix, spec.owner, spec.container_id, spec.network_id, *(item.container_id for item in spec.dependencies)}
            _require(key not in identities and not resources.intersection(cohort))
            identities.add(key)
            resources.update(cohort)
            specs.append(spec)
        return tuple(specs)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise NativeEnvironmentInvalid("operator target registry is unavailable or invalid") from None


class ConfiguredOwnedTargetEnvironments:
    def __init__(self, *, command=bounded_command, registry_path=None):
        self.command, self.registry_path = command, registry_path

    def _spec(self, project_id, environment_id, require_work):
        require_work()
        path = self.registry_path if self.registry_path is not None else os.environ.get("NASUS_TARGET_ENVIRONMENT_REGISTRY", "")
        specs = read_registry(path)
        matches = [spec for spec in specs if (spec.project_id, spec.environment_id) == (project_id, environment_id)]
        _require(len(matches) == 1)
        require_work()
        return matches[0]

    def policy_digest(self, project_id, environment_id, *, require_work):
        return self._spec(project_id, environment_id, require_work).digest

    def inspect(self, project_id, environment_id, artifact_hash, *, require_work):
        spec = self._spec(project_id, environment_id, require_work)
        result = OwnedTargetEnvironmentInspector(spec, command=self.command).inspect(artifact_hash, require_work=require_work)
        _require(self._spec(project_id, environment_id, require_work).digest == spec.digest)
        require_work()
        return result

    def inspect_health(self, project_id, environment_id, artifact_hash, *, require_work):
        from .owned_target_health import OwnedTargetHealthInspector
        spec = self._spec(project_id, environment_id, require_work)
        result = OwnedTargetHealthInspector(spec, command=self.command).inspect(artifact_hash, require_work=require_work)
        _require(self._spec(project_id, environment_id, require_work).digest == spec.digest)
        require_work()
        return result
