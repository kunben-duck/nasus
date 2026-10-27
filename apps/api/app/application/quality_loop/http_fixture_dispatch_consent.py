"""Original operation permission pins, separate from worker and target authority."""
from dataclasses import dataclass
import re
from typing import Protocol

from .http_fixtures import HttpFixtureScope
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid


@dataclass(frozen=True)
class HttpFixtureDispatchConsent:
    grant_id: str
    grant_digest: str
    actor_id: str
    source_scope_digest: str
    scope: HttpFixtureScope
    operation: str

    def __post_init__(self):
        for value in (self.grant_id, self.actor_id):
            if (type(value) is not str or not 1 <= len(value) <= 128 or not value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise HttpFixtureInvalid("fixture dispatch consent requires its original identity")
            value.encode("utf-8", errors="strict")
        if (not isinstance(self.scope, HttpFixtureScope) or type(self.operation) is not str
                or self.operation not in {"setup", "cleanup"}
                or any(type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                    for value in (self.grant_digest, self.source_scope_digest))):
            raise HttpFixtureInvalid("fixture dispatch consent requires one exact operation and scope")

    def require_phase(self, scope, phase):
        if (scope != self.scope or type(phase) is not str
                or not ((self.operation == "setup" and phase == "setup")
                    or (self.operation == "cleanup" and phase.startswith("cleanup:") and len(phase) > 8))):
            raise HttpFixtureInvalid("fixture consent is not for this original phase")

    @property
    def pin(self):
        return {"grant_id": self.grant_id, "grant_digest": self.grant_digest,
            "source_scope_digest": self.source_scope_digest}


class HttpFixtureTransactionConsentPort(Protocol):
    def consent_pin(self, scope, phase) -> dict: ...
    def require(self, session, scope, phase, command) -> None: ...
    def claim(self, session, dispatch) -> None: ...
    def complete(self, session, dispatch) -> None: ...
