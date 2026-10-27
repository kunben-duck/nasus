from sqlalchemy import select

from ...application.system_image.structure_commands import StructureCommandSummary, UNFINISHED_STRUCTURE_STATUSES
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from .db_models import AuditEventRecord, ToolInvocationRecord
from .unit_of_work import session_scope


class StructureCommandRepository:
    """Bounded discovery of the caller's manual commands, never a dispatch path."""

    def unfinished(self, *, project_id, plan_id, plan_digest, actor_id, after_id, limit):
        if not 1 <= limit <= 51:
            raise ValueError("Invalid structural command query limit.")
        model, audit = ToolInvocationRecord, AuditEventRecord
        owned = select(audit.id).where(audit.tool_invocation_id == model.id,
            audit.entity_type == "tool_invocation", audit.entity_id == model.id,
            audit.action == "tool.invocation.created", audit.actor_kind == "user", audit.actor == actor_id).exists()
        query = select(model.id, model.status, model.input_payload, model.idempotency_key).where(
            model.tool_id == "system_image.build.structure", model.initiator_actor == "user", owned,
            model.status.in_(UNFINISHED_STRUCTURE_STATUSES), model.id > after_id,
            model.input_payload["project_id"].as_string() == project_id,
            model.input_payload["plan_id"].as_string() == plan_id,
            model.input_payload["plan_digest"].as_string() == plan_digest,
        ).order_by(model.id).limit(limit)
        with session_scope() as session:
            rows = session.execute(query).all()
        result = []
        for ident, status, payload, canonical_key in rows:
            target, key = payload.get("target_baseline_id"), payload.get("idempotency_key")
            if (not isinstance(target, str) or not target or len(target) > 128
                    or (key is not None and (not isinstance(key, str) or not key or len(key) > 128))
                    or (canonical_key is not None and canonical_key != key)):
                raise BuildPlanIntegrityError("Structural command identity is inconsistent.")
            result.append(StructureCommandSummary(ident, target, status, key))
        return tuple(result)
