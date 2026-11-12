"""M1 pins knowledge, not implementation, test execution, or release authority."""


class VersionDeliveryConflict(ValueError):
    pass


class VersionDeliveryIntegrityError(ValueError):
    pass


def require_matching_pin(request, pin):
    if request.expected_head_id != request.publication_id:
        raise VersionDeliveryConflict("Select the exact current publication head")
    if any(getattr(request, key) != getattr(pin, key) for key in (
            "publication_id", "image_revision_id", "image_artifact_hash")):
        raise VersionDeliveryConflict("Image binding does not match the published image")
