"""The system-image context compiler depends on a port, not quality-loop tables."""
from typing import Protocol

from ...domain.system_image.context_pack import ContextPackIntegrityError


class IterationContextPort(Protocol):
    def pin(self, request, *, historical=False): ...


def context_iteration(port: IterationContextPort, request, *, historical=False):
    if port is None:
        raise ContextPackIntegrityError("Iteration context authority is unavailable")
    pin = port.pin(request, historical=historical)
    if (pin["project_id"] != request.project_id or pin["version_id"] != request.iteration.version_id
            or pin["image_revision_id"] != request.image_revision_id
            or pin["image_artifact_hash"] != request.image_artifact_hash):
        raise ContextPackIntegrityError("Iteration context authority differs from the selected image")
    return pin
