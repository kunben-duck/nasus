"""Actual, bounded canary comparisons; not universal isolation or execution authority.

No Internet, developer endpoint, developer file or Docker socket is accessed.
Only fresh owned canaries are created, with cleanup delegated to the probe owner.
"""
import base64
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import secrets
import time


CANARY_SOURCE = Path(__file__).resolve().parent / "fixtures/IsolationCanary.java"
CANARY_PATH = "/run/nasus-host-canary"
ABSENT = b"NASUS_CANARY_ABSENT\n"
SOCKET_ABSENT = b"NASUS_DOCKER_SOCKET_ABSENT\n"


class IsolationProbeFailure(RuntimeError):
    pass


def byte_digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def response(result):
    if (type(result.returncode) is not int or type(result.stdout) is not bytes
            or len(result.stdout) > 16 * 1024):
        raise IsolationProbeFailure("canary response is incomplete or exceeds its bound")
    return {"return_code": result.returncode, "response_base64": base64.b64encode(result.stdout).decode("ascii"),
        "response_hash": byte_digest(result.stdout), "byte_count": len(result.stdout)}


def network_denied(before, target, after, marker):
    if type(marker) is not bytes or not re.fullmatch(b"[0-9a-f]{64}", marker):
        raise IsolationProbeFailure("invalid canary identity")
    for result in (before, target, after):
        response(result)
    if any(item.returncode != 0 or item.stdout != marker for item in (before, after)):
        raise IsolationProbeFailure("a failed positive control is not evidence of isolation")
    # Only a transport refusal/timeout without HTTP bytes proves this bounded comparison.
    return target.returncode in {7, 28} and target.stdout == b""


def file_absent(before, target, after, marker):
    for result in (before, target, after):
        response(result)
    if any(item.returncode != 0 or item.stdout != marker for item in (before, after)):
        raise IsolationProbeFailure("host-file positive control changed or is unavailable")
    return target.returncode == 0 and target.stdout == ABSENT


def curl_arguments(container, address):
    if type(container) is not str or not re.fullmatch(r"[0-9a-f]{64}", container):
        raise IsolationProbeFailure("canary requests require an exact original container ID")
    try:
        host = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        raise IsolationProbeFailure("canary address must be an exact owned private IPv4") from None
    if not host.is_private or host.is_loopback or host.is_unspecified or host.is_multicast or host.is_link_local:
        raise IsolationProbeFailure("canary address is outside the owned private scope")
    return ["docker", "exec", "--user", "65534:65534", container, "curl", "--disable", "--noproxy", "*",
        "--ipv4", "--silent", "--fail", "--connect-timeout", "2", "--max-time", "3",
        "--max-filesize", "64", "--proto", "=http", "--request", "GET", "--header", "Accept-Encoding: identity",
        "--url", "http://" + str(host) + ":18080/"]


def _container(command, resources, suffix, image, network, arguments, process):
    name = resources.prefix + "-" + suffix
    resources.containers.append(name)
    command(["docker", "run", "--detach", "--pull=never", "--name", name,
        "--label", "nasus.target.environment_owner=" + resources.owner, "--network", network,
        "--read-only", "--user", "65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--memory=256m", "--cpus=1", "--tmpfs", "/tmp:rw,size=64m",
        *arguments, image, *process])
    return name


def _instances(command, names, network, owner, image):
    data = json.loads(command(["docker", "network", "inspect", network]).stdout)
    if (type(data) is not list or len(data) != 1 or data[0]["Name"] != network
            or data[0]["Labels"].get("nasus.target.environment_owner") != owner
            or data[0]["Internal"] is not False or data[0]["Driver"] != "bridge"):
        raise IsolationProbeFailure("the fresh comparison network differs")
    value = data[0]
    instances = []
    for name in names:
        item = json.loads(command(["docker", "container", "inspect", name]).stdout)[0]
        if (item["Name"] != "/" + name or item["Config"]["Labels"].get("nasus.target.environment_owner") != owner
                or item["State"]["Running"] is not True or item["Image"] != image
                or set(item["NetworkSettings"]["Networks"]) != {network}
                or item["Config"]["User"] != "65534:65534" or item["HostConfig"]["PortBindings"]):
            raise IsolationProbeFailure("the positive-control instance differs")
        address = item["NetworkSettings"]["Networks"][network]["IPAddress"]
        curl_arguments(item["Id"], address)
        instances.append({"container_id": item["Id"], "image_id": item["Image"],
            "started_at": item["State"]["StartedAt"], "address": address})
    if (set(value["Containers"]) != {item["container_id"] for item in instances}
            or len(set(item["container_id"] for item in instances)) != len(instances)):
        raise IsolationProbeFailure("unexpected comparison network members")
    return {"network_id": value["Id"], "instances": instances}


