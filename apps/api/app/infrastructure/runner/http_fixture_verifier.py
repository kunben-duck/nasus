"""Recheck raw owned execution bytes, not only a deserialized success flag."""
from dataclasses import asdict

from ...domain.quality_loop.runner_observations import RunnerObservationInvalid
from .adapters import HttpAutomationRunner
from .http_observation_verifier import HTTPRunnerObservationVerifier
from .owned_target_environment import _object
from .request_wire import runner_request_body, runner_request_hash


class OwnedHttpFixtureObservationVerifier:
    def verify_input(self, command):
        from .http_fixture_input_verifier import verify_http_fixture_input
        return verify_http_fixture_input(command)

    def verify(self, command, execution, *, environment_id, inventory_hash):
        if (execution.environment_id != environment_id or execution.inventory_hash != inventory_hash
                or type(execution.request_body) is not bytes or execution.request_body != runner_request_body(command)
                or type(execution.result_body) is not bytes or len(execution.result_body) > 24 * 1024 * 1024):
            raise RunnerObservationInvalid("fixture execution differs from its original wire or owned environment")
        try:
            payload = _object(execution.result_body)
            original = HttpAutomationRunner._result_from_payload(command, payload, request_hash=runner_request_hash(command))
        except (UnicodeError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise RunnerObservationInvalid("fixture raw execution output cannot be verified") from None
        if asdict(original) != asdict(execution.result):
            raise RunnerObservationInvalid("fixture deserialized result differs from original output")
        return HTTPRunnerObservationVerifier().verify(command, original)
