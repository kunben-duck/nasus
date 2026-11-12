"""Execute an exact HTTP job in a registry-owned namespace, never the host network."""
import base64
import hashlib
import json
from pathlib import Path

from ...application.quality_loop.execution_work_guard import ExecutionWorkGuard, work_poll
from ...application.quality_loop.http_fixture_diagnostics import fixture_phase
from ...application.quality_loop.runner_port import OwnedTargetHttpExecution
from ...domain.quality_loop.native_environment import NativeEnvironmentInvalid, _require
from .adapters import HttpAutomationRunner
from .configured_target_environments import ConfiguredOwnedTargetEnvironments
from .native_maven_build import NativeBuildFailure, bounded_command
from .owned_target_environment import _object
from .request_wire import runner_request_body


CLI = Path(__file__).resolve().parents[4] / "runner/src/owned-http-cli.mjs"
MAX_RESULT_BYTES = 24 * 1024 * 1024


class ConfiguredOwnedTargetHttpRunner:
    """Private worker port. No HTTP request can select a Docker resource or CLI."""

    def __init__(self, *, node_executable, environments=None, command=bounded_command):
        path = Path(node_executable)
        _require(path.is_absolute() and path.is_file())
        self.node = str(path.resolve())
        self.environments = environments or ConfiguredOwnedTargetEnvironments()
        self.command = command

    def execute_owned_http(self, command, *, environment_id, artifact_hash, inventory_hash, require_work):
        return self._execute(command, environment_id=environment_id, artifact_hash=artifact_hash,
            inventory_hash=inventory_hash, require_work=require_work, stage_case=False)

    def stage_owned_case_http(self, command, *, environment_id, artifact_hash, inventory_hash, require_work):
        """Hand bytes to the private case archive; its transaction must verify the full inputs."""
        return self._execute(command, environment_id=environment_id, artifact_hash=artifact_hash,
            inventory_hash=inventory_hash, require_work=require_work, stage_case=True)

    def _execute(self, command, *, environment_id, artifact_hash, inventory_hash, require_work, stage_case):
        poll = work_poll(require_work)
        # The default transport verifies fully before spawn. Ordinary results
        # also require full proof before handoff; case staging is private.
        owned_boundaries = isinstance(require_work, ExecutionWorkGuard) and self.command is bounded_command
        (poll if owned_boundaries else require_work)()
        _require(command.kind == "http" and command.base_url == "http://127.0.0.1:8080"
            and type(command.timeout_ms) is int and 1000 <= command.timeout_ms <= 120000)
        wire = runner_request_body(command)
        _require(len(wire) <= 512 * 1024)
        with fixture_phase("runner_target_before"):
            before = self.environments.inspect(command.project_id, environment_id, artifact_hash, require_work=poll)
            _require(before.inventory_hash == inventory_hash)
        if getattr(command, "fixture_input", None) is not None:
            capsule = command.fixture_input["capture_set"]
            _require(capsule["environment_id"] == environment_id and capsule["target_artifact_hash"] == artifact_hash
                and capsule["inventory_hash"] == inventory_hash
                and capsule["operator_policy_digest"] == before.inventory["operator_policy_digest"])
        envelope = json.dumps({"schema": "nasus.owned-http-command.v1", "inventory": before.inventory,
            "wire_body_base64": base64.b64encode(wire).decode("ascii")},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        _require(len(envelope) <= 1024 * 1024 and CLI.is_file())
        callback_failed = False
        policy_digest = self.environments.policy_digest
        policy_polls = (isinstance(require_work, ExecutionWorkGuard)
            and type(self.environments) is ConfiguredOwnedTargetEnvironments
            and getattr(policy_digest, "__func__", None) is ConfiguredOwnedTargetEnvironments.policy_digest)

        def check(check_work):
            nonlocal callback_failed
            try:
                if check_work is not None:
                    check_work()
                _require(policy_digest(command.project_id, environment_id,
                    require_work=poll) == before.inventory["operator_policy_digest"])
            except BaseException:
                callback_failed = True
                raise

        def current():
            check(require_work)

        def active():
            # The default registry lookup already polls both before and after reading.
            check(None if policy_polls else poll)

        def verify_dispatch():
            with fixture_phase("runner_dispatch_proof"):
                current()

        guard = (ExecutionWorkGuard(verify_dispatch if owned_boundaries else current, active)
            if isinstance(require_work, ExecutionWorkGuard) else current)
        try:
            with fixture_phase("runner_subprocess"):
                code, body = self.command([self.node, str(CLI), "--execute-owned-target-http"],
                    timeout=command.timeout_ms / 1000 + 20, max_bytes=MAX_RESULT_BYTES,
                    input_body=envelope, require_work=guard,
                    **({"defer_result_verification": True} if owned_boundaries else {}))
                if not owned_boundaries:
                    current()
                _require(code == 0 and type(body) is bytes and 0 < len(body) <= MAX_RESULT_BYTES)
        except (NativeBuildFailure, OSError):
            if callback_failed:
                raise
            raise NativeEnvironmentInvalid("owned HTTP execution did not produce a verified result") from None
        raw = _object(body)
        try:
            result = HttpAutomationRunner._result_from_payload(command, raw,
                request_hash="sha256:" + hashlib.sha256(wire).hexdigest())
        except (ValueError, TypeError, KeyError, AttributeError):
            raise NativeEnvironmentInvalid("owned HTTP result does not match the original job") from None
        with fixture_phase("runner_target_after"):
            inspect = self.environments.inspect
            if policy_polls and getattr(inspect, "__func__", None) is ConfiguredOwnedTargetEnvironments.inspect:
                after = inspect(command.project_id, environment_id, artifact_hash, require_work=poll,
                    expected_policy_digest=before.inventory["operator_policy_digest"])
            else:
                after = inspect(command.project_id, environment_id, artifact_hash, require_work=active)
            _require(after.inventory_hash == inventory_hash and after.inventory == before.inventory)
            if stage_case and owned_boundaries:
                with fixture_phase("runner_case_private_staging"):
                    active()
            else:
                with fixture_phase("runner_result_proof"):
                    current()
        return OwnedTargetHttpExecution(result, wire, body, environment_id, inventory_hash)
