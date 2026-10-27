"""Internal observation linkage; no public dispatch or execution authorization."""
from dataclasses import asdict
from typing import Protocol

from .runner_port import AutomationRunnerCommand
from ...domain.quality_loop.http_bindings import HTTP_FIXTURE_RECEIPT_SCHEMA
from ...domain.quality_loop.run_plan_observations import (
    RunPlanObservationInvalid, compile_case_jobs, map_case_observation, map_unverified_case_attempt,
)
from ...domain.quality_loop.acceptance_specification import acceptance_digest


class HTTPRunnerObservationVerificationPort(Protocol):
    def verify(self, command, result): ...


class RunPlanObservationApplicationService:
    def __init__(self, verifier: HTTPRunnerObservationVerificationPort):
        self.verifier = verifier

    def commands(self, plan, *, run_id, timeout_ms):
        """Compile the full roster only; a caller still needs independent authority."""
        return tuple(self._command(job) for job in compile_case_jobs(plan, run_id=run_id, timeout_ms=timeout_ms))

    @staticmethod
    def _command(job):
        if job["receipt_protocol"] == HTTP_FIXTURE_RECEIPT_SCHEMA:
            raise RunPlanObservationInvalid("fixture-bound jobs require original setup handoff, not a template command")
        return AutomationRunnerCommand(job_id=job["job_id"], project_id=job["project_id"], us_id=job["us_id"],
            base_url=job["base_url"], steps=tuple(job["steps"]), timeout_ms=job["timeout_ms"], metadata=job["metadata"],
            kind="http", http_protocol=job["receipt_protocol"])

    def observe_http(self, plan, command, result):
        try:
            jobs = compile_case_jobs(plan, run_id=command.metadata["run_id"], timeout_ms=command.timeout_ms)
            job = next(item for item in jobs if item["job_id"] == command.job_id)
            self._require_original(job, command, result)
            return self._observe(plan, job, command, result)
        except (KeyError, TypeError, StopIteration):
            raise RunPlanObservationInvalid("RunPlan observation scope cannot be verified") from None

    def observe_http_batch(self, plan, entries, *, run_id, timeout_ms):
        """Validate the complete submitted cohort before inspecting any responses."""
        jobs, submitted = self._cohort(plan, entries, run_id=run_id, timeout_ms=timeout_ms, allow_unknown=False)
        return tuple(self._observe(plan, job, *submitted[job["job_id"]]) for job in jobs if job["job_id"] in submitted)

    def observe_http_attempt_batch(self, plan, entries, *, run_id, timeout_ms):
        jobs, submitted = self._cohort(plan, entries, run_id=run_id, timeout_ms=timeout_ms, allow_unknown=True)
        verified, unknown = [], []
        for job in jobs:
            if job["job_id"] not in submitted:
                continue
            command, result = submitted[job["job_id"]]
            if result.execution_receipt is None:
                unknown.append(map_unverified_case_attempt(plan, job, runner_status=result.status,
                    runner_result_hash=acceptance_digest(asdict(result))))
            else:
                verified.append(self._observe(plan, job, command, result))
        return tuple(verified), tuple(unknown)

    def _cohort(self, plan, entries, *, run_id, timeout_ms, allow_unknown):
        jobs = compile_case_jobs(plan, run_id=run_id, timeout_ms=timeout_ms)
        if type(entries) not in {tuple, list} or len(entries) > len(jobs):
            raise RunPlanObservationInvalid("HTTP observation cohort exceeds the original roster")
        by_id, submitted = {item["job_id"]: item for item in jobs}, {}
        try:
            for command, result in entries:
                if command.job_id in submitted:
                    raise RunPlanObservationInvalid("HTTP observation cohort contains duplicate jobs")
                job = by_id[command.job_id]
                if allow_unknown and result.execution_receipt is None:
                    if (command != self._command(job) or result.runner_job_id != command.job_id
                            or result.runner_mode != "http_native" or result.status not in {"error", "timed_out"}
                            or result.artifacts):
                        raise RunPlanObservationInvalid("missing native proof cannot be promoted or hide partial artifacts")
                else:
                    self._require_original(job, command, result)
                submitted[command.job_id] = (command, result)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise RunPlanObservationInvalid("HTTP observation cohort differs from the original plan attempt") from None
        return jobs, submitted

    def _require_original(self, job, command, result):
        if (command != self._command(job) or result.runner_job_id != command.job_id
                or result.runner_mode != "http_native" or result.execution_receipt is None):
            raise RunPlanObservationInvalid("RunPlan observations require the exact original native HTTP job")

    def _observe(self, plan, job, command, result):
        receipt = self.verifier.verify(command, result)
        return map_case_observation(plan, job, receipt)
