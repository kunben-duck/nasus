"""Bounded lifecycle diagnostics without request, archive or exception contents."""
from contextlib import contextmanager
import logging
from time import perf_counter


logger = logging.getLogger(__name__)
PHASES = frozenset({
    "prepare_access", "prepare_original_command", "prepare_current_authority",
    "prepare_inputs", "prepare_binding", "prepare_final_authority",
    "grant_recipe_parent", "grant_environment_record", "grant_live_permission",
    "workflow_delivery", "workflow_start",
    "bind_canonical", "bind_live_permission", "bind_existing_intent", "bind_preparation",
    "bind_prior_effects", "bind_intent_persistence", "bind_preparation_receipt",
    "bind_intent_verification", "bind_event_persistence", "bind_current_authority",
    "worker_command", "worker_original_command", "worker_access", "worker_execute",
    "worker_archive_inputs", "worker_archive_history", "worker_commit",
    "execution_inputs", "execution_runtime", "execution_operation",
    "runtime_current", "runtime_binding", "runtime_command_fence", "runtime_acquire", "runtime_final_authority",
    "work_acquire", "work_require", "work_renew", "work_initial_authority", "work_original_scope",
    "work_transaction_lock", "work_locked_authority", "work_registered_parent", "work_final_scope",
    "work_final_authority", "work_live_lease",
})
FAILURE_TYPES = frozenset({
    "HttpFixtureInvalid", "HttpFixtureWorkBusy", "HttpFixtureWorkLost", "HttpFixtureOutcomeUnknown",
    "HttpFixtureExecutionStopped", "RunPlanChanged", "RunPlanIntegrityError",
    "SourceAccessDenied", "SourceAccessStale", "StaleSourceAccessScope", "PermissionError", "KeyError",
    "ValueError", "TypeError", "OperationalError", "DBAPIError", "ClientError",
    "RPCError", "TimeoutError", "CancelledError",
})


@contextmanager
def fixture_phase(phase):
    if type(phase) is not str or phase not in PHASES:
        raise ValueError("unknown fixture diagnostic phase")
    started = perf_counter()
    try:
        yield
    except BaseException as exc:
        kind = type(exc).__name__
        logger.warning("Fixture lifecycle phase failed; phase=%s failure_type=%s elapsed_ms=%d",
            phase, kind if kind in FAILURE_TYPES else "other", int((perf_counter() - started) * 1000))
        raise
    else:
        logger.info("Fixture lifecycle phase completed; phase=%s elapsed_ms=%d",
            phase, int((perf_counter() - started) * 1000))
