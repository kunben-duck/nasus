"""Owned HTTP fixture phases behind an explicit dispatch journal and live fence."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, dataclass
import re
from typing import Callable, ContextManager, Protocol

from .runner_port import AutomationRunnerCommand, OwnedTargetHttpExecution, OwnedTargetHttpRunnerPort
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_bindings import HTTP_BINDING_RECEIPT_SCHEMA
from ...domain.quality_loop.http_fixtures import (
    HttpFixtureInvalid, fixture_bindings, resolve_fixture_cleanup, validate_http_fixture_manifest,
)


class HttpFixtureOutcomeUnknown(RuntimeError):
    pass


class HttpFixtureDispatchAlreadyClaimed(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpFixtureScope:
    project_id: str
    attempt_id: str
    case_id: str
    parent_digest: str
    data_manifest_hash: str
    environment_id: str
    artifact_hash: str
    inventory_hash: str
    timeout_ms: int

    def __post_init__(self):
        for value in (self.project_id, self.attempt_id, self.case_id, self.environment_id):
            if (type(value) is not str or not 1 <= len(value) <= 128 or not value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise HttpFixtureInvalid("invalid fixture execution identity")
            value.encode("utf-8", errors="strict")
        if any(type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None for value in
                (self.parent_digest, self.data_manifest_hash, self.artifact_hash, self.inventory_hash)):
            raise HttpFixtureInvalid("fixture execution requires exact original digests")
        if type(self.timeout_ms) is not int or not 1000 <= self.timeout_ms <= 120000:
            raise HttpFixtureInvalid("invalid fixture execution timeout")

    @property
    def digest(self):
        return acceptance_digest(asdict(self))


@dataclass(frozen=True)
class HttpFixturePhaseRecord:
    command: AutomationRunnerCommand
    execution: OwnedTargetHttpExecution | None


class HttpFixtureDispatchJournalPort(Protocol):
    def verified_read_session(self) -> ContextManager[object]:
        """Optional owned immutable-proof scope; never cache live authority."""
        ...
    def inspect(self, scope: HttpFixtureScope, phase: str) -> HttpFixturePhaseRecord | None: ...
    def claim(self, scope, phase, command, *, require_current: Callable[[], None]) -> None:
        """Unique project/attempt/case/phase, not scope digest; never rebind a claim."""
        ...
    def complete(self, scope, phase, command, execution, *, require_current: Callable[[], None]) -> None:
        """Preserve original bytes; failure leaves a non-retryable reserved phase."""
        ...


class HttpFixtureObservationVerificationPort(Protocol):
    def verify(self, command, execution, *, environment_id, inventory_hash) -> dict: ...


@dataclass(frozen=True)
class HttpFixturePhaseOutcome:
    phase: str
    command: AutomationRunnerCommand
    execution: OwnedTargetHttpExecution
    receipt: dict


@dataclass(frozen=True)
class HttpFixtureCleanupOutcome:
    phases: tuple[HttpFixturePhaseOutcome, ...]
    unresolved_bindings: tuple[str, ...]
    unknown_phases: tuple[str, ...]
    cleanup_verified: bool
    baseline_restored: bool = False
    business_coverage_verified: bool = False
    execution_authorized: bool = False


class HttpFixtureLifecycleApplicationService:
    def __init__(self, runner: OwnedTargetHttpRunnerPort, journal: HttpFixtureDispatchJournalPort,
                 verifier: HttpFixtureObservationVerificationPort):
        self.runner, self.journal, self.verifier = runner, journal, verifier

    @staticmethod
    def _manifest(scope, value):
        manifest = validate_http_fixture_manifest(value)
        if manifest["case_id"] != scope.case_id or acceptance_digest(manifest) != scope.data_manifest_hash:
            raise HttpFixtureInvalid("fixture manifest differs from the fixed execution scope")
        return manifest

    @staticmethod
    def _command(scope, phase, steps):
        return AutomationRunnerCommand(job_id="http-fixture-" + acceptance_digest([scope.digest, phase])[7:],
            project_id=scope.project_id, us_id=scope.case_id, base_url="http://127.0.0.1:8080",
            steps=steps, timeout_ms=scope.timeout_ms, kind="http", http_protocol=HTTP_BINDING_RECEIPT_SCHEMA,
            metadata={"fixture_scope": asdict(scope), "fixture_phase": phase, "business_coverage_verified": False})

    def _verify(self, scope, phase, command, execution, require_work):
        require_work()
        receipt = self.verifier.verify(command, execution, environment_id=scope.environment_id,
            inventory_hash=scope.inventory_hash)
        require_work()
        return HttpFixturePhaseOutcome(phase, command, execution, receipt)

    def _phase(self, scope, phase, steps, *, require_work, dispatch=True):
        reader = getattr(self.journal, "verified_read_session", None)
        with reader() if callable(reader) else nullcontext():
            return self._execute_phase(scope, phase, steps, require_work=require_work, dispatch=dispatch)

    def _execute_phase(self, scope, phase, steps, *, require_work, dispatch=True):
        command = self._command(scope, phase, steps)
        require_work()
        prior = self.journal.inspect(scope, phase)
        if prior is not None:
            if prior.command != command:
                raise HttpFixtureInvalid("fixture journal command was rebound")
            if prior.execution is None:
                raise HttpFixtureOutcomeUnknown("fixture phase was dispatched without verified original output; never retry")
            return self._verify(scope, phase, command, prior.execution, require_work)
        if not dispatch:
            raise HttpFixtureOutcomeUnknown("fixture setup has no original dispatch evidence")
        try:
            self.journal.claim(scope, phase, command, require_current=require_work)
        except HttpFixtureDispatchAlreadyClaimed:
            raise HttpFixtureOutcomeUnknown("fixture dispatch was claimed concurrently; read original evidence") from None
        require_work()
        try:
            execution = self.runner.execute_owned_http(command, environment_id=scope.environment_id,
                artifact_hash=scope.artifact_hash, inventory_hash=scope.inventory_hash, require_work=require_work)
        except Exception as exc:
            require_work()
            raise HttpFixtureOutcomeUnknown("fixture transport ended without verified original output; never retry") from exc
        outcome = self._verify(scope, phase, command, execution, require_work)
        self.journal.complete(scope, phase, command, execution, require_current=require_work)
        require_work()
        return outcome

    def prepare(self, scope: HttpFixtureScope, value, *, require_work: Callable[[], None]):
        manifest = self._manifest(scope, value)
        return self._phase(scope, "setup", tuple(manifest["setup_steps"]), require_work=require_work)

    def cleanup(self, scope: HttpFixtureScope, value, *, require_work: Callable[[], None]):
        manifest = self._manifest(scope, value)
        prepared = self._phase(scope, "setup", tuple(manifest["setup_steps"]), require_work=require_work, dispatch=False)
        resources = {item["binding_id"]: item["value"] for item in prepared.receipt["bindings"]}
        phases, unresolved, unknown = [], [], []
        for binding in fixture_bindings(manifest):
            if binding not in resources:
                unresolved.append(binding)
                continue
            phase = "cleanup:" + binding
            try:
                phases.append(self._phase(scope, phase, resolve_fixture_cleanup(manifest, binding, resources[binding]),
                    require_work=require_work))
            except HttpFixtureOutcomeUnknown:
                unknown.append(phase)
        return HttpFixtureCleanupOutcome(tuple(phases), tuple(unresolved), tuple(unknown),
            not unresolved and not unknown and all(item.execution.result.status == "passed" for item in phases))
