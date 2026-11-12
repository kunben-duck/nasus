"""Reauthorize M1 message events at delivery, including durable SSE replay."""
from .errors import PlatformApplicationError


class DeliveryConversationEventAccess:
    def __init__(self, read_access, *, conversation_scope, require_conversation_access):
        self.read_access = read_access
        self.conversation_scope = conversation_scope
        self.require_conversation_access = require_conversation_access

    def can_access(self, event):
        message = event.payload.get("message")
        metadata = message.get("metadata") if isinstance(message, dict) else None
        if not self.read_access.applies(metadata):
            return True
        if not event.conversation_id:
            raise PlatformApplicationError("delivery_history_invalid", "Delivery event scope could not be verified.", 502)
        conversation = self.conversation_scope(event.conversation_id)
        if conversation is None:
            return False
        if conversation.id != event.conversation_id:
            raise PlatformApplicationError("delivery_history_invalid", "Delivery event scope could not be verified.", 502)
        try:
            self.require_conversation_access(conversation)
            self.read_access.require_metadata_access(conversation.project_id, (metadata,))
        except PlatformApplicationError as exc:
            if exc.status_code == 403:
                return False
            raise
        return True
