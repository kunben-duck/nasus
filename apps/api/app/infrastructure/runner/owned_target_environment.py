"""Inspect exact operator-owned resources; never deploy, request HTTP or recover them."""
from datetime import datetime, timezone
import json
import re

from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.native_environment import (
    ENVIRONMENT_SCHEMA, OWNER_LABEL, NativeEnvironmentInvalid, NativeEnvironmentObservation, OwnedEnvironment, _require,
)
from .native_maven_build import NativeBuildFailure, bounded_command


# Environment variables and trailing JVM arguments can contain credentials.
CONTAINER_FORMAT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
    '"Running":{{json .State.Running}},"StartedAt":{{json .State.StartedAt}},'
    '"User":{{json .Config.User}},"Labels":{{json .Config.Labels}},'
    '"Path":{{json .Path}},"Args":{{if and (eq .Path "java") (ge (len .Args) 2)}}'
    '{{json (slice .Args 0 2)}}{{else}}[]{{end}},"HostConfig":{'
    '"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},"CapDrop":{{json .HostConfig.CapDrop}},'
    '"CapAdd":{{json .HostConfig.CapAdd}},"Privileged":{{json .HostConfig.Privileged}},'
    '"SecurityOpt":{{json .HostConfig.SecurityOpt}},"NetworkMode":{{json .HostConfig.NetworkMode}},'
    '"PortBindings":{{json .HostConfig.PortBindings}},"PidMode":{{json .HostConfig.PidMode}},'
    '"IpcMode":{{json .HostConfig.IpcMode}},"UTSMode":{{json .HostConfig.UTSMode}},'
    '"Memory":{{json .HostConfig.Memory}},"NanoCpus":{{json .HostConfig.NanoCpus}},'
    '"PidsLimit":{{json .HostConfig.PidsLimit}},"Tmpfs":{{json .HostConfig.Tmpfs}}},"Mounts":{{json .Mounts}},'
    '"Networks":{{json .NetworkSettings.Networks}},"Ports":{{json .NetworkSettings.Ports}}}')
NETWORK_FORMAT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Internal":{{json .Internal}},'
    '"Driver":{{json .Driver}},"Scope":{{json .Scope}},"Attachable":{{json .Attachable}},'
    '"Labels":{{json .Labels}},"Containers":{{json .Containers}}}')


def _object(body):
    def unique(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result
    def invalid(_):
        raise NativeEnvironmentInvalid("invalid native environment JSON")
    try:
        value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=unique, parse_constant=invalid)
        _require(type(value) is dict)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise NativeEnvironmentInvalid("owned target inspection returned invalid metadata") from None


