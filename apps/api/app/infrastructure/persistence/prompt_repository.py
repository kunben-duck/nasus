from __future__ import annotations

from sqlalchemy import select

from ...domain.platform.prompt_registry import PromptDefinition
from .db_models import PromptDefinitionRecord, PromptSelectionRecord
from .unit_of_work import session_scope


class SQLAlchemyPromptRegistry:
    """Immutable prompt versions with an independently mutable active pointer."""

    def register(self, definition: PromptDefinition) -> None:
        with session_scope() as session:
            key = {"prompt_id": definition.prompt_id, "version": definition.version}
            row = session.get(PromptDefinitionRecord, key)
            if row is not None:
                if row.content_hash != definition.content_hash:
                    raise RuntimeError(
                        f"prompt {definition.prompt_id}@{definition.version} content hash changed; "
                        "publish a new version instead"
                    )
                return
            session.add(
                PromptDefinitionRecord(
                    prompt_id=definition.prompt_id,
                    version=definition.version,
                    name=definition.name,
                    purpose=definition.purpose,
                    input_schema_ref=definition.input_schema_ref,
                    output_schema_ref=definition.output_schema_ref,
                    safety_rules_ref=definition.safety_rules_ref,
                    rollback_to=definition.rollback_to,
                    system_template=definition.system_template,
                    content_hash=definition.content_hash,
                )
            )
            selection = session.get(PromptSelectionRecord, definition.prompt_id)
            if selection is None:
                session.add(
                    PromptSelectionRecord(
                        prompt_id=definition.prompt_id,
                        active_version=definition.version,
                    )
                )

    def get_active(self, prompt_id: str) -> PromptDefinition:
        with session_scope() as session:
            selection = session.get(PromptSelectionRecord, prompt_id)
            if selection is None:
                raise KeyError(f"prompt {prompt_id} has no active version")
            row = session.get(
                PromptDefinitionRecord,
                {"prompt_id": prompt_id, "version": selection.active_version},
            )
        if row is None:
            raise RuntimeError(
                f"active prompt selection {prompt_id}@{selection.active_version} is invalid"
            )
        return self._to_definition(row)

    def get(self, prompt_id: str, version: str) -> PromptDefinition | None:
        with session_scope() as session:
            row = session.get(
                PromptDefinitionRecord,
                {"prompt_id": prompt_id, "version": version},
            )
        return self._to_definition(row) if row is not None else None

    def list_versions(self, prompt_id: str | None = None) -> list[PromptDefinition]:
        statement = select(PromptDefinitionRecord).order_by(
            PromptDefinitionRecord.prompt_id,
            PromptDefinitionRecord.version,
        )
        if prompt_id:
            statement = statement.where(PromptDefinitionRecord.prompt_id == prompt_id)
        with session_scope() as session:
            rows = session.scalars(statement).all()
        return [self._to_definition(row) for row in rows]

    def activate(self, prompt_id: str, version: str) -> PromptDefinition:
        with session_scope() as session:
            row = session.get(
                PromptDefinitionRecord,
                {"prompt_id": prompt_id, "version": version},
            )
            if row is None:
                raise KeyError(f"unknown prompt version {prompt_id}@{version}")
            selection = session.get(PromptSelectionRecord, prompt_id)
            if selection is None:
                selection = PromptSelectionRecord(prompt_id=prompt_id)
                session.add(selection)
            selection.active_version = version
        return self._to_definition(row)

    @staticmethod
    def _to_definition(row: PromptDefinitionRecord) -> PromptDefinition:
        return PromptDefinition(
            prompt_id=row.prompt_id,
            name=row.name,
            version=row.version,
            purpose=row.purpose,
            input_schema_ref=row.input_schema_ref,
            output_schema_ref=row.output_schema_ref,
            safety_rules_ref=row.safety_rules_ref,
            rollback_to=row.rollback_to,
            system_template=row.system_template,
        )


__all__ = ["SQLAlchemyPromptRegistry"]
