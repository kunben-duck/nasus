"""PG/MinIO/owned-runner assembly; explicit jobs require original command pins."""
import os

from ...application.quality_loop.http_fixture_execution import HttpFixtureWorkerRuntime
from ...application.quality_loop.http_fixture_diagnostics import fixture_phase
from ...application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
from ...application.quality_loop.http_fixture_journal_access import NativeSavedRunPlanHttpFixtureAccess
from ...application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid, fixture_bindings
from ..persistence.http_fixture_dispatch_consent_repository import PostgresHttpFixtureConsentFence
from ..persistence.http_fixture_command_repository import HttpFixtureCommandRepository
from ..persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
from ..persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from ..storage.http_fixture_artifacts import HttpFixtureExecutionArtifacts
from .http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from .owned_target_http import ConfiguredOwnedTargetHttpRunner


class OwnedHttpFixtureRuntimeFactory:
    def __init__(self, grants, plans, environment_records, environment_health, storage, *, runner=None, commands=None):
        self.grants, self.plans = grants, plans
        self.environment_records, self.environment_health = environment_records, environment_health
        self.storage = storage
        self.runner = runner
        self.commands = commands

    def _access(self, inputs):
        return NativeSavedRunPlanHttpFixtureAccess(self.plans, inputs.parent, inputs.manifest,
            self.environment_records, inputs.native_environment, environment_health=self.environment_health)

    def _current(self, inputs, require_current, *, live):
        def current():
            require_current()
            self.grants.authorization.require_current(inputs.access_scope)
            if live:
                if (inputs.access_scope.actor_id != inputs.consent.actor_id
                        or inputs.access_scope.fingerprint != inputs.consent.source_scope_digest):
                    raise HttpFixtureInvalid("fixture worker is not the original consenting actor and source scope")
                with fixture_phase("grant_live_permission"):
                    value = self.grants.repository.require_live(inputs.scope.project_id, inputs.consent.grant_id,
                        actor_id=inputs.consent.actor_id, scope=inputs.scope, operation=inputs.selection.operation,
                        source_scope_digest=inputs.consent.source_scope_digest)
                if value["grant_digest"] != inputs.selection.grant_digest:
                    raise HttpFixtureInvalid("fixture worker permission was replaced")
            self.grants.authorization.require_current(inputs.access_scope)
            require_current()
        return current

    def create(self, inputs, *, owner_id, require_current, command_authority=None):
        current = self._current(inputs, require_current, live=True)
        with fixture_phase("runtime_current"):
            current()
        access = self._access(inputs)
        artifacts = HttpFixtureExecutionArtifacts(self.storage)
        runner = self.runner
        if runner is None:
            runner = ConfiguredOwnedTargetHttpRunner(node_executable=os.environ.get("NASUS_HTTP_FIXTURE_NODE", ""))
        command_options = {}
        if command_authority is not None:
            command_authority = HttpFixtureCommandAuthority.model_validate(command_authority.model_dump(mode="json"))
            commands = self.commands if self.commands is not None else HttpFixtureCommandRepository()
            with fixture_phase("runtime_binding"):
                commands.bind(inputs, command_authority, require_current=current)
            original_current = current
            def command_current():
                original_current()
                commands.require(inputs, command_authority)
                original_current()
            current = command_current
            with fixture_phase("runtime_command_fence"):
                command_options["command_fence"] = commands.fence(inputs, command_authority)
        journal = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=inputs.consent.actor_id)
        repository = PostgresHttpFixtureWorkRepository(journal)
        with fixture_phase("runtime_acquire"):
            lease = repository.acquire(inputs.scope, inputs.selection.operation, owner_id, require_current=current)
        journal = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=inputs.consent.actor_id,
            work_fence=repository.fence(lease), consent_fence=PostgresHttpFixtureConsentFence(
                self.grants.repository, inputs.consent), **command_options)
        # The lifecycle checks this port immediately around every side effect;
        # the journal additionally fences the original consent in its transaction.
        class FencedRunner:
            def execute_owned_http(self, command, **options):
                original = options["require_work"]
                def require_work():
                    current()
                    original()
                    current()
                return runner.execute_owned_http(command, **{**options, "require_work": require_work})
        class FencedRepository:
            def require(self, value):
                current()
                repository.require(value)
                current()

            def renew(self, value, *, require_current):
                def renewed_current():
                    current()
                    require_current()
                repository.renew(value, require_current=renewed_current)
        with fixture_phase("runtime_final_authority"):
            current()
        return HttpFixtureWorkerRuntime(HttpFixtureLifecycleApplicationService(FencedRunner(), journal,
            OwnedHttpFixtureObservationVerifier()), FencedRepository(), lease)

    def history(self, inputs, *, require_current, original_setup=None, include_cleanup=False):
        if type(include_cleanup) is not bool:
            raise HttpFixtureInvalid("fixture history requires an explicit cleanup inventory selection")
        if original_setup is not None:
            original_setup = HttpFixtureCommandAuthority.model_validate(original_setup.model_dump(mode="json"))
        current = self._current(inputs, require_current, live=False)
        current()
        journal = PostgresHttpFixtureDispatchJournal(self._access(inputs), HttpFixtureExecutionArtifacts(self.storage),
            actor_id=inputs.access_scope.actor_id)
        phases = ("setup",) if inputs.selection.operation == "setup" and not include_cleanup else (
            "setup", *("cleanup:" + binding for binding in fixture_bindings(inputs.manifest)))
        result = []
        for phase in phases:
            current()
            options = {"read_only": True}
            if phase == "setup" and original_setup is not None:
                options["original_command"] = original_setup
            result.append((phase, journal.inspect(inputs.scope, phase, **options)))
        current()
        return tuple(result)
