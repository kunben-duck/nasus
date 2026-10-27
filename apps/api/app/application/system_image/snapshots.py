from __future__ import annotations

from ..platform.errors import PlatformApplicationError
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ...domain.system_image.publication import PublicationChanged, PublicationIntegrityError
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageArtifactUnavailable
from .read_model_port import SystemImageReadPort


class SystemImageSnapshotQueryApplicationService:
    """System-image snapshot read use cases."""

    def __init__(self, reader: SystemImageReadPort) -> None:
        self._reader = reader

    def get_system_image(self, project_id: str, *, working: bool = False):
        try:
            view = self._reader.read(project_id, working=True) if working else self._reader.read(project_id)
            if view.scope.project_id != project_id or view.response.project.id != project_id:
                raise SourceAccessDenied("snapshot scope project mismatch")
            self._reader.require_current(view.scope)
            if view.verify_publication:
                view.verify_publication()
            return view.response
        except PublicationChanged as exc:
            raise PlatformApplicationError("publication_changed", "Published image changed. Reload the image.", 409) from exc
        except (PublicationIntegrityError, ImageRevisionIntegrityError) as exc:
            raise PlatformApplicationError("image_integrity_failed", "Published image failed integrity verification.", 502) from exc
        except ImageArtifactUnavailable as exc:
            raise PlatformApplicationError("image_artifact_unavailable", "Published image is unavailable.", 503) from exc
        except StaleSourceAccessScope as exc:
            raise PlatformApplicationError("source_scope_changed", "Source access changed. Reload the image.", 409) from exc
        except SourceAccessDenied as exc:
            raise PlatformApplicationError("source_access_denied", "Source is not available.", 403) from exc


__all__ = ["SystemImageSnapshotQueryApplicationService"]
