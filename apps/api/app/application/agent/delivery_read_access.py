"""Live source authorization for persisted M1 conversation disclosures."""
from collections.abc import Mapping

from ..platform.errors import PlatformApplicationError
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope


class DeliveryConversationReadAccess:
    metadata_keys = ("delivery_intake", "version_delivery", "requirement_intake")

    def __init__(self, source_access):
        self.source_access = source_access

    @classmethod
    def applies(cls, metadata):
        return isinstance(metadata, Mapping) and any(key in metadata for key in cls.metadata_keys)

    def require_access(self, conversation):
        self.require_metadata_access(conversation.project_id,
            (message.metadata for message in conversation.messages))

    def require_metadata_access(self, project_id, metadata_items):
        protected = [metadata for metadata in metadata_items if self.applies(metadata)]
        if not protected:
            return
        if not isinstance(project_id, str) or not project_id:
            raise PlatformApplicationError("delivery_history_invalid", "Delivery history scope could not be verified.", 502)
        for metadata in protected:
            for key in self.metadata_keys:
                if key in metadata and (not isinstance(metadata[key], Mapping)
                        or metadata[key].get("project_id") != project_id):
                    raise PlatformApplicationError("delivery_history_invalid", "Delivery history scope could not be verified.", 502)
        try:
            # Authorization is fresh per response/event, not a cached image read.
            self.source_access.require_all_sources_access(project_id)
        except (SourceAccessDenied, StaleSourceAccessScope) as exc:
            raise PlatformApplicationError("source_access_denied", "Delivery history is unavailable in the current access scope.", 403) from exc
