from __future__ import annotations

from typing import Callable, Protocol

from ...domain.quality_loop.native_build import NativeBuildOutput, NativeBuildRequest


class NativeBuildPort(Protocol):
    def policy(self) -> dict: ...

    def build(self, request: NativeBuildRequest, *, require_work: Callable[[], None] | None = None) -> NativeBuildOutput: ...


class NativeBuildArtifactPort(Protocol):
    def put(self, build_id: str, request: NativeBuildRequest, output: NativeBuildOutput) -> dict: ...

    def read(self, build_id: str, request: NativeBuildRequest, *, artifact_ref: str, artifact_hash: str) -> dict: ...
