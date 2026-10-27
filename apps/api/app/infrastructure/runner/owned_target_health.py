"""Fixed local read-only probes; no caller-selected URL, SQL, container or credentials."""
import base64
from copy import deepcopy
from datetime import datetime, timezone

from ...domain.quality_loop.native_environment import _require
from ...domain.quality_loop.native_environment_health import (
    HEALTH_PROBES, MAX_HEALTH_RESPONSE_BYTES, NativeEnvironmentHealthObservation,
)
from ...domain.shared.native_build_source import byte_digest
from .native_maven_build import bounded_command
from .owned_target_environment import OwnedTargetEnvironmentInspector


# Only the owned PG process environment supplies credentials; no secret enters argv or output.
POSTGRES_SELECT_ONE = ('case "$POSTGRES_USER" in ""|*[!A-Za-z0-9_]*) exit 2;; esac; '
    'case "$POSTGRES_DB" in ""|*[!A-Za-z0-9_]*) exit 2;; esac; '
    'unset PGSERVICE PGSERVICEFILE PGHOST PGPORT; '
    'export PGPASSWORD="$POSTGRES_PASSWORD" PGHOSTADDR=127.0.0.1 PGCONNECT_TIMEOUT=5 '
    'PGOPTIONS="-c statement_timeout=5000"; '
    'exec psql --no-psqlrc --host=127.0.0.1 --port=5432 --username="$POSTGRES_USER" '
    '--dbname="$POSTGRES_DB" --set=ON_ERROR_STOP=1 --tuples-only --no-align --command="SELECT 1"')


class OwnedTargetHealthInspector:
    def __init__(self, spec, *, command=bounded_command):
        self.spec = spec
        self.inspector = OwnedTargetEnvironmentInspector(spec, command=command)

    def inspect(self, artifact_hash, *, require_work):
        before = self.inspector.inspect(artifact_hash, require_work=require_work)
        members = {item["role"]: item for item in before.inventory["dependency_instances"]}
        members["target"] = before.inventory["target"]
        queries = {"pg": ["sh", "-c", POSTGRES_SELECT_ONE],
            "redis": ["redis-cli", "--raw", "-h", "127.0.0.1", "-p", "6379", "PING"],
            "target": ["curl", "--disable", "--noproxy", "*", "--silent", "--show-error", "--max-time", "5",
                "--max-filesize", str(MAX_HEALTH_RESPONSE_BYTES - 4), "--proto", "=http", "--request", "GET",
                "--header", "Accept-Encoding: identity", "--write-out", "\n%{http_code}",
                "--url", "http://127.0.0.1:8080/actuator/health"]}
        checks = []
        for role in ("pg", "redis", "target"):
            member = members[role]
            body = self.inspector._command(["exec", "--user", member["user"], member["container_id"], *queries[role]],
                require_work, MAX_HEALTH_RESPONSE_BYTES)
            checks.append({"role": role, "probe": HEALTH_PROBES[role],
                **{key: member[key] for key in ("container_id", "image_id", "started_at")},
                "response_base64": base64.b64encode(body).decode("ascii"), "response_hash": byte_digest(body), "byte_count": len(body)})
        after = self.inspector.inspect(artifact_hash, require_work=require_work)
        _require(after.inventory == before.inventory and after.inventory_hash == before.inventory_hash)
        require_work()
        return NativeEnvironmentHealthObservation(deepcopy(after.inventory), after.inventory_hash, tuple(checks),
            datetime.now(timezone.utc).isoformat())
