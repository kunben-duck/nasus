"""Physical native-response verification behind the application port."""
from ...domain.quality_loop.http_runner_observations import verify_http_runner_observations
from ...domain.quality_loop.runner_observations import RunnerObservationInvalid
from .http_observation_artifacts import verify_http_response_artifacts
from .request_wire import runner_request_hash


class HTTPRunnerObservationVerifier:
    def verify(self, command, result):
        if command.kind != "http" or result.runner_mode != "http_native" or result.execution_receipt is None:
            raise RunnerObservationInvalid("native HTTP observations are required")
        receipt = verify_http_runner_observations(result.execution_receipt, job_id=command.job_id,
            project_id=command.project_id, us_id=command.us_id, request_hash=runner_request_hash(command),
            steps=command.steps, status=result.status, protocol=command.http_protocol,
            fixture_input=getattr(command, "fixture_input", None), base_url=command.base_url, metadata=command.metadata)
        artifacts = [dict(artifact_type=item.artifact_type, name=item.name, media_type=item.media_type,
            content_base64=item.content_base64) for item in result.artifacts]
        verify_http_response_artifacts(receipt, artifacts, command.steps)
        return receipt
