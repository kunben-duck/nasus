from typing import Callable, Protocol

from ...domain.quality_loop.native_environment import NativeEnvironmentObservation


class NativeTargetEnvironmentPort(Protocol):
    def policy_digest(self, project_id: str, environment_id: str,
                      *, require_work: Callable[[], None]) -> str: ...
    def inspect(self, project_id: str, environment_id: str, artifact_hash: str,
                *, require_work: Callable[[], None]) -> NativeEnvironmentObservation: ...
