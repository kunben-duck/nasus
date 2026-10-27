"""Owned deployment observations are not fixture, oracle or execution authority."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re

from .acceptance_specification import acceptance_digest


ENVIRONMENT_SCHEMA = "nasus.owned-target-environment.v1"
OWNER_LABEL = "nasus.target.environment_owner"


class NativeEnvironmentInvalid(ValueError):
    pass


def _require(value):
    if not value:
        raise NativeEnvironmentInvalid("owned target environment could not be verified")


@dataclass(frozen=True)
class OwnedDependency:
    role: str
    container_id: str
    image_id: str
    user: str


@dataclass(frozen=True)
class OwnedEnvironment:
    project_id: str
    environment_id: str
    owner: str
    prefix: str
    container_id: str
    image_id: str
    network_id: str
    dependencies: tuple[OwnedDependency, ...]

    def __post_init__(self):
        _require(all(type(value) is str and 1 <= len(value) <= 128 and value == value.strip()
            and not any(ord(char) <= 32 for char in value) for value in (self.project_id, self.environment_id)))
        _require(type(self.owner) is str and re.fullmatch(r"[0-9a-f]{16}", self.owner)
            and type(self.prefix) is str and self.prefix in {"nasus-exweb-" + self.owner, "nasus-target-" + self.owner})
        _require(type(self.dependencies) is tuple and len(self.dependencies) == 2
            and all(type(item) is OwnedDependency for item in self.dependencies)
            and all(type(item.role) is str for item in self.dependencies)
            and {item.role for item in self.dependencies} == {"pg", "redis"})
        containers = [self.container_id, *(item.container_id for item in self.dependencies)]
        _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) for value in [*containers, self.network_id])
            and len(set(containers)) == len(containers) and self.network_id not in containers)
        _require(all(type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
            for value in [self.image_id, *(item.image_id for item in self.dependencies)]))
        _require(all(type(item.user) is str and re.fullmatch(r"[1-9][0-9]{0,4}:[1-9][0-9]{0,4}", item.user)
            and all(int(part) <= 65535 for part in item.user.split(":")) for item in self.dependencies))

    @property
    def digest(self):
        return acceptance_digest(asdict(self))


@dataclass(frozen=True)
class NativeEnvironmentObservation:
    inventory: dict
    inventory_hash: str
    observed_at: str

    def __post_init__(self):
        value = self.inventory
        false_fields = ("host_ports_exposed", "developer_resources_used", "model_outbound_permitted", "execution_authorized",
            "external_egress_denial_verified", "host_access_denial_verified", "dependency_health_verified",
            "fixtures_verified", "locators_verified", "business_coverage_verified")
        counts = ("automated_count", "executed_on_target_count", "passed_count")
        _require(type(value) is dict and set(value) == {"schema", "project_id", "environment_id", "operator_policy_digest",
            "artifact_hash", "target", "dependency_instances", "network_id", "namespace_origin",
            "native_artifact_attested", "isolation_attested", *false_fields, *counts}
            and value.get("schema") == ENVIRONMENT_SCHEMA
            and acceptance_digest(value) == self.inventory_hash
            and value.get("native_artifact_attested") is True
            and value.get("isolation_attested") is True
            and all(value.get(key) is False for key in false_fields)
            and all(type(value.get(key)) is int and value[key] == 0 for key in counts))
        _require(all(type(value[key]) is str and 1 <= len(value[key]) <= 128
            and not any(ord(char) <= 32 for char in value[key]) for key in ("project_id", "environment_id")))
        _require(value["namespace_origin"] == "http://127.0.0.1:8080"
            and all(type(value[key]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value[key])
                for key in ("operator_policy_digest", "artifact_hash"))
            and type(value["network_id"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["network_id"]))
        target, dependencies = value["target"], value["dependency_instances"]
        _require(type(target) is dict and set(target) == {"container_id", "image_id", "started_at", "user"}
            and target["user"] == "65534:65534" and type(dependencies) is list and len(dependencies) == 2
            and all(type(item) is dict and set(item) == {"container_id", "image_id", "started_at", "user", "role"}
                and type(item["role"]) is str for item in dependencies)
            and {item["role"] for item in dependencies} == {"pg", "redis"})
        instances = [target, *dependencies]
        for item in instances:
            _require(type(item["container_id"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["container_id"])
                and type(item["image_id"]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", item["image_id"])
                and type(item["started_at"]) is str and 1 <= len(item["started_at"]) <= 64
                and type(item["user"]) is str and re.fullmatch(r"[1-9][0-9]{0,4}:[1-9][0-9]{0,4}", item["user"])
                and all(int(part) <= 65535 for part in item["user"].split(":")))
        _require(len({item["container_id"] for item in instances}) == len(instances)
            and value["network_id"] not in {item["container_id"] for item in instances}
            and type(self.observed_at) is str and len(self.observed_at) <= 64)
        try:
            instant = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
            _require(instant.tzinfo is not None and instant.utcoffset() == timezone.utc.utcoffset(instant))
        except (ValueError, TypeError):
            raise NativeEnvironmentInvalid("invalid native environment observation time") from None
