#!/usr/bin/env python3
"""M0 live adapter probe. Never substitutes for governed M1-M5 loop evidence."""
import argparse
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.app.domain.quality_loop.build_profiles import PYTHON_BUILD
from apps.api.app.domain.quality_loop.environment_profiles import PYTHON_ENVIRONMENT
from apps.api.app.domain.quality_loop.native_build import NativeBuildRequest, build_receipt
from apps.api.app.domain.quality_loop.native_environment import OWNER_LABEL, OwnedEnvironment, OwnedDependency
from apps.api.app.domain.shared.native_build_source import NativeBuildFile, FrozenNativeBuildSource, NativeBuildSourcePin, byte_digest
from apps.api.app.infrastructure.runner.native_maven_build import bounded_command
from apps.api.app.infrastructure.runner.native_python_build import OfflinePythonNativeBuild
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.app.infrastructure.runner.owned_target_health import OwnedTargetHealthInspector
from realworld_contract import CASES, run_cases

BASE = "87dd078c883a046f5ff20269df2fb004d8b5f83f"
SPEC = "25588846c314b15a5e427ffe816e6b4af7be68c7"
SPEC_FILES = ("LICENSE", "specs/api/openapi.yml", "specs/api/hurl/articles.hurl",
    "specs/api/hurl/errors_articles.hurl", "specs/api/hurl/errors_authorization.hurl",
    "docs/src/content/docs/specifications/backend/endpoints.md")
LOCK_CODE = 'import hashlib,importlib.metadata,json; p=sorted((d.metadata["Name"].lower(),d.version) for d in importlib.metadata.distributions()); print(json.dumps({"packages":p,"hash":"sha256:"+hashlib.sha256(json.dumps(p,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()}))'


def call(args, *, timeout=30, max_bytes=2 * 1024 * 1024, input_body=None):
    code, body = bounded_command(args, timeout=timeout, max_bytes=max_bytes, input_body=input_body)
    if code:
        raise RuntimeError("command failed: " + " ".join(args[:3]) + ": " + body.decode(errors="replace")[:500])
    return body


def git(repo, *args):
    return call(["git", "-C", str(repo), *args])


def captured_source(repo, commit):
    files = []
    for record in git(repo, "ls-tree", "-rz", commit).split(b"\0"):
        if not record: continue
        header, path = record.split(b"\t", 1)
        mode, kind, blob = header.split()
        if kind == b"commit": continue  # Frontends/spec submodules are separate sources, not application files.
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError("unsupported source member")
        files.append(NativeBuildFile(path.decode(), git(repo, "cat-file", "blob", blob.decode())))
    files = tuple(sorted(files, key=lambda f: f.path))
    digest = byte_digest(b"".join(f.path.encode() + b"\0" + f.body for f in files))
    # Diagnostic pins are deliberately not persisted as published Nasus images.
    pin = NativeBuildSourcePin("realworld-adapter-probe", "unpublished-diagnostic", digest,
        "git-tree-diagnostic", digest, "code", commit, "realworld", commit, digest, digest)
    return FrozenNativeBuildSource(pin, files)


def verify_revisions(repo, defect, fix):
    commits = {"original": BASE, "defect": git(repo, "rev-parse", "--verify", defect + "^{commit}").decode().strip(),
               "fix": git(repo, "rev-parse", "--verify", fix + "^{commit}").decode().strip()}
    for value in commits.values():
        if not re.fullmatch(r"[a-f0-9]{40}", value): raise ValueError("fixed commit required")
    git(repo, "merge-base", "--is-ancestor", BASE, commits["defect"])
    git(repo, "merge-base", "--is-ancestor", commits["defect"], commits["fix"])
    if git(repo, "diff", BASE, commits["fix"]): raise ValueError("fix must restore the original captured tree")
    changed = git(repo, "diff", "--name-only", BASE, commits["defect"]).decode().splitlines()
    if changed != ["apps/articles/api.py"]: raise ValueError("controlled defect scope differs")
    original = git(repo, "show", BASE + ":apps/articles/api.py")
    head, update = original.split(b"def update(", 1)
    changed = update.replace(b"    if request.user != article.author:\n        raise AuthorizationError\n",
        b"    # Nasus controlled acceptance defect: ownership check intentionally removed.\n", 1)
    if git(repo, "show", commits["defect"] + ":apps/articles/api.py") != head + b"def update(" + changed:
        raise ValueError("controlled defect patch differs")
    return commits


def capture_spec(repo, folder):
    commit = git(repo, "rev-parse", "--verify", SPEC + "^{commit}").decode().strip()
    if commit != SPEC:
        raise ValueError("specification commit differs")
    evidence = []
    for path in SPEC_FILES:
        body = git(repo, "show", SPEC + ":" + path)
        target = folder / "specification" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        evidence.append({"path": path, "commit": SPEC, "content_hash": byte_digest(body),
            "byte_count": len(body), "evidence_path": str(target.relative_to(folder))})
    return {"repository": "https://github.com/realworld-apps/realworld", "commit": SPEC,
        "files": evidence, "human_approval_recorded": False, "hurl_executed": False}


