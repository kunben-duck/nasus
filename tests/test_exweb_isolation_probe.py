"""Protocol specimens test comparisons and cleanup; not actual isolation evidence."""
import base64
from copy import deepcopy
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import exweb_isolation_probe as isolation


MARKER = b"a" * 64
IMAGE = "sha256:" + "b" * 64
TARGET = "c" * 64
SERVER = "d" * 64
CONTROL = "e" * 64


def result(code=0, body=MARKER):
    return subprocess.CompletedProcess([], code, body)


@pytest.mark.parametrize("code", [7, 28])
def test_only_bounded_transport_denial_with_two_healthy_controls_counts(code):
    assert isolation.network_denied(result(), result(code, b""), result(), MARKER)


@pytest.mark.parametrize("code,body", [(0, MARKER), (0, b""), (0, b"other HTTP response"),
    (7, b"response"), (28, b"partial HTTP"), (6, b""), (127, b""), (22, b""), (56, b"")])
def test_reachable_target_dns_binary_failure_or_partial_bytes_do_not_prove_denial(code, body):
    assert not isolation.network_denied(result(), result(code, body), result(), MARKER)


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize("code,body", [(7, b""), (0, b"wrong marker"), (28, b"")])
def test_failed_changed_or_late_dead_positive_control_is_not_a_success(side, code, body):
    before, after = result(), result()
    if side == "before": before = result(code, body)
    else: after = result(code, body)
    with pytest.raises(isolation.IsolationProbeFailure, match="positive control"):
        isolation.network_denied(before, result(28, b""), after, MARKER)


@pytest.mark.parametrize("code,body", [(True, b""), (0, "not bytes"), (0, b"x" * 16385)])
def test_original_response_type_and_byte_bounds_are_strict(code, body):
    with pytest.raises(isolation.IsolationProbeFailure): isolation.response(result(code, body))


def test_original_bytes_are_retained_with_complete_hash_not_assumed_status():
    observed = isolation.response(result(28, b""))
    assert observed == {"return_code": 28, "response_base64": "", "response_hash": isolation.byte_digest(b""), "byte_count": 0}
    body = b"actual marker"
    assert base64.b64decode(isolation.response(result(0, body))["response_base64"]) == body


def test_file_absence_needs_original_host_canary_controls_and_exact_sentinel():
    assert isolation.file_absent(result(), result(0, isolation.ABSENT), result(), MARKER)
    assert not isolation.file_absent(result(), result(0, b"NASUS_CANARY_PRESENT\n"), result(), MARKER)
    assert not isolation.file_absent(result(), result(1, isolation.ABSENT), result(), MARKER)
    for before, after in ((result(1, b""), result()), (result(), result(0, b"changed"))):
        with pytest.raises(isolation.IsolationProbeFailure):
            isolation.file_absent(before, result(0, isolation.ABSENT), after, MARKER)


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0", "8.8.8.8", "169.254.1.1", "224.0.0.1",
    "::1", "host.docker.internal", "http://172.18.0.2", "172.18.0.2; touch /tmp/unsafe"])
def test_only_exact_owned_private_numeric_address_can_be_contacted(address):
    with pytest.raises(isolation.IsolationProbeFailure): isolation.curl_arguments(TARGET, address)


def test_numeric_canary_request_cannot_follow_redirects_proxy_retry_or_write():
    args = isolation.curl_arguments(TARGET, "172.18.0.2")
    assert args[:5] == ["docker", "exec", "--user", "65534:65534", TARGET]
    assert args[-1] == "http://172.18.0.2:18080/"
    assert args[args.index("--noproxy") + 1] == "*" and "--disable" in args and "--ipv4" in args
    assert "--retry" not in args and "--location" not in args and "--data" not in args
    with pytest.raises(isolation.IsolationProbeFailure): isolation.curl_arguments("mutable-name", "172.18.0.2")


class Commands:
    def __init__(self, resources):
        self.resources, self.calls = resources, []
        self.network = resources.prefix + "-canary-network"
        self.cohort_changed, self.positive_dead, self.denied_code = False, False, 28
        self.inspections = 0

    def __call__(self, args, **options):
        self.calls.append((args, options))
        if args[1:3] == ["network", "inspect"]:
            self.inspections += 1
            return result(0, json.dumps([{"Name": self.network, "Id": "f" * 64,
                "Labels": {"nasus.target.environment_owner": self.resources.owner}, "Internal": False, "Driver": "bridge",
                "Containers": {SERVER: {}, CONTROL: {}}}]).encode())
        if args[1:3] == ["container", "inspect"]:
            server = args[-1].endswith("-canary")
            return result(0, json.dumps([{"Name": "/" + args[-1], "Id": SERVER if server else CONTROL, "Image": IMAGE,
                "Config": {"Labels": {"nasus.target.environment_owner": self.resources.owner}, "User": "65534:65534"},
                "HostConfig": {"PortBindings": {}},
                "State": {"Running": True, "StartedAt": "changed" if self.cohort_changed and self.inspections > 1 else "original"},
                "NetworkSettings": {"Networks": {self.network: {"IPAddress": "172.18.0.2" if server else "172.18.0.3"}}}}]).encode())
        if args[1] == "exec":
            if "curl" in args:
                if args[4] == TARGET: return result(self.denied_code, b"")
                if self.positive_dead and sum("curl" in call for call, _ in self.calls) > 1: return result(7, b"")
                return result()
            if "cat" in args: return result()
            if "/var/run/docker.sock" in args[-1]: return result(0, isolation.SOCKET_ABSENT)
            return result(0, isolation.ABSENT)
        return result(0, b"owned-resource")


