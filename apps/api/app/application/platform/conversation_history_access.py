from .errors import PlatformApplicationError


HISTORY_TOOLS = frozenset({"query.conversation.history.search", "query.conversation.history.read"})


class ConversationHistoryReceiptAccess:
    def __init__(self, memory):
        self.memory = memory

    def applies(self, invocation):
        return invocation.tool_id in HISTORY_TOOLS

    def require_access(self, invocation):
        if not invocation.conversation_id:
            raise PlatformApplicationError("history_scope_missing", "Conversation scope is required", 403)
        conversation = self.memory.conversation(invocation.conversation_id)
        try:
            self.memory.guard(conversation)
        except PermissionError as exc:
            raise PlatformApplicationError("history_access_denied", "History is unavailable in the current access scope", 403) from exc

    def require_batch_access(self, invocations):
        for invocation in invocations:
            if self.applies(invocation):
                self.require_access(invocation)

    def broadcast_view(self, invocation):
        if not self.applies(invocation) or not invocation.result or not invocation.result.conversation_history:
            return invocation
        view = invocation.model_copy(deep=True)
        view.result.conversation_history = {"reference_only": True, "messages": [
            {"message_id": row["message_id"]} for row in view.result.conversation_history.get("messages", [])]}
        return view
