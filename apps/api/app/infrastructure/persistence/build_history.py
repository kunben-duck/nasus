"""Build inbox projection. Never select tool payloads or assistant message bodies."""
from sqlalchemy import case, func, select

from .db_models import (
    AgentGoalRecord as Goal, ConversationMessageRecord as Message, ConversationRecord as Chat,
    ConversationTurnRecord as Turn, ToolInvocationRecord as Tool,
)
from .unit_of_work import session_scope


def build_history_rows(owner, project_id, unbound, query):
    first_prompt = select(Message.blocks[0]["text"].as_string()).where(
        Message.conversation_id == Chat.id, Message.role == "user"
    ).order_by(Message.created_at, Message.id).limit(1).scalar_subquery()
    title = case((Chat.title.in_(["", "Build", "构建"]), func.coalesce(first_prompt, Chat.title)), else_=Chat.title)
    def has(model, *statuses):
        return select(model.id).where(model.conversation_id == Chat.id, model.status.in_(statuses)).exists()

    goal_confirmation = select(Goal.id).where(
        Goal.conversation_id == Chat.id, Goal.status == "paused",
        Goal.pause_reason.in_(("waiting_confirmation", "waiting_approval")),
    ).exists()
    task = case((has(Tool, "waiting_confirmation", "waiting_approval") | goal_confirmation, "confirmation"),
                (has(Turn, "accepted", "planning", "streaming") | has(Tool, "pending", "running") | has(Goal, "running", "pending"), "running"),
                (has(Goal, "paused", "blocked"), "paused"), else_=None)
    last_turn = select(func.max(Turn.updated_at)).where(Turn.conversation_id == Chat.id).scalar_subquery()
    last_goal = select(func.max(func.coalesce(Goal.last_progress_at, Goal.started_at))).where(
        Goal.conversation_id == Chat.id
    ).scalar_subquery()
    activity = func.greatest(Chat.last_message_at, last_turn, last_goal)
    stmt = select(Chat, func.substr(title, 1, 120), task, activity).where(Chat.space_type == "build", Chat.initiator_id == owner)
    if project_id:
        stmt = stmt.where(Chat.project_id == project_id)
    if unbound:
        stmt = stmt.where(Chat.project_id.is_(None))
    if query:
        stmt = stmt.where(func.lower(title).contains(query.lower(), autoescape=True))
    with session_scope() as db:
        rows = stmt.order_by(activity.desc().nulls_last(), Chat.id).execution_options(yield_per=50)
        for chat, name, status, timestamp in db.execute(rows):
            # The existing delivery ACL rechecks protected metadata, not a cached membership flag.
            metadata = db.scalars(select(Message.message_metadata).where(Message.conversation_id == chat.id))
            yield chat, metadata, {"id": chat.id, "title": name, "project_id": chat.project_id,
                                   "activity_at": timestamp, "task_status": status}
