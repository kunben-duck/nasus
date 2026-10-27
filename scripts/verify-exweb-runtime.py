"""Execute only the explicitly reviewed, pinned exweb target in disposable Docker resources.

This is real target evidence, not approved requirements, Nasus RunPlan provenance,
LLM acceptance, or release permission. No dependencies are downloaded and no
developer database, environment file, model key, or service is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from uuid import uuid4
import zipfile

import httpx


REPOSITORY = "https://github.com/kunben-duck/exweb.git"
REVISION = "fe5827f6b76f77ef34918d8b452ee823142332dc"
MAVEN_IMAGE = "maven:3.9.11-eclipse-temurin-21"
POSTGRES_IMAGE = "postgres:16-alpine"
REDIS_IMAGE = "redis:7-alpine"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from apps.api.app.domain.quality_loop.native_environment import OWNER_LABEL, OwnedDependency, OwnedEnvironment
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from scripts.exweb_isolation_probe import IsolationProbeFailure, isolation_observations
SOURCE_ROOT = "src/main/java/com/huawei/finance/front/one/"


class ProbeFailure(RuntimeError):
    pass


def digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def command(args, *, timeout=60, env=None, check=True, input=None):
    clean = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "TMPDIR"}}
    if env:
        clean.update(env)
    result = subprocess.run(args, env=clean, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, check=False, input=input)
    if check and result.returncode:
        raise ProbeFailure("probe subprocess failed; inspect its scoped report/log")
    return result


def source_inventory(repository: Path, revision: str):
    if revision != REVISION:
        raise ProbeFailure("only the reviewed exweb commit is permitted")
    origin = command(["git", "-C", str(repository), "remote", "get-url", "origin"]).stdout.decode().strip()
    if origin != REPOSITORY:
        raise ProbeFailure("repository origin does not match the reviewed target")
    resolved = command(["git", "-C", str(repository), "rev-parse", revision + "^{commit}"]).stdout.decode().strip()
    if resolved != revision:
        raise ProbeFailure("exact commit is required")
    listing = command(["git", "-C", str(repository), "ls-tree", "-rz", revision]).stdout
    files = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, object_id = header.decode().split()
        path = name.decode("utf-8")
        if (mode not in {"100644", "100755"} or kind != "blob"
                or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts):
            raise ProbeFailure("symlinks, submodules and unsafe paths are not executable inputs")
        files.append({"path": path, "mode": mode, "git_blob": object_id})
    if not files or len(files) > 1000:
        raise ProbeFailure("target inventory is empty or exceeds this probe's reviewed bound")
    return files


def export_source(repository: Path, destination: Path, files, revision=REVISION):
    for item in files:
        path = PurePosixPath(item["path"])
        if path.is_absolute() or ".." in path.parts or item["mode"] not in {"100644", "100755"}:
            raise ProbeFailure("export requires safe file members from the exact inventory")
    archive = command(["git", "-C", str(repository), "archive", "--format=tar", revision]).stdout
    if len(archive) > 20 * 1024 * 1024:
        raise ProbeFailure("target archive exceeds the reviewed bound")
    expected = {item["path"]: item for item in files}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            if member.isdir():
                continue
            item = expected.get(member.name)
            if item is None or not member.isfile() or member.name in seen:
                raise ProbeFailure("archive is not exactly the fixed Git file inventory")
            body = source.extractfile(member).read()
            blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            if blob != item["git_blob"]:
                raise ProbeFailure("archive bytes do not match the Git blob")
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            target.chmod(0o755 if item["mode"] == "100755" else 0o644)
            item["content_hash"] = digest(body)
            seen.add(member.name)
    if seen != expected.keys():
        raise ProbeFailure("archive omitted a fixed source file")


def pinned_image(image: str):
    data = json.loads(command(["docker", "image", "inspect", image]).stdout)[0]
    return {"requested": image, "image_id": data["Id"], "architecture": data["Architecture"]}


def image_identity(image: str, user: str):
    values = []
    for option in ("-u", "-g"):
        output = command(["docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only",
                          "--cap-drop=ALL", "--entrypoint", "id", image, option, user]).stdout.decode().strip()
        if not output.isdigit() or not 1 <= int(output) <= 65535:
            raise ProbeFailure("trusted service image must have a non-root identity")
        values.append(int(output))
    return tuple(values)


def jar_inventory(jar: Path):
    assets = []
    with zipfile.ZipFile(jar) as source:
        entries = [item for item in source.infolist() if not item.is_dir() and (
            item.filename.startswith("BOOT-INF/lib/") or item.filename.startswith("BOOT-INF/classes/"))]
        if (not entries or len(entries) > 4096 or sum(item.file_size for item in entries) > 256 * 1024 * 1024
                or len({item.filename for item in entries}) != len(entries)):
            raise ProbeFailure("runtime archive inventory is empty, duplicate or exceeds the bound")
        for item in sorted(entries, key=lambda item: item.filename):
            if ".." in PurePosixPath(item.filename).parts:
                raise ProbeFailure("runtime archive contains an unsafe member")
            assets.append({"path": item.filename, "bytes": item.file_size,
                           "content_hash": digest(source.read(item))})
    return {"assets": assets, "inventory_hash": digest(json.dumps(assets, sort_keys=True).encode()),
            "runtime_library_count": sum(item["path"].startswith("BOOT-INF/lib/") for item in assets),
            "compiled_class_count": sum(item["path"].endswith(".class") for item in assets)}


def build_args(name, image, source: Path, cache: Path):
    return ["docker", "run", "--rm", "--pull=never", "--name", name, "--network", "none",
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=256", "--memory=2g", "--cpus=2", "--tmpfs", "/tmp:rw,size=512m",
            "--mount", "type=bind,src=" + str(source) + ",dst=/work",
            "--mount", "type=bind,src=" + str(cache) + ",dst=/cache,readonly",
            "--workdir", "/work", "--entrypoint", "mvn", image, "--batch-mode", "--offline",
            "-Duser.home=/tmp", "-Dmaven.repo.local=/cache", "verify"]


class DockerResources:
    def __init__(self):
        self.prefix = "nasus-exweb-" + uuid4().hex[:16]
        self.owner = self.prefix.removeprefix("nasus-exweb-")
        self.containers = []
        self.network_created = False
        self.extra_networks = []

    def create_network(self):
        self.network_created = True
        command(["docker", "network", "create", "--internal", "--label", OWNER_LABEL + "=" + self.owner, self.prefix])

    def container(self, suffix, image, args, env=None):
        name = self.prefix + "-" + suffix
        # Register cleanup before create: a timed-out Docker client can still create a resource.
        self.containers.append(name)
        command(["docker", "run", "--detach", "--pull=never", "--name", name,
                 "--label", OWNER_LABEL + "=" + self.owner,
                 "--network", self.prefix, "--cap-drop=ALL", "--security-opt=no-new-privileges",
                 "--pids-limit=256", "--memory=1g", "--cpus=2", *args, image], env=env)
        return name

    def close(self):
        failures = []
        for name in reversed(self.containers):
            command(["docker", "rm", "--force", "--volumes", name], check=False)
            inspect = command(["docker", "container", "inspect", name], check=False)
            if not resource_absent(inspect, name):
                failures.append(name)
        networks = ([self.prefix] if self.network_created else []) + self.extra_networks
        for network in reversed(networks):
            command(["docker", "network", "rm", network], check=False)
            if not resource_absent(command(["docker", "network", "inspect", network], check=False), network):
                failures.append(network)
        return {"verified": not failures, "remaining_owned_resources": failures}


def resource_absent(result, name):
    if result.returncode == 0:
        return False
    message = result.stdout.decode("utf-8", errors="replace").lower()
    # A daemon/client failure is not authoritative evidence of resource removal.
    return name.lower() in message and (
        "no such object" in message or "no such container" in message or "no such network" in message
        or ("network " + name.lower() + " not found") in message)


def wait_for(callback, seconds=90):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if callback():
            return
        time.sleep(0.3)
    raise ProbeFailure("owned target did not become ready within the probe timeout")


class DockerHttpTransport(httpx.BaseTransport):
    """Execute genuine HTTP inside the owned namespace; expose no target port to the host."""
    def __init__(self, container):
        self.container = container

    def handle_request(self, request):
        if request.url.scheme != "http" or request.url.host != "127.0.0.1" or request.url.port != 8080:
            raise ProbeFailure("target HTTP is confined to the owned container's loopback")
        args = ["docker", "exec", "--interactive", self.container, "curl", "--noproxy", "*",
                "--silent", "--show-error", "--include", "--max-time", "5", "--proto", "=http",
                "--request", request.method, "--url", str(request.url), "--header", "Accept-Encoding: identity"]
        for key, value in request.headers.items():
            if key.lower() != "accept-encoding":
                args.extend(["--header", key + ": " + value])
        if request.content:
            args.extend(["--data-binary", "@-"])
        try:
            result = command(args, timeout=10, check=False, input=request.content)
        except subprocess.TimeoutExpired as exc:
            raise httpx.ConnectError("owned target HTTP timed out", request=request) from exc
        if result.returncode:
            raise httpx.ConnectError("owned target HTTP is not available", request=request)
        try:
            header, body = result.stdout.split(b"\r\n\r\n", 1)
            lines = header.split(b"\r\n")
            status = int(lines[0].split()[1])
            headers = [tuple(line.split(b":", 1)) for line in lines[1:]]
            headers = [(key.strip(), value.strip()) for key, value in headers if key.lower() != b"transfer-encoding"]
        except (ValueError, IndexError) as exc:
            raise ProbeFailure("owned target did not return a complete HTTP response") from exc
        return httpx.Response(status, headers=headers, content=body)


def session_observations(client, checks, evidence):
    headers = {"X-Tenant-Id": "nasus-probe-a", "X-User-Id": "owner-a"}
    path = "/api/v1/finance/chat/sessions"

    def request(key, method, url, *, identity=headers, payload=None):
        response = client.request(method, url, headers=identity, json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {"non_json_body_hash": digest(response.content)}
        evidence.append({"check_id": key, "method": method, "path": url,
                         "identity": identity, "request": payload, "status": response.status_code,
                         "response": body, "response_hash": digest(response.content)})
        return response.status_code, body

    status, session = request("session_create", "POST", path, payload={"title": "Native exweb session", "channel": "web"})
    checks["session_create"] = (status == 200 and isinstance(session, dict) and session.get("status") == "ACTIVE"
                                and session.get("tenantId") == "nasus-probe-a"
                                and session.get("userId") == "owner-a"
                                and session.get("title") == "Native exweb session"
                                and isinstance(session.get("sessionId"), str))
    if not checks["session_create"]:
        raise ProbeFailure("native session creation did not satisfy the source-bound probe oracle")
    ident = session["sessionId"]
    status, body = request("owner_read", "GET", path + "/" + ident)
    checks["owner_read"] = status == 200 and body == session
    status, body = request("owner_list", "GET", path)
    checks["owner_list"] = status == 200 and isinstance(body, list) and session in body
    for label, identity in (
        ("other_user", {**headers, "X-User-Id": "owner-b"}),
        ("other_tenant", {**headers, "X-Tenant-Id": "nasus-probe-b"}),
    ):
        status, body = request(label + "_list", "GET", path, identity=identity)
        checks[label + "_list"] = status == 200 and body == []
        status, body = request(label + "_read", "GET", path + "/" + ident, identity=identity)
        checks[label + "_read_denied"] = status >= 400 and isinstance(body, dict) and body.get("sessionId") != ident
        # A 500 is not an acceptable authorization API contract, even if content is withheld.
        checks[label + "_read_status"] = status in {403, 404}
    status, body = request("session_close", "POST", path + "/" + ident + "/close")
    checks["session_close"] = status == 200 and isinstance(body, dict) and body.get("status") == "CLOSED" and body.get("sessionId") == ident
    status, body = request("closed_read", "GET", path + "/" + ident)
    checks["closed_read_denied"] = status >= 400 and isinstance(body, dict) and body.get("status") != "ACTIVE"
    checks["closed_read_status"] = status in {404, 409, 410}
    return ident, headers


def require_anonymous_session(status, session):
    if (status != 200 or not isinstance(session, dict)
            or session.get("tenantId") != "default" or session.get("userId") != "anonymous"
            or session.get("status") != "ACTIVE" or type(session.get("sessionId")) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session["sessionId"]) is None):
        raise ProbeFailure("owned HTTP fixture setup did not return the original anonymous session")
    return session["sessionId"]


def runner_http_observations(client, args, deployment, checks, evidence, *, environment_spec, inventory):
    with tempfile.TemporaryDirectory(prefix="nasus-owned-http-registry-", dir=args.report.parent) as directory:
        return _runner_http_observations(client, args, deployment, checks, evidence,
            environment_spec=environment_spec, inventory=inventory, registry=Path(directory) / "registry.json")


def _runner_http_observations(client, args, deployment, checks, evidence, *, environment_spec, inventory, registry):
    """Use the production oracle engine against the actual owned Java loopback.

    Anonymous fixtures are deliberate: draft jobs cannot inject tenant/user or
    credential headers. Protected multi-identity checks remain separate above.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
    from apps.api.app.infrastructure.runner.configured_target_environments import ConfiguredOwnedTargetEnvironments, REGISTRY_SCHEMA
    from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
    from apps.api.app.infrastructure.runner.owned_target_http import ConfiguredOwnedTargetHttpRunner
    from dataclasses import asdict

    node = str(args.node_executable.resolve())
    version = command([node, "--version"]).stdout.decode().strip()
    if not version.startswith("v") or not version.split(".", 1)[0][1:].isdigit() or int(version.split(".", 1)[0][1:]) < 22:
        raise ProbeFailure("HTTP Runner verification requires the existing Node 22+ runtime")
    path = "/api/v1/finance/chat/sessions"
    created = client.post(path, json={"title": "Actual HTTP Runner fixture", "channel": "web"})
    session = created.json()
    evidence.append({"check_id": "runner_fixture_setup", "status": created.status_code, "response": session,
        "response_hash": digest(created.content), "authority": "developer_probe_not_approved_specification"})
    ident = require_anonymous_session(created.status_code, session)
    directory = args.report.with_suffix(".runner")
    directory.mkdir(mode=0o700, exist_ok=False)
    registry.write_text(json.dumps({"schema": REGISTRY_SCHEMA, "environments": [asdict(environment_spec)]}))
    registry.chmod(0o600)
    adapter = ConfiguredOwnedTargetHttpRunner(node_executable=node,
        environments=ConfiguredOwnedTargetEnvironments(registry_path=str(registry)))
    cases = []

    def execute_steps(label, steps, *, protocol="nasus.runner-http-execution.v1"):
        job = AutomationRunnerCommand(job_id="exweb-owned-" + uuid4().hex, project_id=environment_spec.project_id,
            us_id=label, base_url="http://127.0.0.1:8080", steps=tuple(steps), timeout_ms=10000, kind="http",
            http_protocol=protocol,
            metadata={"repository_revision": REVISION, "target_artifact_hash": deployment["jar_hash"],
                "oracle_authority": "developer_probe_not_approved_specification"})
        execution = adapter.execute_owned_http(job, environment_id=environment_spec.environment_id,
            artifact_hash=deployment["jar_hash"], inventory_hash=inventory.inventory_hash, require_work=lambda: None)
        wire, result = execution.request_body, execution.result
        verified = HTTPRunnerObservationVerifier().verify(job, result)
        input_path, result_path = directory / (label + ".request.json"), directory / (label + ".result.json")
        input_path.write_bytes(wire)
        result_path.write_bytes(execution.result_body)
        checks["runner_" + label] = result.status == "passed"
        item = {"case_id": label, "status": result.status, "request_hash": digest(wire),
            "result_hash": digest(execution.result_body), "request_archive": str(input_path), "result_archive": str(result_path),
            "owned_inventory_hash": execution.inventory_hash,
            "observed_assertion_count": verified["observed_assertion_count"], "passed_assertion_count": verified["passed_assertion_count"],
            "failed_assertion_count": verified["failed_assertion_count"], "response_byte_verification": True,
            "receipt_protocol": verified["schema"], "binding_count": len(verified.get("bindings", [])),
            "external_fixture_setup_required": protocol == "nasus.runner-http-execution.v1" and label in {"owner_read", "close", "closed_read"},
            "target_build_verified": False, "business_coverage_verified": False}
        cases.append(item)
        evidence.append({"check_id": "runner_" + label, **item})

    def request_steps(request_id, method, target, expected, *, body="null"):
        steps = [{"action": "request", "request_id": request_id, "method": method, "path": target,
            "headers_json": '{"Accept":"application/json","Content-Type":"application/json"}', "body_json": body}]
        for pointer, value in expected:
            steps.append({"action": "assert_status", "request_id": request_id, "value": str(value)} if pointer is None else
                {"action": "assert_json", "request_id": request_id, "pointer": pointer, "value_json": json.dumps(value, ensure_ascii=False)})
        return steps

    def execute(label, method, target, expected, *, body="null"):
        execute_steps(label, request_steps("original", method, target, expected, body=body))

    execute("health", "GET", "/actuator/health", [(None, 200), ("/status", "UP")])
    execute("create", "POST", path, [(None, 200), ("/tenantId", "default"), ("/userId", "anonymous"), ("/status", "ACTIVE"),
        ("/title", "Actual HTTP Runner created session")], body='{"title":"Actual HTTP Runner created session","channel":"web"}')
    execute("owner_read", "GET", path + "/" + ident, [(None, 200), ("/sessionId", ident), ("/status", "ACTIVE")])
    execute("close", "POST", path + "/" + ident + "/close", [(None, 200), ("/sessionId", ident), ("/status", "CLOSED")])
    execute("closed_read", "GET", path + "/" + ident, [(None, 404)])
    for label, include_closed_read in (("bound_session_lifecycle", False), ("bound_closed_read", True)):
        title = "Actual single-job HTTP session"
        steps = request_steps("create", "POST", path, [(None, 200), ("/tenantId", "default"), ("/userId", "anonymous"),
            ("/status", "ACTIVE"), ("/title", title)], body=json.dumps({"title": title, "channel": "web"}))
        steps.append({"action": "capture_json", "request_id": "create", "pointer": "/sessionId", "binding_id": "session"})
        steps.extend(request_steps("read", "GET", path + "/{{session}}", [(None, 200), ("/status", "ACTIVE"), ("/title", title)]))
        steps.extend(request_steps("close", "POST", path + "/{{session}}/close", [(None, 200), ("/status", "CLOSED"), ("/title", title)]))
        if include_closed_read:
            steps.extend(request_steps("closed", "GET", path + "/{{session}}", [(None, 404)]))
        execute_steps(label, steps, protocol="nasus.runner-http-execution.v2")
    sources = [ROOT / "apps/api/app/infrastructure/runner/owned_target_http.py", *(ROOT / "apps/runner/src" / name for name in (
        "owned-http-cli.mjs", "owned-http-cohort.mjs", "http-job.mjs", "http-bindings.mjs", "http-executor.mjs", "http-transport.mjs", "strict-json.mjs", "execution-receipt.mjs", "docker-http-transport.mjs"))]
    result = {"node_version": version, "executor_sources": [{"path": str(item.relative_to(ROOT)), "content_hash": digest(item.read_bytes())}
        for item in sources], "cases": cases, "fixture_session_id": ident,
        "transport": "configured_owned_target_http_port", "public_runner_api_used": False,
        "inventory": inventory.inventory, "inventory_hash": inventory.inventory_hash,
        "nasus_runplan_verified": False, "execution_authorized": False, "release_authorized": False}
    if getattr(args, "http_fixtures", False):
        from scripts.exweb_http_fixture_probe import observe_exweb_http_fixtures
        result["http_fixtures"] = observe_exweb_http_fixtures(adapter, environment_spec, inventory, deployment, directory, revision=REVISION)
        checks.update(result["http_fixtures"]["checks"])
    return result


