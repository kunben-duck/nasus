from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select

from ...domain.platform.llm_call import LLMCall
from .database import SessionLocal
from .db_models import LLMCallRecord


class SQLAlchemyLLMCallRepository:
    """PostgreSQL/SQLAlchemy persistence for redacted LLMCall facts."""

    def __init__(self, session_factory: Callable = SessionLocal) -> None:
        self._session_factory = session_factory

    def persist_llm_call(self, call: LLMCall) -> None:
        session = self._session_factory()
        try:
            session.add(self._to_record(call))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_llm_calls(
        self,
        *,
        route: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        agent_goal_id: str | None = None,
        tool_invocation_id: str | None = None,
        limit: int = 100,
    ) -> list[LLMCall]:
        statement = select(LLMCallRecord)
        filters = (
            (LLMCallRecord.route, route),
            (LLMCallRecord.project_id, project_id),
            (LLMCallRecord.conversation_id, conversation_id),
            (LLMCallRecord.agent_goal_id, agent_goal_id),
            (LLMCallRecord.tool_invocation_id, tool_invocation_id),
        )
        for column, value in filters:
            if value is not None:
                statement = statement.where(column == value)
        statement = statement.order_by(LLMCallRecord.occurred_at.desc()).limit(limit)
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_record(call: LLMCall) -> LLMCallRecord:
        return LLMCallRecord(
            id=call.id,
            occurred_at=call.occurred_at,
            route=call.route,
            purpose=call.purpose,
            provider=call.provider,
            model_name=call.model_name,
            selected_provider=call.selected_provider,
            selected_model_name=call.selected_model_name,
            runtime_mode=call.runtime_mode,
            outcome=call.outcome,
            reason=call.reason,
            prompt_id=call.prompt_id,
            prompt_version=call.prompt_version,
            project_id=call.project_id,
            version_id=call.version_id,
            task_id=call.task_id,
            conversation_id=call.conversation_id,
            agent_goal_id=call.agent_goal_id,
            tool_invocation_id=call.tool_invocation_id,
            model_calls=call.model_calls,
            input_token_count=call.input_token_count,
            output_token_count=call.output_token_count,
            usage_source=call.usage_source,
            latency_ms=call.latency_ms,
            input_item_count=call.input_item_count,
            output_item_count=call.output_item_count,
            request_hash=call.request_hash,
            response_hash=call.response_hash,
        )

    @staticmethod
    def _to_domain(row: LLMCallRecord) -> LLMCall:
        return LLMCall(
            id=row.id,
            occurred_at=row.occurred_at,
            route=row.route,  # type: ignore[arg-type]
            purpose=row.purpose,
            provider=row.provider,
            model_name=row.model_name,
            selected_provider=row.selected_provider,
            selected_model_name=row.selected_model_name,
            runtime_mode=row.runtime_mode,  # type: ignore[arg-type]
            outcome=row.outcome,  # type: ignore[arg-type]
            reason=row.reason,
            prompt_id=row.prompt_id,
            prompt_version=row.prompt_version,
            project_id=row.project_id,
            version_id=row.version_id,
            task_id=row.task_id,
            conversation_id=row.conversation_id,
            agent_goal_id=row.agent_goal_id,
            tool_invocation_id=row.tool_invocation_id,
            model_calls=row.model_calls,
            input_token_count=row.input_token_count,
            output_token_count=row.output_token_count,
            usage_source=row.usage_source,  # type: ignore[arg-type]
            latency_ms=row.latency_ms,
            input_item_count=row.input_item_count,
            output_item_count=row.output_item_count,
            request_hash=row.request_hash,
            response_hash=row.response_hash,
        )


__all__ = ["SQLAlchemyLLMCallRepository"]
