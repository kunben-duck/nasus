"""Health observations of exact owned instances, never execution permission."""
import base64
from dataclasses import dataclass

from .acceptance_specification import acceptance_digest
from .http_runner_oracles import strict_http_json
from .native_environment import NativeEnvironmentInvalid, NativeEnvironmentObservation
from ..shared.native_build_source import byte_digest


HEALTH_SCHEMA = "nasus.owned-target-health.v1"
HEALTH_PROBES = {"pg": "postgres_select_one", "redis": "redis_ping", "target": "target_actuator_health"}
MAX_HEALTH_RESPONSE_BYTES = 16 * 1024


def _require(value):
    if not value:
        raise NativeEnvironmentInvalid("original target health observation could not be verified")


def health_response(check):
    _require(type(check) is dict and set(check) == {"role", "probe", "container_id", "image_id", "started_at",
        "response_base64", "response_hash", "byte_count"})
    _require(type(check["role"]) is str and check["role"] in HEALTH_PROBES
        and check["probe"] == HEALTH_PROBES[check["role"]]
        and type(check["response_base64"]) is str and len(check["response_base64"]) <= 4 * ((MAX_HEALTH_RESPONSE_BYTES + 2) // 3)
        and type(check["byte_count"]) is int and 0 < check["byte_count"] <= MAX_HEALTH_RESPONSE_BYTES)
    try:
        body = base64.b64decode(check["response_base64"], validate=True)
        _require(base64.b64encode(body).decode("ascii") == check["response_base64"]
            and len(body) == check["byte_count"] and byte_digest(body) == check["response_hash"])
    except (ValueError, UnicodeError):
        raise NativeEnvironmentInvalid("invalid original health response bytes") from None
    return body


def healthy(check):
    body = health_response(check)
    if check["role"] == "pg":
        return body == b"1\n"
    if check["role"] == "redis":
        return body == b"PONG\n"
    try:
        raw, status = body.rsplit(b"\n", 1)
        _require(len(status) == 3 and status.isdigit() and 100 <= int(status) <= 599)
        parsed = strict_http_json(raw.decode("utf-8", errors="strict"))
        _require(type(parsed) is dict)
        return status == b"200" and parsed.get("status") == "UP"
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise NativeEnvironmentInvalid("target health response is not a complete original HTTP observation") from None


@dataclass(frozen=True)
class NativeEnvironmentHealthObservation:
    inventory: dict
    inventory_hash: str
    checks: tuple[dict, ...]
    observed_at: str

    def __post_init__(self):
        NativeEnvironmentObservation(self.inventory, self.inventory_hash, self.observed_at)
        _require(type(self.checks) is tuple and len(self.checks) == 3
            and tuple(item.get("role") for item in self.checks if type(item) is dict) == ("pg", "redis", "target"))
        members = {item["role"]: item for item in self.inventory["dependency_instances"]}
        members["target"] = self.inventory["target"]
        for check in self.checks:
            health_response(check)
            member = members[check["role"]]
            _require(all(check[key] == member[key] for key in ("container_id", "image_id", "started_at")))
            healthy(check)

    @property
    def dependency_health_verified(self):
        return all(healthy(item) for item in self.checks[:2])

    @property
    def target_health_verified(self):
        return healthy(self.checks[2])

    def payload(self):
        return {"schema": HEALTH_SCHEMA, "inventory": self.inventory, "inventory_hash": self.inventory_hash,
            "checks": list(self.checks), "observed_at": self.observed_at}

    @property
    def content_hash(self):
        return acceptance_digest(self.payload())