def run_probe(args, report):
    repository, cache = args.repository.resolve(), args.maven_cache.resolve()
    files = source_inventory(repository, args.revision)
    images = {key: pinned_image(value) for key, value in (
        ("java_maven", args.maven_image), ("postgres", args.postgres_image), ("redis", args.redis_image))}
    report.update(source={"repository": REPOSITORY, "revision": args.revision, "files": files}, images=images)
    resources = DockerResources()
    application, password = None, None
    report["resource_prefix"] = resources.prefix
    try:
        with tempfile.TemporaryDirectory(prefix="nasus-exweb-runtime-", dir=ROOT / "output") as directory:
            source = Path(directory) / "source"
            source.mkdir()
            export_source(repository, source, files, args.revision)
            report["source"]["inventory_hash"] = digest(json.dumps(files, sort_keys=True).encode())
            oracle_paths = {SOURCE_ROOT + path for path in (
                "application/service/SessionApplicationService.java", "interfaces/chat/ChatSessionController.java",
                "interfaces/chat/dto/FrontChatSessionDto.java", "infrastructure/persistence/InMemorySessionRepository.java")}
            report["oracle_source_files"] = [item for item in files if item["path"] in oracle_paths]
            if len(report["oracle_source_files"]) != len(oracle_paths):
                raise ProbeFailure("reviewed oracle sources are missing")
            report["stage"] = "build"
            build_name = resources.prefix + "-build"
            resources.containers.append(build_name)
            build = command(build_args(build_name, images["java_maven"]["image_id"], source, cache),
                            timeout=180, check=False)
            args.report.with_suffix(".build.log").write_bytes(build.stdout)
            report["build"] = {"return_code": build.returncode, "log_hash": digest(build.stdout),
                               "offline": True, "source_modified": False}
            changed = [item["path"] for item in files if digest((source / item["path"]).read_bytes()) != item["content_hash"]]
            report["build"]["source_modified"] = bool(changed)
            if build.returncode or changed:
                raise ProbeFailure("fixed target build failed or changed its original input")
            jar = source / "target/FinanceEXChatService-1.0.0-RELEASE.jar"
            report["build"]["jar_hash"] = digest(jar.read_bytes())
            report["build"]["jar_bytes"] = jar.stat().st_size
            report["build"]["runtime_inputs"] = jar_inventory(jar)
            report["stage"] = "startup"
            resources.create_network()
            password = secrets.token_hex(24)
            pg_uid, pg_gid = image_identity(images["postgres"]["image_id"], "postgres")
            redis_uid, redis_gid = image_identity(images["redis"]["image_id"], "redis")
            postgres = resources.container("pg", images["postgres"]["image_id"], [
                "--user", f"{pg_uid}:{pg_gid}",
                "--env", "POSTGRES_DB=exweb_probe", "--env", "POSTGRES_USER=exweb_probe",
                "--env", "POSTGRES_PASSWORD", "--tmpfs", f"/var/lib/postgresql/data:rw,size=512m,uid={pg_uid},gid={pg_gid}"],
                {"POSTGRES_PASSWORD": password})
            resources.container("redis", images["redis"]["image_id"], [
                "--user", f"{redis_uid}:{redis_gid}", "--tmpfs", f"/data:rw,size=128m,uid={redis_uid},gid={redis_gid}"])
            wait_for(lambda: command(["docker", "exec", postgres, "pg_isready", "-U", "exweb_probe", "-d", "exweb_probe"], check=False).returncode == 0)
            java_args = ["--read-only", "--tmpfs", "/tmp:rw,size=256m",
                         "--user", "65534:65534",
                         "--mount", "type=bind,src=" + str(jar) + ",dst=/app/target.jar,readonly",
                         "--entrypoint", "java", "--env", "FINANCEEX_DB_PASSWORD"]
            # Docker arguments are options before IMAGE, JVM arguments are appended afterwards.
            application = resources.prefix + "-app"
            resources.containers.append(application)
            command(["docker", "run", "--detach", "--pull=never", "--name", application,
                     "--label", OWNER_LABEL + "=" + resources.owner,
                     "--network", resources.prefix, "--cap-drop=ALL", "--security-opt=no-new-privileges",
                     "--pids-limit=256", "--memory=1g", "--cpus=2", *java_args,
                     images["java_maven"]["image_id"], "-jar", "/app/target.jar",
                     "--spring.sql.init.mode=always", "--spring.datasource.url=jdbc:postgresql://" + postgres + ":5432/exweb_probe",
                     "--spring.datasource.username=exweb_probe", "--spring.data.redis.host=" + resources.prefix + "-redis",
                     "--financeex.agent.agentscope.base-url=http://127.0.0.1:1/v1"],
                    env={"FINANCEEX_DB_PASSWORD": password})
            runtime = json.loads(command(["docker", "container", "inspect", application]).stdout)[0]
            dependency_spec = []
            for role, user in (("pg", f"{pg_uid}:{pg_gid}"), ("redis", f"{redis_uid}:{redis_gid}")):
                item = json.loads(command(["docker", "container", "inspect", resources.prefix + "-" + role]).stdout)[0]
                dependency_spec.append(OwnedDependency(role, item["Id"], item["Image"], user))
            network = json.loads(command(["docker", "network", "inspect", resources.prefix]).stdout)[0]
            environment_spec = OwnedEnvironment("exweb-development-probe", resources.prefix, resources.owner, resources.prefix,
                runtime["Id"], runtime["Image"], network["Id"], tuple(dependency_spec))
            environment_inspector = OwnedTargetEnvironmentInspector(environment_spec)
            before_environment = environment_inspector.inspect(report["build"]["jar_hash"], require_work=lambda: None)
            report["native_environment"] = {"before": {"inventory": before_environment.inventory,
                "inventory_hash": before_environment.inventory_hash, "observed_at": before_environment.observed_at}}
            report["deployment"] = {"container_id": runtime["Id"], "image_id": runtime["Image"],
                                    "jar_hash": report["build"]["jar_hash"], "internal_network": True,
                                    "developer_resources_used": False, "model_outbound_permitted": False,
                                    "host_ports_exposed": False}
            with httpx.Client(base_url="http://127.0.0.1:8080", timeout=5, trust_env=False,
                              transport=DockerHttpTransport(application)) as client:
                def ready():
                    try:
                        response = client.get("/actuator/health")
                        return response.status_code == 200 and response.json().get("status") == "UP"
                    except (httpx.HTTPError, ValueError):
                        return False
                wait_for(ready)
                if args.isolation_canaries:
                    report["stage"] = "isolation_canaries"
                    report["isolation_canaries"] = isolation_observations(command, resources, environment_inspector,
                        report["build"]["jar_hash"], Path(directory), images["java_maven"]["image_id"])
                    report["checks"].update(report["isolation_canaries"]["checks"])
                report["stage"] = "native_assertions"
                session_id, headers = session_observations(client, report["checks"], report["evidence"])
                sql = "SELECT count(*) FROM chat_session WHERE id = '" + session_id.replace("'", "''") + "'"
                row = command(["docker", "exec", postgres, "psql", "-U", "exweb_probe", "-d", "exweb_probe", "-tAc", sql]).stdout.decode().strip()
                report["checks"]["session_in_postgres"] = row == "1"
                report["evidence"].append({"check_id": "session_in_postgres", "row_count": row})
                command(["docker", "restart", application])
                wait_for(ready)
                response = client.get("/api/v1/finance/chat/sessions", headers=headers)
                body = response.json()
                report["checks"]["session_survives_restart"] = (response.status_code == 200 and isinstance(body, list)
                    and any(item.get("sessionId") == session_id and item.get("status") == "CLOSED" for item in body))
                report["evidence"].append({"check_id": "session_survives_restart", "status": response.status_code,
                                           "response": body, "response_hash": digest(response.content)})
                if args.http_runner:
                    report["stage"] = "production_http_runner"
                    runner_inventory = environment_inspector.inspect(report["build"]["jar_hash"], require_work=lambda: None)
                    report["http_runner"] = runner_http_observations(client, args, report["deployment"], report["checks"], report["evidence"],
                        environment_spec=environment_spec, inventory=runner_inventory)
                if digest(jar.read_bytes()) != report["build"]["jar_hash"]:
                    raise ProbeFailure("mounted runtime artifact changed during target execution")
                report["deployment"]["artifact_unchanged_after_execution"] = True
                after_environment = environment_inspector.inspect(report["build"]["jar_hash"], require_work=lambda: None)
                report["native_environment"]["after"] = {"inventory": after_environment.inventory,
                    "inventory_hash": after_environment.inventory_hash, "observed_at": after_environment.observed_at}
                report["native_environment"]["canonical_runplan_verified"] = False
            report["stage"] = "observed"
    finally:
        try:
            for name in resources.containers:
                if name == application or not name.endswith(("-pg", "-redis")):
                    continue
                result = command(["docker", "logs", name], check=False)
                if result.returncode == 0:
                    logs = result.stdout.replace(password.encode(), b"[REDACTED]") if password else result.stdout
                    path = args.report.with_suffix("." + name.rsplit("-", 1)[-1] + ".log")
                    path.write_bytes(logs)
                    report.setdefault("infrastructure_log_hashes", {})[name.rsplit("-", 1)[-1]] = digest(logs)
            if application:
                logs = command(["docker", "logs", application], check=False).stdout
                if password:
                    logs = logs.replace(password.encode(), b"[REDACTED]")
                args.report.with_suffix(".runtime.log").write_bytes(logs)
                report["runtime_log_hash"] = digest(logs)
        finally:
            report["cleanup"] = resources.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-reviewed-target", action="store_true")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--maven-cache", type=Path, required=True)
    parser.add_argument("--maven-image", default=MAVEN_IMAGE)
    parser.add_argument("--postgres-image", default=POSTGRES_IMAGE)
    parser.add_argument("--redis-image", default=REDIS_IMAGE)
    parser.add_argument("--http-runner", action="store_true", help="Also verify the production HTTP oracle engine against the isolated target")
    parser.add_argument("--http-fixtures", action="store_true", help="Also exercise explicit fixture setup/cleanup; not a canonical execution grant")
    parser.add_argument("--isolation-canaries", action="store_true", help="Add owned positive-control network/file comparisons; not universal isolation authority")
    parser.add_argument("--node-executable", type=Path, default=Path(shutil.which("node") or "node"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.execute_reviewed_target:
        parser.error("execution requires --execute-reviewed-target, not a retrieval request")
    if args.http_fixtures and not args.http_runner:
        parser.error("--http-fixtures requires the original --http-runner evidence")
    args.report = args.report.resolve()
    if any(path.exists() for path in (args.report, *(args.report.with_suffix(suffix) for suffix in (
            ".build.log", ".runtime.log", ".pg.log", ".redis.log", ".runner")))):
        parser.error("choose a new report path; existing evidence is never overwritten")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "output").mkdir(exist_ok=True)
    report = {"schema": "nasus.exweb-native-runtime-probe.v1", "stage": "source_verification",
              "recorded_at": datetime.now(timezone.utc).isoformat(), "checks": {}, "evidence": [],
              "oracle_authority": "developer_probe_not_approved_specification",
              "nasus_runplan_verified": False, "llm_verified": False, "release_authorized": False}
    try:
        run_probe(args, report)
    except (ProbeFailure, IsolationProbeFailure, subprocess.TimeoutExpired, OSError, ValueError, KeyError, IndexError,
            TypeError, httpx.HTTPError, zipfile.BadZipFile) as exc:
        report["error"] = type(exc).__name__
        if isinstance(exc, ProbeFailure):
            report["error_message"] = str(exc)
    passed = bool(report["checks"]) and all(report["checks"].values()) and not report.get("error") and report.get("cleanup", {}).get("verified")
    report["status"] = "passed" if passed else "failed"
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "stage": report["stage"],
                      "passed_checks": sum(report["checks"].values()), "total_checks": len(report["checks"]),
                      "report": str(args.report), "cleanup_verified": report.get("cleanup", {}).get("verified")}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
