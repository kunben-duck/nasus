"""Count and paginate canonical operations after SQL source-visibility filtering."""
from sqlalchemy import and_, case, func, literal, select, true, union_all
from sqlalchemy.orm import aliased
from sqlalchemy.exc import SQLAlchemyError

from ...domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL
from ...domain.quality_loop.http_fixture_grant import GRANT_TOOL
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from ...domain.quality_loop.http_fixture_history import HttpFixtureHistoryUnavailable
from .db_models import ToolInvocationRecord as Command
from .http_fixture_grant_models import HttpFixtureGrantRecord as Grant
from .http_fixture_recipe_models import HttpFixtureRecipeRecord as Recipe
from .source_snapshot_models import SourceManifestMemberRecord as Member
from .unit_of_work import session_scope


class HttpFixtureHistoryRepository:
    @staticmethod
    def _inventory(project_id, binding_ids, *, invocation_id=None):
        branches = []
        for tool in (GRANT_TOOL, FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL):
            original = aliased(Command)
            selected = Command if tool == FIXTURE_COMMAND_TOOL else original
            recipe_join = and_(Recipe.project_id == project_id,
                Recipe.record_id == Command.input_payload["recipe_id"].as_string(),
                Recipe.artifact_hash == Command.input_payload["recipe_artifact_hash"].as_string())
            base = select(Command.id.label("invocation_id"), Command.tool_id, Command.status, Command.input_payload,
                Recipe.record_id.label("recipe_id"), Recipe.artifact_hash.label("recipe_artifact_hash"), Recipe.manifest_id,
                (original.id if tool == FIXTURE_CANCEL_TOOL else literal(None)).label("original_id"),
                (original.tool_id if tool == FIXTURE_CANCEL_TOOL else literal(None)).label("original_tool"),
                (original.status if tool == FIXTURE_CANCEL_TOOL else literal(None)).label("original_status"),
                (original.input_payload if tool == FIXTURE_CANCEL_TOOL else literal(None)).label("original_input")).select_from(Command)
            if tool != GRANT_TOOL:
                if tool == FIXTURE_CANCEL_TOOL:
                    base = base.outerjoin(original, and_(original.id == Command.input_payload["invocation_id"].as_string(),
                        original.tool_id == FIXTURE_COMMAND_TOOL, original.input_payload["project_id"].as_string() == project_id))
                base = base.outerjoin(Grant, and_(Grant.project_id == project_id,
                    Grant.record_id == selected.input_payload["grant_id"].as_string(),
                    Grant.operation == selected.input_payload["operation"].as_string()))
                recipe_join = and_(Recipe.project_id == Grant.project_id, Recipe.record_id == Grant.recipe_id,
                    Recipe.artifact_hash == Grant.recipe_artifact_hash)
            base = base.outerjoin(Recipe, recipe_join).where(Command.tool_id == tool,
                Command.input_payload["project_id"].as_string() == project_id)
            if invocation_id is not None:
                base = base.where(Command.id == invocation_id)
            branches.append(base)
        original_commands = union_all(*branches).cte("original_fixture_commands")
        hidden = aliased(Member)
        member = select(Member.manifest_id).where(Member.project_id == project_id,
            Member.manifest_id == original_commands.c.manifest_id).exists()
        inaccessible = select(hidden.manifest_id).where(hidden.project_id == project_id,
            hidden.manifest_id == original_commands.c.manifest_id, hidden.binding_id.not_in(binding_ids)).exists()
        valid = and_(original_commands.c.recipe_id.is_not(None), member)
        visible = select(original_commands).where(valid, ~inaccessible).cte("visible_fixture_commands")
        invalid = select(func.count()).select_from(original_commands).where(~valid).scalar_subquery()
        return visible, invalid

    @classmethod
    def _statement(cls, project_id, binding_ids, *, after_id="", limit=3, invocation_id=None):
        visible, invalid = cls._inventory(project_id, binding_ids, invocation_id=invocation_id)
        total = select(func.count().label("total"), invalid.label("invalid_total")).select_from(visible).subquery()
        page = select(visible).where(visible.c.invocation_id > after_id).order_by(visible.c.invocation_id).limit(limit + 1).subquery()
        return select(total.c.total, total.c.invalid_total, page).select_from(total.outerjoin(page, true())).order_by(page.c.invocation_id)

    @staticmethod
    def _row(row):
        command = {"id": row.invocation_id, "tool_id": row.tool_id, "status": row.status, "input_payload": row.input_payload}
        original = ({"id": row.original_id, "tool_id": row.original_tool, "status": row.original_status,
            "input_payload": row.original_input} if row.original_id is not None else None)
        return {"command": command, "execution": original,
            "recipe_id": row.recipe_id, "recipe_artifact_hash": row.recipe_artifact_hash}

    @classmethod
    def _read(cls, statement):
        try:
            with session_scope() as session:
                rows = session.execute(statement).all()
                if not rows or rows[0].invalid_total != 0:
                    raise HttpFixtureInvalid("fixture history has unresolved original ancestry; no partial complete inventory")
                return rows[0].total, [cls._row(row) for row in rows if row.invocation_id is not None]
        except SQLAlchemyError as exc:
            raise HttpFixtureHistoryUnavailable("original fixture history storage is unavailable") from exc

    def list_history(self, request, *, binding_ids):
        total, selected = self._read(self._statement(request.project_id, binding_ids, after_id=request.after_id, limit=request.limit))
        # Preserve the look-ahead for application-level archive verification.
        items = selected[:request.limit]
        return {"items": items, "total": total,
            "next_after_id": items[-1]["command"]["id"] if len(selected) > request.limit else None,
            "lookahead": selected[request.limit:]}

    def read_history(self, project_id, invocation_id, *, binding_ids):
        total, selected = self._read(self._statement(project_id, binding_ids, invocation_id=invocation_id, limit=1))
        if total != 1 or len(selected) != 1:
            raise KeyError("original fixture operation not found")
        return selected[0]
