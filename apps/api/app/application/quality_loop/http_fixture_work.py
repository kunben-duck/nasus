"""Private worker ownership; a lease is never canonical execution consent."""
from dataclasses import asdict, dataclass
import re
from typing import Protocol

from .http_fixtures import HttpFixtureScope
from .generation_work_lease import run_with_generation_lease
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid


FIXTURE_WORK_LEASE_SECONDS = 90


class HttpFixtureWorkBusy(RuntimeError):
    pass


class HttpFixtureWorkLost(RuntimeError):
    pass


def fixture_work_identity(scope, operation):
    if not isinstance(scope, HttpFixtureScope) or type(operation) is not str or operation not in {"setup", "cleanup"}:
        raise HttpFixtureInvalid("fixture worker operation must be independently scoped")
    return "fixture_work_" + acceptance_digest([scope.project_id, scope.attempt_id, scope.case_id, operation])[7:]


def fixture_work_digest(scope, operation):
    fixture_work_identity(scope, operation)
    return acceptance_digest({"schema": "nasus.http-fixture-work.v1", "scope": asdict(scope), "operation": operation})


@dataclass(frozen=True)
class HttpFixtureWorkLease:
    scope: HttpFixtureScope
    operation: str
    owner_id: str
    epoch: int
    request_digest: str

    def __post_init__(self):
        if (not isinstance(self.scope, HttpFixtureScope) or type(self.owner_id) is not str
                or not 1 <= len(self.owner_id) <= 128 or not self.owner_id.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in self.owner_id)
                or type(self.epoch) is not int or not 1 <= self.epoch <= 2147483647
                or type(self.request_digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", self.request_digest) is None
                or self.request_digest != fixture_work_digest(self.scope, self.operation)):
            raise HttpFixtureInvalid("fixture worker lease identity or original scope differs")

    @property
    def work_id(self):
        return fixture_work_identity(self.scope, self.operation)

    def require_phase(self, scope, phase):
        if (scope != self.scope or type(phase) is not str
                or not ((self.operation == "setup" and phase == "setup")
                    or (self.operation == "cleanup" and phase.startswith("cleanup:") and len(phase) > 8))):
            raise HttpFixtureWorkLost("fixture worker does not own this original phase")


class HttpFixtureTransactionFencePort(Protocol):
    def ownership_pin(self, scope, phase) -> dict: ...
    def require(self, session, scope, phase, command) -> None: ...
    def claim(self, session, dispatch) -> None: ...
    def complete(self, session, dispatch) -> None: ...


async def run_with_http_fixture_work(repository, lease, operation, *, require_current, renew_seconds=15):
    """Reuse the bounded heartbeat lifecycle; transaction fences remain required."""
    class Runtime:
        def require_lease(self, value):
            require_current()
            repository.require(value)
            require_current()

        def renew_lease(self, value):
            repository.renew(value, require_current=require_current)

    return await run_with_generation_lease(Runtime(), lease, operation, renew_seconds=renew_seconds)
