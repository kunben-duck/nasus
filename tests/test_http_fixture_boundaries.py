import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_business_fixture_handoff_preserves_original_wire_and_explicit_legacy_protocols():
    root = ROOT / "apps/api/app"
    for relative in ("application/quality_loop/run_plan_case_fixtures.py", "application/quality_loop/run_plan_case_inputs.py",
            "application/quality_loop/run_plan_case_execution.py", "domain/quality_loop/run_plan_case_execution.py"):
        tree = ast.parse((root / relative).read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(any(part in name.split(".") for part in
            ("infrastructure", "sqlalchemy", "fastapi", "boto3", "temporalio", "httpx")) for name in modules)
    source = (root / "application/quality_loop/run_plan_case_fixtures.py").read_text()
    assert "OriginalCaseFixtureWire" in source and "prepared.execution.request_body" in source and "prepared.execution.result_body" in source
    assert "include_cleanup=True" in source and "self.verifier.verify(command, prepared.execution" in source
    producer = (root / "application/quality_loop/run_plan_case_inputs.py").read_text()
    assert "self.fixtures.read_native" in producer and "build_fixture_input(capture, wire.request_body, wire.result_body)" in producer
    assert "current != prepared" in producer and "historical_scope" in producer
    worker = (root / "application/quality_loop/run_plan_case_execution.py").read_text()
    assert worker.index("self._verified_commands(plan, scope, fixture_inputs)", worker.index("async def execute")) < worker.index("journal.acquire", worker.index("async def execute"))
    assert "self.verifier.verify_input(command)" in worker and "value[\"fixture_input\"] != command.fixture_input" in worker
    assert "FixtureBoundHttpCommand" in worker and "No fake Runner result or automatic retry" in worker
    scope = (root / "domain/quality_loop/run_plan_case_execution.py").read_text()
    assert "class FixtureBoundRunPlanCaseScope(RunPlanCaseScope)" in scope and "restore_case_scope" in scope
    assert "fixture_input_pins: tuple[dict, ...]" in scope and "case_job_digest(job, scope)" in scope
    assert "source_request_body_base64" not in scope and "source_result_body_base64" not in scope


def test_project_fixture_discovery_is_source_filtered_before_sql_count_and_has_no_effect_path():
    root = ROOT / "apps/api/app"
    repository = (root / "infrastructure/persistence/http_fixture_history_repository.py").read_text()
    for token in ("union_all", "hidden.binding_id.not_in(binding_ids)", "visible_fixture_commands", "invalid_total", "limit + 1"):
        assert token in repository
    assert not any(token in repository for token in ("session.add", "with_for_update", "require_live", "LIMIT 500"))
    application = (root / "application/quality_loop/http_fixture_history.py").read_text()
    for token in ("binding_ids=tuple(sorted(access.binding_ids))", "self.grants.authorization.require_current(access)",
            "self.grants.history_request", "self.grants.execution_inputs(selected, live=False)", "lookahead", "verify_receipt"):
        assert token in application
    assert not any(token in application for token in ("self.workflow", "self.runner", "require_live", "self.grants.repository", "sessionStorage"))
    routes = (root / "interface/http/routers/run_plans.py").read_text()
    assert '"/v1/projects/{project_id}/quality/http-fixture-operations"' in routes
    assert '"/v1/projects/{project_id}/quality/http-fixture-operations/{invocation_id}"' in routes
    for path in ("domain/quality_loop/http_fixture_history.py", "application/quality_loop/http_fixture_history.py"):
        tree = ast.parse((root / path).read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any("infrastructure" in name or "sqlalchemy" in name or "temporalio" in name for name in imports)
    portal = ROOT / "apps/portal/src"
    assert "<HttpFixtureHistoryPanel" in (portal / "routes/project/sections/KnowledgeSection.tsx").read_text()
    api = (portal / "domains/quality-loop/httpFixtureHistoryApi.ts").read_text()
    assert "cache: 'no-store'" in api and "signal.throwIfAborted()" in api
    assert not any(token in api for token in ("platformApi", "invokeTool", "confirmToolInvocation", "method:", "sessionStorage"))
    hook = (portal / "domains/quality-loop/useHttpFixtureHistory.ts").read_text()
    assert "useState(false)" in hook and "retry: false" in hook and "gcTime: 0" in hook
    assert "verifyFixtureHistoryPages(list.data.pages, projectId)" in hook and "rows: failed || reading ? undefined" in hook


def test_independent_original_journal_uses_only_verified_read_ports_and_non_authoritative_phases():
    root = ROOT / "apps/api/app"
    application = (root / "application/quality_loop/http_fixture_observations.py").read_text()
    for token in ("self.history.read", "self.jobs.read", "self.grants.execution_inputs(selection, live=False)",
            "fixture_bindings(inputs.manifest)", "self.grants.authorization.require_current(access)", "verify_receipt"):
        assert token in application
    for path in ("domain/quality_loop/http_fixture_observation.py", "application/quality_loop/http_fixture_observations.py"):
        source = (root / path).read_text()
        imports = [node.module or "" for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
        assert not any("infrastructure" in name or "sqlalchemy" in name or "temporalio" in name for name in imports)
        assert not any(token in source for token in ("self.workflow", "self.runner", "require_live", "self.grants.repository", "sessionStorage"))
    routes = (root / "interface/http/routers/run_plans.py").read_text()
    assert '"/v1/projects/{project_id}/quality/http-fixture-operations/{invocation_id}/observation"' in routes
    assert "response_model=HttpFixtureOriginalObservation" in routes and "fixture_observation_changed" in routes
    portal = ROOT / "apps/portal/src"
    api = (portal / "domains/quality-loop/httpFixtureObservationApi.ts").read_text()
    assert "cache: 'no-store'" in api and "signal.throwIfAborted()" in api and "/observation`" in api
    assert not any(token in api for token in ("platformApi", "invokeTool", "confirmToolInvocation", "method:", "sessionStorage"))
    hook = (portal / "domains/quality-loop/useHttpFixtureHistory.ts").read_text()
    assert "inspect && !!metadata" in hook and "journalFailed" in hook and "setInspect(false)" in hook
    assert "metadata?.status, scope" in hook and "query.data" not in hook
    panel = (portal / "routes/project/sections/knowledge/scope/HttpFixtureObservationDetails.tsx").read_text()
    assert "outcome_unknown" in panel and "cancellation does not prove rollback" in panel
    assert not any(token in panel for token in ("invokeTool", "confirmToolInvocation", "onClick", "dangerouslySetInnerHTML"))


def test_fixture_portal_uses_original_native_parents_and_independent_canonical_commands():
    root = ROOT / "apps/portal/src"
    panel = (root / "routes/project/sections/knowledge/scope/HttpFixtureRecipePanel.tsx").read_text()
    assert "<HttpFixtureOperationPanel" in panel and "recipe={state.result}" in panel
    api = (root / "domains/quality-loop/httpFixtureOperationApi.ts").read_text()
    assert "platformApi.invokeTool" in api and "platformApi.confirmToolInvocation" in api
    assert "requireFixtureOperationInput(stage, input)" in api and "original.status === 'waiting_confirmation'" in api
    recover = api.split("  async recover(", 1)[1].split("  async readGrant(", 1)[0]
    assert "confirmToolInvocation" not in recover and "invokeTool" not in recover and "cache: 'no-store'" in recover
    parents = (root / "domains/quality-loop/httpFixtureEnvironmentApi.ts").read_text()
    assert "runPlanBuildApi.recover" in parents and "runPlanBuildApi.read" in parents and "environmentRecordApi.read" in parents
    assert "invokeTool" not in parents and "confirmToolInvocation" not in parents
    validation = (root / "domains/quality-loop/httpFixtureOperationValidation.ts").read_text()
    for token in ("nasus.http-fixture-grant.v2", "nasus.http-fixture-job.v2", "target_observation_verified === false",
                  "v.intent_digest === null", "900000", "fixtureFalseAuthorities", "canonicalDigest({ tool_id:"):
        assert token in validation
    hook = (root / "domains/quality-loop/useHttpFixtureOperation.ts").read_text()
    assert "retry: false" in hook and "consent === stage + confirmationKey" in hook
    assert "executionResult.job.phases.every((item) => item.state === 'observed')" in hook
    assert "operation.operation === 'setup' ? operation.attemptId : crypto.randomUUID()" in hook
    mutation = hook.split("mutationFn: async (", 1)[1].split("}, onSettled:", 1)[0]
    assert "input, fields: selected" in mutation and ": OperationWrite" in mutation
    assert ".data" not in mutation and "prepared" not in mutation
    assert mutation.index("await canonicalDigest(input)") < mutation.index("storage.read(actorId")
    assert "input, fields: selected })" in hook


def test_unbound_cancellation_is_append_only_and_has_no_intent_backfill_or_execution_authority():
    migration = (ROOT / "apps/api/migrations/versions/0117_fixture_preparation_cancel.py").read_text()
    assert 'down_revision = "0116_fixture_preparations"' in migration
    assert "nasus_reject_image_revision_mutation()" in migration and "Cannot discard populated" in migration
    assert "INSERT" not in migration and "quality_http_fixture_commands" not in migration
    repository = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_job_repository.py").read_text()
    observe = repository.split("    def preparation_state(", 1)[1].split("    def finish(", 1)[0]
    assert '"target_observation_verified": False' in observe and '"intent_digest": None' in observe
    assert not any(value in observe for value in ("session.add", "acquire(", "preflight(", "_lifecycle_event"))
    application = (ROOT / "apps/api/app/application/quality_loop/http_fixture_jobs.py").read_text()
    read = application.split("    def _read(", 1)[1].split("    def read(", 1)[0]
    assert read.index("self.grants.execution_inputs(selection, live=False)") < read.index("self.repository.preparation_state")
    assert read.index("return preparation") < read.index("self.execution.read")


def test_fixture_domain_and_application_do_not_import_runtime_or_persistence_adapters():
    for relative in ("domain/quality_loop/http_fixtures.py", "application/quality_loop/http_fixtures.py",
            "application/quality_loop/http_fixture_journal_access.py", "application/quality_loop/http_fixture_work.py",
            "domain/quality_loop/http_fixture_recipe.py", "application/quality_loop/http_fixture_recipes.py",
            "domain/quality_loop/http_fixture_grant.py", "application/quality_loop/http_fixture_grants.py",
            "application/quality_loop/http_fixture_dispatch_consent.py", "domain/quality_loop/http_fixture_target.py",
            "application/quality_loop/http_fixture_execution.py", "application/quality_loop/worker_threads.py",
            "domain/quality_loop/http_fixture_command.py", "application/quality_loop/http_fixture_commands.py",
            "domain/quality_loop/http_fixture_preparation.py",
            "application/quality_loop/http_fixture_jobs.py"):
        tree = ast.parse((ROOT / "apps/api/app" / relative).read_text())
        imports = [item.module or "" for item in ast.walk(tree) if isinstance(item, ast.ImportFrom)]
        imports += [alias.name for item in ast.walk(tree) if isinstance(item, ast.Import) for alias in item.names]
        assert not any(set(module.split(".")) & {"infrastructure", "sqlalchemy", "fastapi", "httpx", "subprocess", "temporalio", "langgraph"}
            for module in imports)


def test_fixture_phase_is_not_a_public_execution_or_coverage_grant():
    source = (ROOT / "apps/api/app/application/quality_loop/http_fixtures.py").read_text()
    assert "self.journal.claim" in source and "self.journal.complete" in source and "require_work" in source
    assert "baseline_restored: bool = False" in source and "business_coverage_verified: bool = False" in source
    assert "execution_authorized: bool = False" in source
    probe = (ROOT / "scripts/exweb_http_fixture_probe.py").read_text()
    assert '"durable_postgresql_journal_verified": False' in probe and "readonly" in probe
    assert '"canonical_runplan_verified": False' in probe


def test_readonly_fixture_verifier_cannot_launch_target_or_overwrite_original_evidence():
    source = (ROOT / "scripts/verify-exweb-http-fixtures.py").read_text()
    tree = ast.parse(source)
    modules = [item.module or "" for item in ast.walk(tree) if isinstance(item, ast.ImportFrom)]
    assert not any("httpx" in module or "subprocess" in module for module in modules)
    assert "replay_exweb_http_fixtures" in source and "args.output.exists()" in source


def test_backend_fixture_journal_preserves_attempt_identity_and_requires_pg_s3():
    source = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_journal_repository.py").read_text()
    assert 'engine.dialect.name != "postgresql"' in source
    assert "scope.project_id, scope.attempt_id, scope.case_id, phase" in source
    assert "require_current()" in source and "self._event(session" in source
    models = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_journal_models.py").read_text()
    assert 'UniqueConstraint("project_id", "attempt_id", "case_id", "phase")' in models
    artifacts = (ROOT / "apps/api/app/infrastructure/storage/http_fixture_artifacts.py").read_text()
    assert "if not storage.config.s3_enabled" in artifacts and '"local-object://' not in artifacts


def test_private_fixture_journal_is_not_wired_as_public_execution_consent():
    paths = [ROOT / "apps/api/app/composition.py", ROOT / "apps/api/app/store.py",
        *list((ROOT / "apps/api/app/bootstrap").rglob("*.py"))]
    assert len(paths) > 2 and all(path.exists() for path in paths)
    assert not any("PostgresHttpFixtureDispatchJournal" in path.read_text() for path in paths if path.exists())
    migration = (ROOT / "apps/api/migrations/versions/0108_http_fixture_journals.py").read_text()
    assert "nasus_reject_image_revision_mutation()" in migration and "Cannot discard populated original fixture history." in migration


def test_work_fence_uses_pg_time_and_original_epoch_in_the_journal_transaction():
    source = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_work_repository.py").read_text()
    assert "func.clock_timestamp()" in source and "row.epoch + 1" in source and "with_for_update()" in source
    assert "datetime.now" not in source and "cannot adopt another dispatch" in source
    journal = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_journal_repository.py").read_text()
    assert "self.work_fence.require(session" in journal and "self.work_fence.claim(session" in journal
    assert "self.work_fence.complete(session" in journal and "work_ownership" in journal
    migration = (ROOT / "apps/api/migrations/versions/0109_http_fixture_work.py").read_text()
    assert "OLD.expires_at > clock_timestamp()" in migration and "NEW.epoch <> OLD.epoch + 1" in migration
    assert "Cannot discard populated original fixture work history." in migration


def test_recipe_registration_is_canonical_but_never_wires_target_dispatch():
    source = (ROOT / "apps/api/app/application/quality_loop/http_fixture_recipes.py").read_text()
    assert "bind_run_plan_fixture" in source and "verify_before_commit" in source and "authorize_receipts" in source
    assert not any(value in source for value in ("execute_owned_http", "self.runner", "HttpFixtureLifecycleApplicationService"))
    migration = (ROOT / "apps/api/migrations/versions/0110_http_fixture_recipes.py").read_text()
    assert "nasus_reject_image_revision_mutation()" in migration and "Cannot discard populated original fixture recipe history." in migration
    storage = (ROOT / "apps/api/app/infrastructure/storage/http_fixture_recipe_artifacts.py").read_text()
    assert "s3_enabled" in storage and 'ref.startswith("s3://")' in storage
    for relative, token in (("store.py", "self.http_fixture_recipes"), ("bootstrap/container.py", "http_fixture_recipes=runtime.http_fixture_recipes"),
            ("application/platform/tool_handlers/registry.py", "HttpFixtureRecipeToolHandler"),
            ("application/platform/tool_receipt_access.py", "RECIPE_TOOLS"),
            ("infrastructure/persistence/event_outbox_repository.py", "HttpFixtureRecipeRepository.verify_event"),
            ("interface/http/routers/run_plans.py", '"/v1/projects/{project_id}/quality/http-fixture-recipes/{record_id}"')):
        assert token in (ROOT / "apps/api/app" / relative).read_text()


def test_independent_consent_has_pg_lifetime_and_cannot_become_a_dispatch_gate_alone():
    application = (ROOT / "apps/api/app/application/quality_loop/http_fixture_grants.py").read_text()
    assert "require_operation" in application and "self.repository.require_live" in application
    assert not any(token in application for token in ("execute_owned_http", "self.runner", "HttpFixtureLifecycleApplicationService"))
    repository = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_grant_repository.py").read_text()
    assert "func.clock_timestamp()" in repository and "datetime.now" not in repository
    assert 'command.status != "completed"' in repository and "row.operation != operation" in repository
    assert "scope.digest" in repository and "source_scope_digest" in repository and "require_access()" in repository
    migration = (ROOT / "apps/api/migrations/versions/0111_http_fixture_grants.py").read_text()
    assert "nasus_reject_image_revision_mutation()" in migration and "Cannot discard populated independent fixture operation consent." in migration
    assert "INSERT" not in migration
    for relative, token in (("store.py", "self.http_fixture_grants"), ("bootstrap/container.py", "http_fixture_grants=runtime.http_fixture_grants"),
            ("application/platform/tool_handlers/registry.py", "HttpFixtureGrantToolHandler"),
            ("application/platform/tool_receipt_access.py", "GRANT_TOOLS"),
            ("infrastructure/persistence/event_outbox_repository.py", "HttpFixtureGrantRepository.verify_event"),
            ("interface/http/routers/run_plans.py", '"/v1/projects/{project_id}/quality/http-fixture-grants/{record_id}"')):
        assert token in (ROOT / "apps/api/app" / relative).read_text()


def test_dispatch_consent_requires_original_permission_and_worker_in_the_same_transaction():
    journal = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_journal_repository.py").read_text()
    assert "consent_fence is not None and work_fence is None" in journal
    assert "self.consent_fence.require(session" in journal and "self.consent_fence.claim(session" in journal
    assert "self.consent_fence.complete(session" in journal and "verify_dispatch_consent(session" in journal
    repository = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_dispatch_consent_repository.py").read_text()
    assert "require_live_in_session(session" in repository and "verify_dispatch_ownership(session" in repository
    assert 'command.status != "completed"' in repository and "never downgrade" in repository
    assert "execute_owned_http" not in repository and "session_scope" not in repository
    migration = (ROOT / "apps/api/migrations/versions/0112_http_fixture_dispatch_consents.py").read_text()
    assert "nasus_reject_image_revision_mutation()" in migration and "Cannot discard populated original fixture dispatch consent." in migration
    assert "INSERT" not in migration


def test_native_fixture_consent_separates_policy_from_original_instance_without_legacy_backfill():
    application = (ROOT / "apps/api/app/application/quality_loop/http_fixture_grants.py").read_text()
    assert "native_fixture_environment" in application and "self.environment_records.read" in application
    assert "preserve_original_v1" in application and "no legacy fallback" in application
    access = (ROOT / "apps/api/app/application/quality_loop/http_fixture_journal_access.py").read_text()
    assert "NativeSavedRunPlanHttpFixtureAccess" in access and "self.native_environment" in access
    assert "latest" in access and "execute_owned_http" not in access
    migration = (ROOT / "apps/api/migrations/versions/0113_fixture_native_grants.py").read_text()
    assert "nasus_reject_image_revision_mutation()" in migration
    assert "Cannot discard populated original native fixture consent." in migration and "INSERT" not in migration
    repository = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_grant_repository.py").read_text()
    assert "_verify_native_binding" in repository and "_native_parent" in repository
    assert "environment_record_artifact_hash" in repository and 'command.status != "completed"' in repository


def test_native_fixture_preflight_is_before_journal_writes_and_not_in_historical_reads():
    journal = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_journal_repository.py").read_text()
    claim = journal.split("    def claim(", 1)[1].split("    def complete(", 1)[0]
    assert claim.index("preflight(scope, phase, command") < claim.index("with session_scope()")
    inspect = journal.split("    def inspect(", 1)[1].split("    def claim(", 1)[0]
    assert "preflight" not in inspect
    access = (ROOT / "apps/api/app/application/quality_loop/http_fixture_journal_access.py").read_text()
    assert "def require_dispatch(" in access and "explicit live target health port" in access
    assert "NativeEnvironmentHealthObservation" in access and "observed.inventory_hash != scope.inventory_hash" in access
    assert "not observed.dependency_health_verified or not observed.target_health_verified" in access
    assert "execute_owned_http" not in access and "session_scope" not in access
    health = (ROOT / "apps/api/app/application/quality_loop/run_plan_environment_health.py").read_text()
    assert "def current():" in health and "require_work()" in health


def test_private_worker_is_composed_through_application_and_owned_adapters():
    source = (ROOT / "apps/api/app/application/quality_loop/http_fixture_execution.py").read_text()
    assert "self.grants.execution_inputs(selection, live=True)" in source
    assert "self.grants.execution_inputs(selection, live=False)" in source
    assert "run_worker_thread" in source and "on_cancel=stopped.set" in source
    factory = (ROOT / "apps/api/app/infrastructure/runner/http_fixture_runtime.py").read_text()
    for fragment in ("NativeSavedRunPlanHttpFixtureAccess", "PostgresHttpFixtureConsentFence",
            "repository.fence(lease)", 'os.environ.get("NASUS_HTTP_FIXTURE_NODE", "")'):
        assert fragment in factory
    history = factory.split("    def history(", 1)[1]
    assert "journal.inspect" in history
    assert not any(token in history for token in ("ConfiguredOwnedTargetHttpRunner", "repository.acquire", "live=True"))
    assert "http_fixture_execution=runtime.http_fixture_execution" in (ROOT / "apps/api/app/bootstrap/container.py").read_text()
    assert "OwnedHttpFixtureRuntimeFactory" in (ROOT / "apps/api/app/store.py").read_text()


def test_original_command_fence_is_additive_and_checks_the_journal_transaction():
    source = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_command_repository.py").read_text()
    assert "with_for_update()" in source and "func.clock_timestamp()" in source
    assert "canonical_fixture" not in source and "datetime.now" not in source
    assert "another canonical command" in source and "never downgrade" in source
    journal = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_journal_repository.py").read_text()
    for name in ("require", "claim", "complete", "require_existing"):
        assert f"self.command_fence.{name}(session" in journal
    assert "command_fence is not None and (work_fence is None or consent_fence is None)" in journal
    assert "verify_dispatch_command(session" in journal
    migration = (ROOT / "apps/api/migrations/versions/0114_fixture_command_provenance.py").read_text()
    assert "nasus_reject_image_revision_mutation()" in migration
    assert "Cannot discard populated original fixture command provenance." in migration and "INSERT" not in migration


def test_public_fixture_job_requires_canonical_gates_and_preserves_original_effects():
    from apps.api.app.application.platform.tool_catalog import core_tool_definitions
    from apps.api.app.domain.platform.rbac import ToolRBAC
    from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL, FIXTURE_JOB_TOOLS

    catalog = {item.tool_id: item for item in core_tool_definitions()}
    assert FIXTURE_JOB_TOOLS <= set(catalog)
    for tool in FIXTURE_JOB_TOOLS:
        assert ToolRBAC().required_roles(catalog[tool]) == ("project_admin", "platform_admin")
    assert catalog[FIXTURE_COMMAND_TOOL].confirmation_mode == catalog[FIXTURE_CANCEL_TOOL].confirmation_mode == "user_confirm"
    application = (ROOT / "apps/api/app/application/quality_loop/http_fixture_jobs.py").read_text()
    assert "command_authority=authority" in application and "self.repository.bind" in application
    assert application.index("self.repository.cancel(target") < application.index("await self.workflow.cancel(target.invocation_id)")
    repository = (ROOT / "apps/api/app/infrastructure/persistence/http_fixture_job_repository.py").read_text()
    assert "with_for_update()" in repository and "func.clock_timestamp()" in repository
    assert "not_dispatched" in repository and "outcome_unknown" in repository
    assert "unknown or unexecuted fixture phases cannot become completion" in repository
    assert "HttpFixtureWorkBusy" in repository and "verify_dispatch_command(session" in repository
    workflow = (ROOT / "apps/api/app/infrastructure/workflow/nasus_http_fixture_workflow.py").read_text()
    assert "WAIT_CANCELLATION_COMPLETED" in workflow
    runtime = (ROOT / "apps/api/app/infrastructure/workflow/http_fixture_runtime.py").read_text()
    assert "REJECT_DUPLICATE" in runtime and "pending_cancellations" in runtime
    for relative, token in (("store.py", "HttpFixtureJobReceiptAccess(self.http_fixture_jobs)"),
            ("bootstrap/container.py", "http_fixture_jobs=runtime.http_fixture_jobs"),
            ("application/platform/tool_handlers/registry.py", "HttpFixtureJobToolHandler"),
            ("application/platform/tool_receipt_access.py", "FIXTURE_JOB_TOOLS"),
            ("infrastructure/workflow/agent_goal_workflow_worker.py", "reconcile_http_fixtures(fixture_runtime)"),
            ("interface/http/routers/run_plans.py", '"/v1/projects/{project_id}/quality/http-fixture-executions/{invocation_id}"')):
        assert token in (ROOT / "apps/api/app" / relative).read_text()
    migration = (ROOT / "apps/api/migrations/versions/0115_fixture_job_cancellations.py").read_text()
    assert "nasus_reject_image_revision_mutation()" in migration and "INSERT" not in migration
    assert "Cannot discard populated original fixture cancellation history." in migration