class OwnedTargetEnvironmentInspector:
    def __init__(self, spec: OwnedEnvironment, *, command=bounded_command):
        self.spec, self.command = spec, command

    def _command(self, args, require_work, max_bytes=256 * 1024):
        callback_failed = False
        def current():
            nonlocal callback_failed
            try:
                require_work()
            except BaseException:
                callback_failed = True
                raise
        try:
            code, body = self.command(["docker", *args], timeout=10, max_bytes=max_bytes, require_work=current)
        except NativeEnvironmentInvalid:
            raise
        except (NativeBuildFailure, OSError):
            if callback_failed:
                raise
            raise NativeEnvironmentInvalid("owned target inspection is unavailable") from None
        _require(code == 0 and type(body) is bytes and len(body) <= max_bytes)
        require_work()
        return body

    def _container(self, ident, require_work):
        return _object(self._command(["container", "inspect", "--format", CONTAINER_FORMAT, ident], require_work))

    def _network(self, require_work):
        return _object(self._command(["network", "inspect", "--format", NETWORK_FORMAT, self.spec.network_id], require_work))

    def _check_container(self, value, *, ident, image, role, user):
        spec = self.spec
        _require(value["Id"] == ident and value["Image"] == image and value["Name"] == "/" + spec.prefix + "-" + role
            and value["Running"] is True and type(value["StartedAt"]) is str and value["StartedAt"]
            and value["User"] == user and value["Labels"].get(OWNER_LABEL) == spec.owner)
        host = value["HostConfig"]
        _require(host["Privileged"] is False and "ALL" in host["CapDrop"] and host["CapAdd"] in (None, [])
            and any(item in {"no-new-privileges", "no-new-privileges:true"} for item in host["SecurityOpt"])
            and host["NetworkMode"] == spec.prefix and host["PidMode"] == "" and host["UTSMode"] == ""
            and host["IpcMode"] == "private" and host["PortBindings"] in ({}, None)
            and all(type(host[key]) is int and 0 < host[key] <= bound for key, bound in
                (("Memory", 2 * 1024 * 1024 * 1024), ("NanoCpus", 2_000_000_000), ("PidsLimit", 256))))
        _require(type(value["Networks"]) is dict and set(value["Networks"]) == {spec.prefix}
            and value["Networks"][spec.prefix]["NetworkID"] == spec.network_id
            and (value["Ports"] is None or type(value["Ports"]) is dict
                and all(item is None for item in value["Ports"].values())))
        mounts = value["Mounts"]
        _require(type(mounts) is list)
        destination = "/tmp" if role == "app" else "/var/lib/postgresql/data" if role == "pg" else "/data"
        _require(type(host["Tmpfs"]) is dict and set(host["Tmpfs"]) == {destination}
            and type(host["Tmpfs"][destination]) is str and len(host["Tmpfs"][destination]) <= 256
            and "rw" in host["Tmpfs"][destination].split(","))
        if role == "app":
            _require(host["ReadonlyRootfs"] is True and value["Path"] == "java"
                and type(value["Args"]) is list and value["Args"][:2] == ["-jar", "/app/target.jar"])
            jars = [item for item in mounts if item["Destination"] == "/app/target.jar"]
            _require(len(jars) == 1 and jars[0]["Type"] == "bind" and jars[0]["RW"] is False
                and all(item is jars[0] or item["Type"] == "tmpfs" and item["Destination"] == "/tmp" for item in mounts))
        else:
            _require(len(mounts) <= 1 and all(item["Type"] == "tmpfs"
                and item["Destination"] == destination and item["RW"] is True for item in mounts))

    def _snapshot(self, require_work):
        target = self._container(self.spec.container_id, require_work)
        self._check_container(target, ident=self.spec.container_id, image=self.spec.image_id, role="app", user="65534:65534")
        dependencies = []
        for item in self.spec.dependencies:
            value = self._container(item.container_id, require_work)
            self._check_container(value, ident=item.container_id, image=item.image_id, role=item.role, user=item.user)
            dependencies.append(value)
        network = self._network(require_work)
        _require(network["Id"] == self.spec.network_id and network["Name"] == self.spec.prefix
            and network["Internal"] is True and network["Attachable"] is False and network["Driver"] == "bridge"
            and network["Scope"] == "local" and network["Labels"].get(OWNER_LABEL) == self.spec.owner
            and type(network["Containers"]) is dict
            and set(network["Containers"]) == {self.spec.container_id, *(item.container_id for item in self.spec.dependencies)})
        return target, dependencies, network

    def inspect(self, artifact_hash, *, require_work):
        _require(type(artifact_hash) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_hash))
        require_work()
        try:
            before = self._snapshot(require_work)
            output = self._command(["exec", self.spec.container_id, "sha256sum", "/app/target.jar"], require_work, 256)
            _require(output.decode("ascii", errors="strict").strip() == artifact_hash[7:] + "  /app/target.jar")
            after = self._snapshot(require_work)
            _require(before == after)
        except (KeyError, TypeError, UnicodeError, AttributeError):
            raise NativeEnvironmentInvalid("owned target metadata incomplete or changed") from None
        target, dependencies, network = after
        inventory = {"schema": ENVIRONMENT_SCHEMA, "project_id": self.spec.project_id,
            "environment_id": self.spec.environment_id, "operator_policy_digest": self.spec.digest,
            "artifact_hash": artifact_hash, "target": {"container_id": target["Id"], "image_id": target["Image"],
                "started_at": target["StartedAt"], "user": target["User"]},
            "dependency_instances": [{"role": spec.role, "container_id": item["Id"], "image_id": item["Image"],
                "started_at": item["StartedAt"], "user": item["User"]} for spec, item in zip(self.spec.dependencies, dependencies)],
            "network_id": network["Id"], "namespace_origin": "http://127.0.0.1:8080",
            "native_artifact_attested": True, "isolation_attested": True,
            "host_ports_exposed": False, "developer_resources_used": False,
            "model_outbound_permitted": False, "execution_authorized": False,
            "external_egress_denial_verified": False, "host_access_denial_verified": False,
            "dependency_health_verified": False,
            "fixtures_verified": False, "locators_verified": False, "business_coverage_verified": False,
            "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0}
        require_work()
        return NativeEnvironmentObservation(inventory, acceptance_digest(inventory), datetime.now(timezone.utc).isoformat())
