"""Revalidate source setup wire and every physical response before resource use."""
from dataclasses import asdict

from ...application.quality_loop.runner_port import AutomationRunnerCommand
from ...domain.quality_loop.http_fixture_binding_input import fixture_input_parts
from ...domain.quality_loop.runner_observations import RunnerObservationInvalid


def verify_http_fixture_input(command):
    # The only recursive adapter call is the original v2 setup, never another import.
    from .adapters import HttpAutomationRunner
    capsule, source, output = fixture_input_parts(getattr(command, "fixture_input", None), project_id=command.project_id,
        case_id=command.us_id, base_url=command.base_url, metadata=command.metadata)
    original = AutomationRunnerCommand(job_id=source["job_id"], project_id=source["project_id"], us_id=source["us_id"],
        base_url=source["base_url"], timeout_ms=source["timeout_ms"], metadata=source["metadata"],
        kind="http", http_protocol=source["receipt_protocol"], steps=tuple(source["steps"]))
    result = HttpAutomationRunner._result_from_payload(original, output, request_hash=capsule.setup_request_hash)
    if result.status != "passed" or result.execution_receipt["bindings"] != [asdict(item) for item in capsule.captures]:
        raise RunnerObservationInvalid("fixture resources differ from the physically verified original setup")
    return capsule
