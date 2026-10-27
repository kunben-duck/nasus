"""Worker command pins and transaction ports; no public dispatch authority here."""
from typing import Protocol

from pydantic import model_validator

from .test_design_output import Digest, GenerationValue, Id


class HttpFixtureCommandAuthority(GenerationValue):
    invocation_id: Id
    request_digest: Digest

    @model_validator(mode="after")
    def bounded_identity(self):
        if any(ord(char) < 32 or ord(char) == 127 for char in self.invocation_id):
            raise ValueError("fixture command requires a bounded original invocation identity")
        return self


class HttpFixtureTransactionCommandPort(Protocol):
    def command_pin(self, session, scope, phase) -> dict: ...
    def require(self, session, scope, phase, command) -> None: ...
    def require_existing(self, session, dispatch) -> None: ...
    def claim(self, session, dispatch) -> None: ...
    def complete(self, session, dispatch) -> None: ...


class HttpFixtureCommandRepositoryPort(Protocol):
    def bind(self, inputs, authority: HttpFixtureCommandAuthority, *, require_current): ...
    def require(self, inputs, authority: HttpFixtureCommandAuthority): ...
    def fence(self, inputs, authority: HttpFixtureCommandAuthority) -> HttpFixtureTransactionCommandPort: ...