def runner_probe(inventory):
    # Exercise the existing private Runner transport, without claiming governed case execution.
    job = {"job_id": "realworld-runtime-" + secrets.token_hex(8), "project_id": inventory["project_id"],
        "us_id": "US-001-runtime-probe", "base_url": "http://127.0.0.1:8080", "timeout_ms": 30000,
        "execution_kind": "http", "receipt_protocol": "nasus.runner-http-execution.v1",
        "steps": [{"action": "request", "request_id": "tags", "method": "GET", "path": "/api/tags",
            "headers_json": "{}", "body_json": "null"},
            {"action": "assert_status", "request_id": "tags", "value": "200"},
            {"action": "assert_json", "request_id": "tags", "pointer": "/tags", "value_json": "[]"}]}
    wire = json.dumps(job, separators=(",", ":")).encode()
    envelope = {"schema": "nasus.owned-http-command.v1", "inventory": inventory,
        "wire_body_base64": base64.b64encode(wire).decode()}
    result = json.loads(call(["node", str(ROOT / "apps/runner/src/owned-http-cli.mjs"), "--execute-owned-target-http"],
        timeout=45, input_body=json.dumps(envelope).encode()))
    if result.get("status") != "passed":
        raise RuntimeError("registered Runner transport probe failed")
    return result


