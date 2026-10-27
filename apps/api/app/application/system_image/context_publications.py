from typing import Protocol

from ...domain.system_image.context_pack import ContextPackIntegrityError, ContextPublicationChanged
from ...domain.system_image.publication import PublicationChanged, PublicationIntegrityError
from .publication_read_models import PublishedImagePin


class ContextPublicationPort(Protocol):
    def pin(self, project_id: str, publication_id: str, *, require_current: bool = False) -> PublishedImagePin: ...


def context_publication(port: ContextPublicationPort, request, *, historical=False):
    if port is None:
        raise ContextPackIntegrityError("Published context requires a publication port")
    try:
        pin = port.pin(request.project_id, request.publication_id, require_current=not historical)
    except PublicationChanged as exc:
        raise ContextPublicationChanged("Published image head changed; preview current inputs") from exc
    except (PublicationIntegrityError, KeyError) as exc:
        raise ContextPackIntegrityError("Context publication could not be verified") from exc
    if pin.image_revision_id != request.image_revision_id or pin.image_artifact_hash != request.image_artifact_hash:
        raise ContextPackIntegrityError("Context publication belongs to a different image")
    return pin.model_dump(mode="json")
