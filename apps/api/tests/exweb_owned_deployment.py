"""Opt-in native validation resources; never a production deploy or business oracle."""
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import secrets

from apps.api.app.application.quality_loop.native_build_inputs import NativeBuildCommand
from apps.api.app.domain.quality_loop.native_build import NativeBuildRequest
from apps.api.app.domain.quality_loop.native_environment import OWNER_LABEL, OwnedDependency, OwnedEnvironment
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.infrastructure.runner.configured_target_environments import REGISTRY_SCHEMA


def runtime_probe():
    path = Path(__file__).resolve().parents[3] / "scripts" / "verify-exweb-runtime.py"
    spec = importlib.util.spec_from_file_location("nasus_owned_exweb_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OriginalExwebDeployment:
    def __init__(self, directory):
        if os.environ.get("EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD") != "1":
            raise ValueError("explicit native exweb execution opt-in is required")
        self.directory = Path(directory)
        self.directory.mkdir()
        self.probe = runtime_probe()
        self.resources = self.probe.DockerResources()
        self.spec = None
        self.registry = self.directory / "registry.json"

    def original_jar(self, built, builds):
        stored = builds.repository.inspect(built["project_id"], built["invocation_id"])
        command = NativeBuildCommand.model_validate(stored["request"])
        source = builds.sources.read(**{key: getattr(command, key) for key in
            ("project_id", "image_revision_id", "image_artifact_hash", "binding_id", "source_revision_id")})
        request = NativeBuildRequest(source, command.artifact_path, command.expected_artifact_hash)
        metadata = stored["result"]
        archive = builds.artifacts.read(metadata["build_id"], request,
            artifact_ref=metadata["artifact_ref"], artifact_hash=metadata["artifact_hash"])
        assert archive["receipt"] == built["receipt"]
        assert byte_digest(archive["artifact"]) == archive["receipt"]["artifact"]["content_hash"]
        jar = self.directory / "original-target.jar"
        jar.write_bytes(archive["artifact"])
        jar.chmod(0o444)
        return jar

    def start(self, built, builds):
        assert self.spec is None
        jar = self.original_jar(built, builds)
        probe, resources = self.probe, self.resources
        java = probe.pinned_image(os.environ["EXWEB_NATIVE_MAVEN_IMAGE_ID"])["image_id"]
        postgres_image = probe.pinned_image(os.environ["EXWEB_NATIVE_POSTGRES_IMAGE_ID"])["image_id"]
        redis_image = probe.pinned_image(os.environ["EXWEB_NATIVE_REDIS_IMAGE_ID"])["image_id"]
        resources.create_network()
        password = secrets.token_hex(24)
        pg_uid, pg_gid = probe.image_identity(postgres_image, "postgres")
        redis_uid, redis_gid = probe.image_identity(redis_image, "redis")
        postgres = resources.container("pg", postgres_image, ["--user", f"{pg_uid}:{pg_gid}",
            "--env", "POSTGRES_DB=exweb_probe", "--env", "POSTGRES_USER=exweb_probe",
            "--env", "POSTGRES_PASSWORD", "--tmpfs", f"/var/lib/postgresql/data:rw,size=512m,uid={pg_uid},gid={pg_gid}"],
            {"POSTGRES_PASSWORD": password})
        resources.container("redis", redis_image, ["--user", f"{redis_uid}:{redis_gid}",
            "--tmpfs", f"/data:rw,size=128m,uid={redis_uid},gid={redis_gid}"])
        probe.wait_for(lambda: probe.command(["docker", "exec", postgres, "pg_isready", "-U", "exweb_probe", "-d", "exweb_probe"], check=False).returncode == 0)
        application = resources.prefix + "-app"
        resources.containers.append(application)
        probe.command(["docker", "run", "--detach", "--pull=never", "--name", application,
            "--label", OWNER_LABEL + "=" + resources.owner, "--network", resources.prefix,
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=1g", "--cpus=2",
            "--read-only", "--tmpfs", "/tmp:rw,size=256m", "--user", "65534:65534",
            "--mount", "type=bind,src=" + str(jar) + ",dst=/app/target.jar,readonly",
            "--entrypoint", "java", "--env", "FINANCEEX_DB_PASSWORD", java, "-jar", "/app/target.jar",
            "--spring.sql.init.mode=always", "--spring.datasource.url=jdbc:postgresql://" + postgres + ":5432/exweb_probe",
            "--spring.datasource.username=exweb_probe", "--spring.data.redis.host=" + resources.prefix + "-redis",
            "--financeex.agent.agentscope.base-url=http://127.0.0.1:1/v1"], env={"FINANCEEX_DB_PASSWORD": password})

        def instance(name):
            return json.loads(probe.command(["docker", "container", "inspect", "--format",
                '{"Id":{{json .Id}},"Image":{{json .Image}}}', name]).stdout)
        target = instance(application)
        dependencies = []
        for role, user in (("pg", f"{pg_uid}:{pg_gid}"), ("redis", f"{redis_uid}:{redis_gid}")):
            item = instance(resources.prefix + "-" + role)
            dependencies.append(OwnedDependency(role, item["Id"], item["Image"], user))
        network_id = json.loads(probe.command(["docker", "network", "inspect", "--format", "{{json .Id}}", resources.prefix]).stdout)
        self.spec = OwnedEnvironment(built["project_id"], resources.prefix, resources.owner, resources.prefix,
            target["Id"], target["Image"], network_id, tuple(dependencies))
        self.registry.write_text(json.dumps({"schema": REGISTRY_SCHEMA, "environments": [asdict(self.spec)]}))
        self.registry.chmod(0o600)
        return {"environment_id": self.spec.environment_id, "kind": "local", "base_url": "http://127.0.0.1:8080",
            "inventory_hash": self.spec.digest, "isolation": "Actual owned internal namespace; not fixture or execution authority"}

    def close(self):
        self.registry.unlink(missing_ok=True)
        return self.resources.close()