class Deployment:
    def __init__(self, image, pg_image, artifact, owner):
        self.owner, self.prefix = owner, "nasus-target-" + owner
        self.image, self.pg_image, self.artifact = image, pg_image, artifact
        self.created = []
        self.network = None
        self.cleaned = False
        self.password = secrets.token_urlsafe(24)

    def docker(self, *args, **kwargs): return call(["docker", *args], **kwargs).decode().strip()

    def start(self):
        self.network = self.docker("network", "create", "--internal", "--label", OWNER_LABEL + "=" + self.owner, self.prefix)
        common = ["--pull=never", "--network", self.prefix, "--label", OWNER_LABEL + "=" + self.owner,
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=128", "--memory=512m", "--cpus=1"]
        pg_name = self.prefix + "-pg"
        self.created.append(pg_name)
        pg = self.docker("run", "-d", "--name", pg_name, *common, "--user", "999:999",
            "--tmpfs", "/var/lib/postgresql/data:rw,uid=999,gid=999,size=256m",
            "-e", "POSTGRES_USER=nasus", "-e", "POSTGRES_DB=realworld", "-e", "POSTGRES_PASSWORD=" + self.password,
            self.pg_image)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            code, _ = bounded_command(["docker", "exec", pg, "pg_isready", "-U", "nasus", "-d", "realworld"], timeout=5, max_bytes=4096)
            if code == 0: break
            time.sleep(0.25)
        else: raise RuntimeError("PostgreSQL did not become ready")
        app_name = self.prefix + "-app"
        self.created.append(app_name)
        # Temporary bootstrap container is removed before the inspected application epoch.
        app_args = [*common, "--read-only", "--user", "65534:65534", "--tmpfs", "/tmp:rw,size=64m",
            "--mount", "type=bind,src=" + str(self.artifact) + ",dst=/app/target.pyz,readonly",
            "-e", "DATABASE_URL=postgresql://nasus:" + self.password + "@" + pg_name + ":5432/realworld",
            "-e", "ALLOWED_HOSTS=127.0.0.1;localhost", "--entrypoint", "python", self.image]
        migration = self.prefix + "-migration"
        self.created.append(migration)
        self.docker("run", "--rm", "--name", migration, *app_args, "/app/target.pyz", "migrate", "--noinput", timeout=60)
        app = self.docker("run", "-d", "--name", app_name, *app_args,
            "/app/target.pyz", "runserver", "0.0.0.0:8080", "--noreload")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            code, body = bounded_command(["docker", "exec", app, "curl", "--silent", "--max-time", "2", "--write-out", "%{http_code}",
                "http://127.0.0.1:8080/api/tags"], timeout=5, max_bytes=65536)
            if code == 0 and body.endswith(b"200"): break
            time.sleep(0.25)
        else:
            raise RuntimeError("RealWorld failed readiness: " + self.docker("logs", "--tail", "12", app)[:1000])
        self.spec = OwnedEnvironment("realworld-adapter-probe", self.owner, self.owner, self.prefix, app, self.image, self.network,
            (OwnedDependency("pg", pg, self.pg_image, "999:999"),), PYTHON_ENVIRONMENT)
        return self.spec

    def cleanup(self):
        for name in reversed(self.created):
            code, body = bounded_command(["docker", "inspect", "--format", "{{json .Config.Labels}}", name], timeout=10, max_bytes=65536)
            if code:
                if b"no such object:" not in body.lower() or name.encode() not in body:
                    raise RuntimeError("cleanup ownership could not be checked")
                continue
            if json.loads(body).get(OWNER_LABEL) != self.owner: raise RuntimeError("cleanup ownership mismatch")
            self.docker("rm", "-f", "-v", name)
        if self.network:
            labels = json.loads(self.docker("network", "inspect", "--format", "{{json .Labels}}", self.network))
            if labels.get(OWNER_LABEL) != self.owner: raise RuntimeError("network cleanup ownership mismatch")
            self.docker("network", "rm", self.network)
        self.cleaned = not self.docker("ps", "-aq", "--filter", "label=" + OWNER_LABEL + "=" + self.owner)
        self.cleaned = self.cleaned and not self.docker("network", "ls", "-q", "--filter", "label=" + OWNER_LABEL + "=" + self.owner)
        if not self.cleaned: raise RuntimeError("cleanup could not be verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("runtime", "full"), default="full")
    parser.add_argument("--repo", type=Path, default=ROOT / ".nasus/validation/realworld-django-ninja")
    parser.add_argument("--spec-repo", type=Path, default=ROOT / ".nasus/validation/realworld-spec")
    parser.add_argument("--defect-ref", default="codex/nasus-realworld-defect")
    parser.add_argument("--fix-ref", default="codex/nasus-realworld-fix")
    parser.add_argument("--image", help="Pinned Python runtime image sha256 ID")
    parser.add_argument("--pg-image", help="Pinned PostgreSQL image sha256 ID")
    args = parser.parse_args()
    if args.phase == "full":
        parser.exit(2, "Full M1-M5 acceptance is not implemented; runtime-only evidence cannot pass the loop gate. Use --phase runtime for M0.\n")
    if not args.image or not args.pg_image:
        parser.error("runtime verification requires --image and --pg-image")
    if any(not re.fullmatch(r"sha256:[a-f0-9]{64}", image) for image in (args.image, args.pg_image)):
        parser.error("mutable image names are not accepted")
    folder = ROOT / "output/realworld" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    report = {"schema": "nasus.realworld-runtime-probe.v1", "stage": "M0", "business_loop_verified": False,
              "spec_commit": SPEC, "runs": [], "status": "failed"}
    try:
        commits = verify_revisions(args.repo, args.defect_ref, args.fix_ref)
        report["commits"] = commits
        report["specification"] = capture_spec(args.spec_repo, folder)
        lock = json.loads(call(["docker", "run", "--rm", "--network", "none", "--read-only", "--user", "65534:65534",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--entrypoint", "python", args.image, "-I", "-c", LOCK_CODE]))
        report["dependency_lock"] = lock
        for variant, commit in commits.items():
            print("Verifying " + variant + " " + commit, flush=True)
            request = NativeBuildRequest(captured_source(args.repo, commit), "target/realworld.pyz", adapter=PYTHON_BUILD)
            output = OfflinePythonNativeBuild(image_id=args.image, dependency_lock_hash=lock["hash"]).build(request)
            artifact = folder / (variant + ".pyz")
            artifact.write_bytes(output.artifact)
            artifact.chmod(0o444)
            run = {"variant": variant, "commit": commit, "build": build_receipt(request, output), "cleanup_verified": False}
            report["runs"].append(run)
            deployment = Deployment(args.image, args.pg_image, artifact, secrets.token_hex(8))
            try:
                spec = deployment.start()
                observation = OwnedTargetEnvironmentInspector(spec).inspect(byte_digest(output.artifact), require_work=lambda: None)
                run["environment"] = asdict(observation)
                health = OwnedTargetHealthInspector(spec).inspect(byte_digest(output.artifact), require_work=lambda: None)
                if not health.target_health_verified or not health.dependency_health_verified:
                    raise RuntimeError("real environment health failed")
                run["health"] = health.payload()
                run["runner_probe"] = runner_probe(observation.inventory)
                run["cases"] = run_cases(bounded_command, spec.container_id)
            finally:
                deployment.cleanup()
                run["cleanup_verified"] = deployment.cleaned
        valid = True
        for run in report["runs"]:
            cases = run["cases"]
            expected = {"other_author_denied"} if run["variant"] == "defect" else set()
            failed = {c["case_id"] for c in cases if c["status"] == "failed"}
            valid = valid and failed == expected and len(cases) == len(CASES) and all(c["status"] in {"passed", "failed"}
                and c["cleanup"] == "article_removed" for c in cases)
        report["status"] = "passed" if valid else "contract_mismatch"
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        path = folder / "report.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(str(path), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
