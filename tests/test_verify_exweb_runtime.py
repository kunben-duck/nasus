"""Probe contract tests use transport specimens, not an executed target."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace
import zipfile

import httpx
import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / "scripts/verify-exweb-runtime.py"
    spec = importlib.util.spec_from_file_location("exweb_native_runtime_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execution_is_explicit_not_part_of_source_retrieval(probe, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "command", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(SystemExit) as error:
        probe.main(["--repository", str(tmp_path), "--maven-cache", str(tmp_path), "--report", str(tmp_path / "report.json")])
    assert error.value.code == 2
    assert calls == []


def test_wrong_revision_fails_before_any_git_or_docker_call(probe, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "command", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(probe.ProbeFailure, match="reviewed exweb commit"):
        probe.source_inventory(tmp_path, "0" * 40)
    assert calls == []


@pytest.mark.parametrize("entry", [
    b"120000 blob " + b"a" * 40 + b"\tlink\0",
    b"160000 commit " + b"a" * 40 + b"\tmodule\0",
    b"100644 blob " + b"a" * 40 + b"\t../escape\0",
])
def test_executable_inventory_rejects_symlinks_submodules_and_escape(probe, tmp_path, monkeypatch, entry):
    replies = iter([probe.REPOSITORY.encode(), probe.REVISION.encode(), entry])
    monkeypatch.setattr(probe, "command", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, next(replies)))
    with pytest.raises(probe.ProbeFailure, match="unsafe paths"):
        probe.source_inventory(tmp_path, probe.REVISION)


def test_build_has_no_network_and_no_host_credentials_or_mutable_cache(probe, tmp_path):
    args = probe.build_args("owned-probe", "sha256:pinned-image", tmp_path / "source", tmp_path / "repository")
    assert args[args.index("--network") + 1] == "none"
    assert "--offline" in args and "--pull=never" in args
    assert "verify" == args[-1] and "-DskipTests" not in args
    assert "--read-only" in args and "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges" in args
    mounts = [args[index + 1] for index, value in enumerate(args) if value == "--mount"]
    assert len(mounts) == 2 and mounts[1].endswith("dst=/cache,readonly")
    assert not any(value == "--env" for value in args)


def transport(authorization_status=403, closed_status=409, *, invalid_create=False):
    session = {"sessionId": "session_probe_1", "tenantId": "nasus-probe-a", "userId": "owner-a",
               "title": "Native exweb session", "status": "ACTIVE", "channel": "web"}
    closed = False

    def respond(request):
        nonlocal closed
        own = request.headers["X-Tenant-Id"] == "nasus-probe-a" and request.headers["X-User-Id"] == "owner-a"
        if request.method == "POST" and request.url.path.endswith("/sessions"):
            assert json.loads(request.content)["title"] == session["title"]
            return httpx.Response(200, json=[] if invalid_create else session)
        if request.method == "POST":
            closed = True
            return httpx.Response(200, json={**session, "status": "CLOSED"})
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json=[{**session, "status": "CLOSED" if closed else "ACTIVE"}] if own else [])
        if not own:
            return httpx.Response(authorization_status, json={"error": "probe denied"})
        if closed:
            return httpx.Response(closed_status, json={"error": "probe closed"})
        return httpx.Response(200, json=session)

    return httpx.MockTransport(respond)


def test_native_oracle_observations_capture_exact_input_and_response(probe):
    checks, evidence = {}, []
    with httpx.Client(base_url="http://localhost", transport=transport()) as client:
        ident, headers = probe.session_observations(client, checks, evidence)
    assert ident == "session_probe_1" and headers["X-User-Id"] == "owner-a"
    assert len(checks) == 12 and all(checks.values())
    assert len(evidence) == 9
    assert all(item["response_hash"].startswith("sha256:") for item in evidence)
    assert evidence[0]["request"] == {"title": "Native exweb session", "channel": "web"}


def test_denial_with_http_500_is_not_a_passing_contract(probe):
    checks, evidence = {}, []
    with httpx.Client(base_url="http://localhost", transport=transport(500, 500)) as client:
        probe.session_observations(client, checks, evidence)
    assert checks["other_user_read_denied"] and checks["other_tenant_read_denied"]
    assert checks["closed_read_denied"]
    assert not checks["other_user_read_status"] and not checks["other_tenant_read_status"]
    assert not checks["closed_read_status"]


def test_non_object_response_is_not_a_native_session(probe):
    checks, evidence = {}, []
    with httpx.Client(base_url="http://localhost", transport=transport(invalid_create=True)) as client:
        with pytest.raises(probe.ProbeFailure, match="session creation"):
            probe.session_observations(client, checks, evidence)
    assert checks == {"session_create": False} and len(evidence) == 1


def test_runner_fixture_accepts_the_original_prefixed_session_identity(probe):
    session = dict(sessionId="session_1234-5678", tenantId="default", userId="anonymous", status="ACTIVE")
    assert probe.require_anonymous_session(200, session) == session["sessionId"]
    for changed in ({**session, "sessionId": "../escape"}, {**session, "userId": "another"},
            {**session, "status": "CLOSED"}, {**session, "sessionId": "x" * 129}):
        with pytest.raises(probe.ProbeFailure): probe.require_anonymous_session(200, changed)


def test_subprocess_does_not_inherit_developer_or_model_secrets(probe, monkeypatch):
    monkeypatch.setenv("NASUS_DATABASE_URL", "private-database")
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    captured = {}

    def run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, b"ok")

    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.command(["docker", "version"]).stdout == b"ok"
    assert "NASUS_DATABASE_URL" not in captured["env"] and "OPENAI_API_KEY" not in captured["env"]


def test_owned_transport_preserves_exact_post_input_and_native_http_status(probe, monkeypatch):
    calls = []

    def command(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, b'HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n{"error":"denied"}')

    monkeypatch.setattr(probe, "command", command)
    with httpx.Client(base_url="http://127.0.0.1:8080", transport=probe.DockerHttpTransport("owned-app")) as client:
        response = client.post("/api/v1/finance/chat/sessions", json={"title": "exact"})
    assert response.status_code == 403 and response.json() == {"error": "denied"}
    args, kwargs = calls[0]
    assert args[:4] == ["docker", "exec", "--interactive", "owned-app"]
    assert "--location" not in args and "--data-binary" in args
    assert json.loads(kwargs["input"]) == {"title": "exact"}


def test_owned_transport_rejects_host_or_external_targets_before_dispatch(probe, monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "command", lambda *args, **kwargs: calls.append(args))
    with httpx.Client(transport=probe.DockerHttpTransport("owned-app")) as client:
        with pytest.raises(probe.ProbeFailure, match="loopback"):
            client.get("http://host.docker.internal:8000/readyz")
    assert calls == []


def test_existing_probe_evidence_cannot_be_overwritten(probe, tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text("original-evidence")
    calls = []
    monkeypatch.setattr(probe, "command", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(SystemExit) as error:
        probe.main(["--execute-reviewed-target", "--repository", str(tmp_path), "--maven-cache", str(tmp_path), "--report", str(path)])
    assert error.value.code == 2 and path.read_text() == "original-evidence" and calls == []


def test_export_rejects_mismatched_actual_git_bytes(probe, tmp_path, monkeypatch):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        item = tarfile.TarInfo("pom.xml")
        item.size = 4
        archive.addfile(item, io.BytesIO(b"fake"))
    monkeypatch.setattr(probe, "command", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stream.getvalue()))
    with pytest.raises(probe.ProbeFailure, match="Git blob"):
        probe.export_source(tmp_path, tmp_path / "export", [{"path": "pom.xml", "mode": "100644", "git_blob": "0" * 40}])
    assert not (tmp_path / "export/pom.xml").exists()


def test_export_rejects_unsafe_inventory_before_archive_dispatch(probe, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "command", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(probe.ProbeFailure, match="safe file members"):
        probe.export_source(tmp_path, tmp_path / "export", [{"path": "../escape", "mode": "100644", "git_blob": "0" * 40}])
    assert calls == []


def test_runtime_inventory_pins_actual_library_and_compiled_bytes(probe, tmp_path):
    path = tmp_path / "native.jar"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BOOT-INF/lib/dependency.jar", b"exact-runtime-library")
        archive.writestr("BOOT-INF/classes/pkg/Native.class", b"exact-compiled-class")
    report = probe.jar_inventory(path)
    assert report["runtime_library_count"] == report["compiled_class_count"] == 1
    assert {item["content_hash"] for item in report["assets"]} == {
        probe.digest(b"exact-runtime-library"), probe.digest(b"exact-compiled-class")}
    assert report["inventory_hash"].startswith("sha256:")


@pytest.mark.parametrize("member", ["BOOT-INF/classes/../unsafe.class", "BOOT-INF/lib/../../unsafe.jar"])
def test_runtime_inventory_rejects_unsafe_members(probe, tmp_path, member):
    path = tmp_path / "bad.jar"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, b"bad")
    with pytest.raises(probe.ProbeFailure, match="unsafe member"):
        probe.jar_inventory(path)


def test_cleanup_daemon_failure_is_not_confirmation_of_resource_absence(probe, monkeypatch):
    monkeypatch.setattr(probe, "command", lambda args, **kwargs: subprocess.CompletedProcess(args, 1, b"Cannot connect to the Docker daemon"))
    resources = probe.DockerResources()
    resources.containers = [resources.prefix + "-app"]
    resources.network_created = True
    report = resources.close()
    assert not report["verified"]
    assert report["remaining_owned_resources"] == [resources.prefix + "-app", resources.prefix]


def test_cleanup_requires_owned_name_in_authoritative_not_found(probe):
    result = subprocess.CompletedProcess([], 1, b"Error: No such object: owned-app")
    assert probe.resource_absent(result, "owned-app")
    assert not probe.resource_absent(result, "different-app")
    assert not probe.resource_absent(subprocess.CompletedProcess([], 0, b"[]"), "owned-app")


def test_original_deployment_requires_opt_in_before_creating_resources(tmp_path, monkeypatch):
    from apps.api.tests.exweb_owned_deployment import OriginalExwebDeployment

    monkeypatch.delenv("EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD", raising=False)
    directory = tmp_path / "not-created"
    with pytest.raises(ValueError, match="explicit native exweb execution"):
        OriginalExwebDeployment(directory)
    assert not directory.exists()


def test_cleanup_removes_registered_canaries_and_rejects_unknown_resource_absence(probe, monkeypatch):
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        if "inspect" in args:
            return subprocess.CompletedProcess(args, 1, ("Error: No such object: " + args[-1]).encode())
        return subprocess.CompletedProcess(args, 0, b"")
    monkeypatch.setattr(probe, "command", command)
    resources = probe.DockerResources()
    resources.containers = [resources.prefix + "-canary", resources.prefix + "-canary-control"]
    resources.network_created = True
    resources.extra_networks = [resources.prefix + "-canary-network"]
    report = resources.close()
    assert report == {"verified": True, "remaining_owned_resources": []}
    removed = [args[-1] for args in calls if args[1:3] == ["network", "rm"]]
    assert removed == [resources.prefix + "-canary-network", resources.prefix]
    monkeypatch.setattr(probe, "command", lambda args, **kwargs: subprocess.CompletedProcess(args, 1, b"daemon unavailable"))
    assert not resources.close()["verified"]


@pytest.mark.parametrize("change", [None, "receipt", "bytes"])
def test_original_deployment_reads_exact_saved_artifact_not_a_rebuild(tmp_path, monkeypatch, change):
    from apps.api.tests.exweb_owned_deployment import OriginalExwebDeployment
    from apps.api.app.domain.shared.native_build_source import (
        FrozenNativeBuildSource, NativeBuildFile, NativeBuildSourcePin, byte_digest,
    )

    monkeypatch.setenv("EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD", "1")
    deployment = OriginalExwebDeployment(tmp_path / "original-output")
    digest = "sha256:" + "a" * 64
    body = b"<project>Protocol source, not an executed Maven build.</project>"
    source = FrozenNativeBuildSource(NativeBuildSourcePin("project", "image", digest, "manifest", digest,
        "binding", "revision", "source", "commit", byte_digest(b"pom.xml\0" + body), digest),
        (NativeBuildFile("pom.xml", body),))
    payload = dict(project_id="project", image_revision_id="image", image_artifact_hash=digest,
        binding_id="binding", source_revision_id="revision", artifact_path="target/original.jar",
        request_digest=digest, operator_policy_digest=digest, source_scope_digest=digest)
    receipt = {"artifact": {"content_hash": byte_digest(b"original-jar")}}
    built = {"project_id": "project", "invocation_id": "original-command", "receipt": receipt}
    reads = []

    def read_original(build_id, request, **kwargs):
        reads.append((build_id, request, kwargs))
        return {"receipt": {"artifact": {"content_hash": digest}} if change == "receipt" else receipt,
            "artifact": b"substituted-jar" if change == "bytes" else b"original-jar"}

    builds = SimpleNamespace(
        repository=SimpleNamespace(inspect=lambda project, invocation: {
            "request": payload, "result": {"build_id": "saved-build", "artifact_ref": "s3://private/original",
                "artifact_hash": digest}}),
        sources=SimpleNamespace(read=lambda **kwargs: source),
        artifacts=SimpleNamespace(read=read_original),
    )
    if change is None:
        path = deployment.original_jar(built, builds)
        assert path.read_bytes() == b"original-jar"
        assert path.stat().st_mode & 0o777 == 0o444
    else:
        with pytest.raises(AssertionError):
            deployment.original_jar(built, builds)
        assert not (deployment.directory / "original-target.jar").exists()
    assert len(reads) == 1
    build_id, request, options = reads[0]
    assert build_id == "saved-build" and request.source is source
    assert request.artifact_path == "target/original.jar"
    assert options == {"artifact_ref": "s3://private/original", "artifact_hash": digest}
    assert deployment.resources.containers == [] and not deployment.resources.network_created
