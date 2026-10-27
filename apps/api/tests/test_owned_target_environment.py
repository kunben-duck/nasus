"""Protocol specimens do not stand in for a native deployment or business gold."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.native_environment import (
    OWNER_LABEL, NativeEnvironmentInvalid, NativeEnvironmentObservation, OwnedDependency, OwnedEnvironment,
)
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.runner.native_maven_build import NativeBuildFailure
from apps.api.app.infrastructure.runner.owned_target_environment import (
    CONTAINER_FORMAT, NETWORK_FORMAT, OwnedTargetEnvironmentInspector,
)


ARTIFACT = "sha256:" + "a" * 64


@pytest.fixture
def spec():
    return OwnedEnvironment("project-a", "environment-a", "0123456789abcdef", "nasus-target-0123456789abcdef",
        "1" * 64, "sha256:" + "2" * 64, "3" * 64,
        (OwnedDependency("pg", "4" * 64, "sha256:" + "5" * 64, "999:999"),
         OwnedDependency("redis", "6" * 64, "sha256:" + "7" * 64, "999:999")))


def containers(spec):
    def container(ident, image, role, user):
        return {"Id": ident, "Image": image, "Name": "/" + spec.prefix + "-" + role,
            "Running": True, "StartedAt": "2026-10-10T00:00:00Z", "User": user,
            "Labels": {OWNER_LABEL: spec.owner}, "Path": "java" if role == "app" else role,
            "Args": ["-jar", "/app/target.jar"] if role == "app" else [],
            "HostConfig": {"Privileged": False, "CapDrop": ["ALL"], "CapAdd": None,
                "SecurityOpt": ["no-new-privileges:true"], "NetworkMode": spec.prefix,
                "PidMode": "", "UTSMode": "", "IpcMode": "private", "PortBindings": None,
                "Memory": 512 * 1024 * 1024, "NanoCpus": 1_000_000_000, "PidsLimit": 128,
                "Tmpfs": {"/tmp" if role == "app" else "/var/lib/postgresql/data" if role == "pg" else "/data": "rw,size=128m"},
                "ReadonlyRootfs": role == "app"},
            "Networks": {spec.prefix: {"NetworkID": spec.network_id}}, "Ports": {"8080/tcp": None},
            "Mounts": ([{"Type": "bind", "Destination": "/app/target.jar", "RW": False},
                {"Type": "tmpfs", "Destination": "/tmp", "RW": True}] if role == "app" else
                [{"Type": "tmpfs", "Destination": "/var/lib/postgresql/data" if role == "pg" else "/data", "RW": True}])}
    return {spec.container_id: container(spec.container_id, spec.image_id, "app", "65534:65534"),
        **{item.container_id: container(item.container_id, item.image_id, item.role, item.user) for item in spec.dependencies}}


def network(spec):
    return {"Id": spec.network_id, "Name": spec.prefix, "Internal": True, "Attachable": False,
        "Driver": "bridge", "Scope": "local", "Labels": {OWNER_LABEL: spec.owner},
        "Containers": {key: {} for key in [spec.container_id, *(item.container_id for item in spec.dependencies)]}}


class Commands:
    def __init__(self, spec):
        self.spec, self.containers, self.network = spec, containers(spec), network(spec)
        self.calls, self.body, self.after = [], ARTIFACT[7:].encode() + b"  /app/target.jar\n", None
        self.reply = None

    def __call__(self, args, **options):
        assert options["timeout"] == 10
        options["require_work"]()
        self.calls.append((args, options))
        if self.reply is not None:
            return self.reply
        if args[1] == "exec":
            assert args == ["docker", "exec", self.spec.container_id, "sha256sum", "/app/target.jar"]
            assert options["max_bytes"] == 256
            if self.after:
                self.after(self)
            return 0, self.body
        assert options["max_bytes"] == 256 * 1024
        if args[1] == "container":
            assert args[2:5] == ["inspect", "--format", CONTAINER_FORMAT]
            value = self.containers[args[-1]]
        else:
            assert args == ["docker", "network", "inspect", "--format", NETWORK_FORMAT, self.spec.network_id]
            value = self.network
        return 0, json.dumps(value).encode()


def test_exact_original_artifact_and_owned_cohort_are_observed_without_execution(spec):
    commands, access = Commands(spec), []
    result = OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: access.append(True))
    inventory = result.inventory
    assert inventory["operator_policy_digest"] == spec.digest
    assert inventory["project_id"] == spec.project_id and inventory["environment_id"] == spec.environment_id
    assert inventory["artifact_hash"] == ARTIFACT and inventory["target"]["container_id"] == spec.container_id
    assert result.inventory_hash == acceptance_digest(inventory)
    assert inventory["native_artifact_attested"] and inventory["isolation_attested"]
    for key in ("execution_authorized", "business_coverage_verified", "fixtures_verified", "locators_verified",
            "external_egress_denial_verified", "host_access_denial_verified", "dependency_health_verified"):
        assert inventory[key] is False
    assert inventory["automated_count"] == inventory["executed_on_target_count"] == inventory["passed_count"] == 0
    assert len(commands.calls) == 9 and len(access) >= 20
    assert result.observed_at.endswith("+00:00")
    assert ".Config.Env" not in CONTAINER_FORMAT and "{{json .Args}}" not in CONTAINER_FORMAT
    assert "slice .Args 0 2" in CONTAINER_FORMAT
    assert "exec" == commands.calls[4][0][1]


@pytest.mark.parametrize("field,value", [
    ("Id", "8" * 64), ("Image", "sha256:" + "9" * 64), ("Name", "/developer-app"),
    ("User", "0:0"), ("User", "root"), ("Running", False), ("Running", 1), ("StartedAt", ""),
    ("Path", "sh"), ("Args", ["-jar", "/app/different.jar"]), ("Labels", {OWNER_LABEL: "wrong-owner"}),
    ("Networks", {}), ("Ports", {"8080/tcp": [{"HostPort": "8080"}]}),
])
def test_wrong_target_identity_or_scope_fails_before_artifact_read(spec, field, value):
    commands = Commands(spec)
    commands.containers[spec.container_id][field] = value
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)
    assert all(args[1] != "exec" for args, _ in commands.calls)


@pytest.mark.parametrize("field,value", [
    ("Privileged", True), ("CapDrop", []), ("CapAdd", ["NET_ADMIN"]), ("SecurityOpt", []),
    ("NetworkMode", "host"), ("PidMode", "host"), ("UTSMode", "host"), ("IpcMode", "host"),
    ("PortBindings", {"8080/tcp": [{}]}), ("Memory", 0), ("Memory", 2**32), ("NanoCpus", 0),
    ("PidsLimit", 0), ("PidsLimit", True), ("PidsLimit", 257), ("ReadonlyRootfs", False),
])
def test_target_security_and_capacity_are_checked(spec, field, value):
    commands = Commands(spec)
    commands.containers[spec.container_id]["HostConfig"][field] = value
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


@pytest.mark.parametrize("change", ["writable-jar", "wrong-mount", "extra-volume", "wrong-network-id", "extra-network"])
def test_no_mutable_jar_or_other_host_mount_or_network(spec, change):
    commands = Commands(spec)
    target = commands.containers[spec.container_id]
    if change == "writable-jar": target["Mounts"][0]["RW"] = True
    if change == "wrong-mount": target["Mounts"][0]["Type"] = "volume"
    if change == "extra-volume": target["Mounts"].append({"Destination": "/secrets", "Type": "bind", "RW": False})
    if change == "wrong-network-id": target["Networks"][spec.prefix]["NetworkID"] = "f" * 64
    if change == "extra-network": target["Networks"]["developer"] = {"NetworkID": "f" * 64}
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


@pytest.mark.parametrize("role", ["pg", "redis"])
@pytest.mark.parametrize("change", ["root", "host-volume", "wrong-mount", "owner", "stopped"])
def test_dependency_is_an_exact_private_owned_instance(spec, role, change):
    commands = Commands(spec)
    ident = next(item.container_id for item in spec.dependencies if item.role == role)
    dependency = commands.containers[ident]
    if change == "root": dependency["User"] = "0:0"
    if change == "host-volume": dependency["Mounts"][0]["Type"] = "volume"
    if change == "wrong-mount": dependency["Mounts"][0]["Destination"] = "/other"
    if change == "owner": dependency["Labels"][OWNER_LABEL] = "other"
    if change == "stopped": dependency["Running"] = False
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


@pytest.mark.parametrize("field,value", [("Id", "f" * 64), ("Name", "developer"), ("Internal", False),
    ("Attachable", True), ("Driver", "overlay"), ("Scope", "swarm"), ("Labels", {}), ("Containers", {})])
def test_network_policy_is_not_inferred_from_a_healthy_app(spec, field, value):
    commands = Commands(spec)
    commands.network[field] = value
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


def test_extra_developer_network_member_is_rejected(spec):
    commands = Commands(spec)
    commands.network["Containers"]["f" * 64] = {}
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


def test_docker_null_ports_for_images_without_exposed_ports_is_valid(spec):
    commands = Commands(spec)
    for value in commands.containers.values(): value["Ports"] = None
    result = OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)
    assert result.inventory["host_ports_exposed"] is False


def test_native_docker_tmpfs_is_reported_in_host_config_not_mounts(spec):
    commands = Commands(spec)
    for value in commands.containers.values():
        value["Mounts"] = [item for item in value["Mounts"] if item["Type"] != "tmpfs"]
    result = OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)
    assert result.inventory["isolation_attested"] is True


@pytest.mark.parametrize("tmpfs", [None, {}, {"/tmp": "ro"}, {"/other": "rw"}, {"/tmp": "rw", "/other": "rw"}])
def test_tmpfs_policy_is_checked_in_authoritative_host_config(spec, tmpfs):
    commands = Commands(spec)
    commands.containers[spec.container_id]["HostConfig"]["Tmpfs"] = tmpfs
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


@pytest.mark.parametrize("body", [b"wrong", b"b" * 64 + b"  /app/target.jar\n", b"a" * 64 + b"  /other.jar\n", b"\xff"])
def test_actual_container_bytes_must_match_the_original_artifact(spec, body):
    commands = Commands(spec)
    commands.body = body
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


@pytest.mark.parametrize("change", ["restart", "mount", "network"])
def test_changes_during_inspection_are_not_returned_as_a_valid_observation(spec, change):
    commands = Commands(spec)
    def mutate(value):
        if change == "restart": value.containers[spec.container_id]["StartedAt"] = "2026-10-10T00:01:00Z"
        if change == "mount": value.containers[spec.container_id]["Mounts"][0]["Source"] = "/other.jar"
        if change == "network": value.network["Containers"][spec.container_id] = {"IPv4Address": "172.22.0.8/16"}
    commands.after = mutate
    with pytest.raises(NativeEnvironmentInvalid):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)


@pytest.mark.parametrize("reply", [(1, b"credential-bearing-error"), (0, b"[]"), (0, b'{"Id":1,"Id":2}'),
    (0, b'{"Id":NaN}'), (0, b"\xff"), (0, b"{}"), (0, b"x" * (256 * 1024 + 1))])
def test_bad_daemon_metadata_fails_closed_without_echoing_diagnostics(spec, reply):
    commands = Commands(spec)
    commands.reply = reply
    with pytest.raises(NativeEnvironmentInvalid) as error:
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)
    assert "credential-bearing-error" not in str(error.value)


@pytest.mark.parametrize("exception", [NativeBuildFailure("secret"), OSError("secret")])
def test_command_failure_is_redacted(spec, exception):
    def command(*args, **options): raise exception
    with pytest.raises(NativeEnvironmentInvalid) as error:
        OwnedTargetEnvironmentInspector(spec, command=command).inspect(ARTIFACT, require_work=lambda: None)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("at", [1, 5, 12, 20])
def test_source_revocation_or_cancellation_propagates_without_recovery(spec, at):
    commands, count = Commands(spec), 0
    def current():
        nonlocal count
        count += 1
        if count == at: raise SourceAccessDenied("revoked")
    with pytest.raises(SourceAccessDenied, match="revoked"):
        OwnedTargetEnvironmentInspector(spec, command=commands).inspect(ARTIFACT, require_work=current)
    assert count == at


@pytest.mark.parametrize("updates", [{"project_id": "other project"}, {"owner": "x"}, {"prefix": "developer"},
    {"container_id": "short"}, {"image_id": "mutable:tag"}, {"network_id": "short"},
    {"dependencies": ()}, {"dependencies": []}])
def test_operator_policy_requires_immutable_complete_resource_ids(spec, updates):
    with pytest.raises(NativeEnvironmentInvalid): replace(spec, **updates)


def test_native_observation_cannot_claim_execution_or_verified_business_coverage(spec):
    result = OwnedTargetEnvironmentInspector(spec, command=Commands(spec)).inspect(ARTIFACT, require_work=lambda: None)
    for key in ("execution_authorized", "fixtures_verified", "locators_verified", "business_coverage_verified", "passed_count"):
        value = deepcopy(result.inventory)
        value[key] = 1 if key == "passed_count" else True
        with pytest.raises(NativeEnvironmentInvalid): NativeEnvironmentObservation(value, acceptance_digest(value), result.observed_at)
    with pytest.raises(NativeEnvironmentInvalid): NativeEnvironmentObservation(result.inventory, "sha256:" + "f" * 64, result.observed_at)
