from ...domain.quality_loop.version_delivery import VersionDeliveryConflict, VersionDeliveryIntegrityError
from ...domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError
from ...domain.system_image.publication import PublicationChanged, PublicationIntegrityError
from ...domain.system_image.source_access import StaleSourceAccessScope
from ..platform.errors import PlatformApplicationError


DELIVERY_ERROR_STATUS = {
    "version_delivery_conflict": 409, "version_delivery_forbidden": 403,
    "version_delivery_not_found": 404, "version_delivery_integrity_failed": 502,
    "version_delivery_unavailable": 503, "version_delivery_invalid": 400,
}


def delivery_error(error):
    if isinstance(error, PlatformApplicationError):
        return error
    if isinstance(error, PermissionError):
        code, message = "version_delivery_forbidden", "Version image inputs are not available."
    elif isinstance(error, (VersionDeliveryConflict, PublicationChanged, StaleSourceAccessScope)):
        code, message = "version_delivery_conflict", str(error)
    elif isinstance(error, (VersionDeliveryIntegrityError, PublicationIntegrityError, ImageRevisionIntegrityError)):
        code, message = "version_delivery_integrity_failed", "Version image binding could not be verified."
    elif isinstance(error, ImageArtifactUnavailable):
        code, message = "version_delivery_unavailable", "Version image archive is temporarily unavailable."
    elif isinstance(error, KeyError):
        code, message = "version_delivery_not_found", "Version or published image was not found in this project."
    else:
        code, message = "version_delivery_invalid", "Invalid Version creation input."
    return PlatformApplicationError(code, message, DELIVERY_ERROR_STATUS[code])