@pytest.fixture
def cohort(monkeypatch):
    monkeypatch.setattr(isolation.secrets, "token_hex", lambda size: MARKER.decode())
    resources = SimpleNamespace(prefix="nasus-exweb-" + "a" * 16, owner="a" * 16, containers=[], extra_networks=[])
    commands = Commands(resources)
    observation = SimpleNamespace(inventory={"target": {"container_id": TARGET, "image_id": IMAGE,
        "started_at": "original", "user": "65534:65534"}, "network_id": "1" * 64}, inventory_hash="sha256:" + "2" * 64)
    inspections = []
    def inspect(*args, **options):
        inspections.append(args)
        return deepcopy(observation)
    return SimpleNamespace(resources=resources, command=commands, observation=observation,
        inspector=SimpleNamespace(inspect=inspect), inspections=inspections)


def test_full_protocol_retains_epoch_controls_original_bytes_and_no_authority(cohort, tmp_path):
    report = isolation.isolation_observations(cohort.command, cohort.resources, cohort.inspector,
        "sha256:" + "3" * 64, tmp_path, IMAGE)
    assert all(report["checks"].values()) and len(report["responses"]) == 7
    assert len(cohort.inspections) == 2 and report["original_inventory_hash"] == cohort.observation.inventory_hash
    assert not any(report[key] for key in ("universal_external_egress_denial_verified", "universal_host_access_denial_verified",
        "nasus_runplan_verified", "execution_authorized", "release_authorized"))
    assert len(cohort.resources.extra_networks) == 1 and len(cohort.resources.containers) == 2
    creates = [args for args, _ in cohort.command.calls if args[1] == "run"]
    for args in creates:
        assert "--read-only" in args and "--pull=never" in args and "--cap-drop=ALL" in args
        assert "--security-opt=no-new-privileges" in args and "--publish" not in args
    target_commands = [args for args, _ in cohort.command.calls if args[1] == "exec" and args[4] == TARGET]
    assert all("cat" not in args[-1] for args in target_commands)
    assert report["responses"]["network_target"]["return_code"] == 28


@pytest.mark.parametrize("fault", ["control-restart", "target-restart", "late-positive", "positive-reply", "source-change"])
def test_changes_during_comparison_reject_whole_evidence(cohort, tmp_path, fault, monkeypatch):
    if fault == "control-restart": cohort.command.cohort_changed = True
    if fault == "late-positive": cohort.command.positive_dead = True
    if fault == "target-restart":
        def inspect(*args, **options):
            observed = deepcopy(cohort.observation)
            if cohort.inspections: observed.inventory["target"]["started_at"] = "changed"
            cohort.inspections.append(args)
            return observed
        cohort.inspector.inspect = inspect
    if fault == "positive-reply":
        original = cohort.command
        def wrong_after(args, **options):
            observed = original(args, **options)
            if "curl" in args and args[4] == CONTROL and sum("curl" in call for call, _ in original.calls) > 1:
                return result(0, b"different marker")
            return observed
        cohort.command = wrong_after
    if fault == "source-change":
        reads = iter((b"original-source", b"changed-source"))
        monkeypatch.setattr(isolation, "CANARY_SOURCE", SimpleNamespace(read_bytes=lambda: next(reads)))
    with pytest.raises(isolation.IsolationProbeFailure):
        isolation.isolation_observations(cohort.command, cohort.resources, cohort.inspector,
            "sha256:" + "3" * 64, tmp_path, IMAGE)
    assert len(cohort.resources.extra_networks) == 1 and len(cohort.resources.containers) == 2


def test_create_timeout_is_registered_for_cleanup_before_dispatch(cohort, tmp_path):
    def timeout(args, **options):
        assert cohort.resources.extra_networks == [cohort.resources.prefix + "-canary-network"]
        raise subprocess.TimeoutExpired(args, 6)
    with pytest.raises(subprocess.TimeoutExpired):
        isolation.isolation_observations(timeout, cohort.resources, cohort.inspector,
            "sha256:" + "3" * 64, tmp_path, IMAGE)
