"""Anti-corruption boundary for versioned browser observations, not a dispatch API."""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Protocol

from ...domain.quality_loop.browser_run_plan import compile_browser_case_jobs, map_browser_case_observation
from ...domain.quality_loop.run_plan_observations import RunPlanObservationInvalid


@dataclass(frozen=True)
class ReviewedBrowserCommand:
    # Keep exact wire bytes separate from legacy browser/HTTP command serialization.
    request_body: bytes = field(repr=False)

    def wire(self):
        return json.loads(self.request_body.decode("utf-8"))

    @property
    def request_hash(self):
        return "sha256:" + hashlib.sha256(self.request_body).hexdigest()


class BrowserNativeObservationPort(Protocol):
    def verify(self, command: ReviewedBrowserCommand, result):
        """Read original private native evidence and verify it matches this command/result."""
        ...


class BrowserRunPlanObservationApplicationService:
    def __init__(self, verifier: BrowserNativeObservationPort):
        self.verifier = verifier

    def commands(self, plan, *, run_id, timeout_ms, environment_digest, browser_digest):
        jobs = compile_browser_case_jobs(plan, run_id=run_id, timeout_ms=timeout_ms,
            environment_digest=environment_digest, browser_digest=browser_digest)
        return tuple(ReviewedBrowserCommand(json.dumps(job, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")) for job in jobs)

    def observe(self, plan, command, result, *, run_id, environment_digest, browser_digest):
        if type(command) is not ReviewedBrowserCommand:
            raise RunPlanObservationInvalid("versioned browser command required")
        job = command.wire()
        originals = self.commands(plan, run_id=run_id, timeout_ms=job["timeout_ms"],
            environment_digest=environment_digest, browser_digest=browser_digest)
        if command not in originals or self.verifier is None:
            raise RunPlanObservationInvalid("original browser inputs and private native verifier required")
        receipt = self.verifier.verify(command, result)
        return map_browser_case_observation(plan, job, deepcopy(receipt), run_id=run_id,
            request_hash=command.request_hash)