def isolation_observations(command, resources, inspector, artifact_hash, directory, image):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise IsolationProbeFailure("canary runtime must use the fixed local image ID")
    before = inspector.inspect(artifact_hash, require_work=lambda: None)
    source_hash = byte_digest(CANARY_SOURCE.read_bytes())
    marker = secrets.token_hex(32).encode("ascii")
    host_file = Path(directory) / "host-canary"
    with host_file.open("xb") as output:
        output.write(marker)
    host_file.chmod(0o444)
    network = resources.prefix + "-canary-network"
    # Remember intent before create; a timed-out client can still leave an owned resource.
    resources.extra_networks.append(network)
    command(["docker", "network", "create", "--driver", "bridge",
        "--label", "nasus.target.environment_owner=" + resources.owner, network])
    server = _container(command, resources, "canary", image, network,
        ["--mount", "type=bind,src=" + str(CANARY_SOURCE) + ",dst=/app/IsolationCanary.java,readonly",
            "--entrypoint", "java"], ["-Djava.io.tmpdir=/tmp", "/app/IsolationCanary.java", marker.decode("ascii")])
    control = _container(command, resources, "canary-control", image, network,
        ["--mount", "type=bind,src=" + str(host_file) + ",dst=" + CANARY_PATH + ",readonly",
            "--entrypoint", "sleep"], ["300"])
    cohort = _instances(command, (server, control), network, resources.owner, image)
    target = before.inventory["target"]["container_id"]
    if (target in {item["container_id"] for item in cohort["instances"]}
            or before.inventory["network_id"] == cohort["network_id"]):
        raise IsolationProbeFailure("target cannot also be a positive-control canary")
    address = cohort["instances"][0]["address"]
    positive_args = curl_arguments(cohort["instances"][1]["container_id"], address)
    deadline = time.monotonic() + 30
    while True:
        positive_before = command(positive_args, timeout=6, check=False)
        if positive_before.returncode == 0 and positive_before.stdout == marker:
            break
        if time.monotonic() >= deadline:
            raise IsolationProbeFailure("positive network control did not become ready")
        time.sleep(0.2)
    denied = command(curl_arguments(target, address), timeout=6, check=False)
    positive_after = command(positive_args, timeout=6, check=False)
    control_file_args = ["docker", "exec", "--user", "65534:65534", control, "cat", CANARY_PATH]
    file_before = command(control_file_args, timeout=6, check=False)
    target_file = command(["docker", "exec", "--user", "65534:65534", target, "sh", "-c",
        'if [ -e /run/nasus-host-canary ]; then printf "NASUS_CANARY_PRESENT\\n"; else printf "NASUS_CANARY_ABSENT\\n"; fi'],
        timeout=6, check=False)
    file_after = command(control_file_args, timeout=6, check=False)
    socket = command(["docker", "exec", "--user", "65534:65534", target, "sh", "-c",
        'if [ -e /var/run/docker.sock ]; then printf "NASUS_DOCKER_SOCKET_PRESENT\\n"; else printf "NASUS_DOCKER_SOCKET_ABSENT\\n"; fi'],
        timeout=6, check=False)
    after = inspector.inspect(artifact_hash, require_work=lambda: None)
    if (after.inventory != before.inventory or after.inventory_hash != before.inventory_hash
            or _instances(command, (server, control), network, resources.owner, image) != cohort
            or byte_digest(CANARY_SOURCE.read_bytes()) != source_hash):
        raise IsolationProbeFailure("target, original JAR or comparison epoch changed during probes")
    checks = {"outside_network_canary_denied": network_denied(positive_before, denied, positive_after, marker),
        "unmounted_host_canary_absent": file_absent(file_before, target_file, file_after, marker),
        "docker_socket_absent": socket.returncode == 0 and socket.stdout == SOCKET_ABSENT}
    return {"schema": "nasus.exweb-isolation-canary.v1", "observed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "exact_owned_target_and_three_bounded_canary_checks_not_universal_isolation",
        "original_inventory_hash": before.inventory_hash, "target_artifact_hash": artifact_hash,
        "target": before.inventory["target"], "control": cohort, "marker_hash": byte_digest(marker),
        "probe_source_hash": source_hash, "checks": checks,
        "responses": {key: response(value) for key, value in (
            ("network_positive_before", positive_before), ("network_target", denied), ("network_positive_after", positive_after),
            ("host_file_positive_before", file_before), ("host_file_target", target_file), ("host_file_positive_after", file_after),
            ("docker_socket_target", socket))},
        "universal_external_egress_denial_verified": False, "universal_host_access_denial_verified": False,
        "nasus_runplan_verified": False, "execution_authorized": False, "release_authorized": False}
