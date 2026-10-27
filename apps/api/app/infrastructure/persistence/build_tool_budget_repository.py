"""Goal-locked, append-only tool reservations across phases and process restarts."""
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import AuditEvent, EventPayload
from ...domain.agent.image_plan_policy import BUILD_GOAL_TEMPLATES
from ...domain.system_image.build_plan import BuildPlanIntegrityError, decode_build_plan
from ...domain.system_image.build_tool_budget import BuildToolBudget, GOAL_BOUND_BUILD_CONTROLS, consumption_payload
from ...domain.system_image.source_snapshots import snapshot_digest
from .build_plan_models import BuildPlanRecord
from .build_tool_budget_models import BuildToolBudgetRecord, BuildToolConsumptionRecord
from .db_models import AgentGoalRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .unit_of_work import session_scope


class BuildToolBudgetRepository:
    @staticmethod
    def initialize_in_session(session, goal, record):
        if goal.goal_template not in BUILD_GOAL_TEMPLATES:
            return
        limit, kind = 80, "default_guardrail"
        origin = {"target_refs": goal.target_refs}
        plans = [ref.removeprefix("build_plan:") for ref in goal.target_refs if ref.startswith("build_plan:")]
        if plans:
            if len(plans) != 1:
                raise BuildPlanIntegrityError("Tool budget requires one original build plan.")
            row = session.get(BuildPlanRecord, plans[0])
            if row is None or row.project_id != goal.project_id:
                raise BuildPlanIntegrityError("Original tool budget plan is unavailable.")
            proposal = decode_build_plan(row.payload)
            if row.plan_digest != proposal.digest or proposal.intent.project_id != goal.project_id:
                raise BuildPlanIntegrityError("Original tool budget plan failed integrity verification.")
            pins = [ref.removeprefix("build_plan_digest:") for ref in goal.target_refs if ref.startswith("build_plan_digest:")]
            if pins and pins != [row.plan_digest]:
                raise BuildPlanIntegrityError("Original tool budget plan pin changed.")
            limit, kind = proposal.intent.budget.max_tool_calls, "saved_plan"
            origin = {"plan_id": row.plan_id, "plan_digest": row.plan_digest}
        else:
            requests = [step.tool_input_payload.get("build_input_request", step.tool_input_payload)
                for step in goal.steps if step.phase == "acting" and (
                    step.selected_tool_id == "system_image.build.plan" or
                    (step.selected_tool_id == "query.system_image.status" and "build_input_request" in step.tool_input_payload))]
            if requests:
                if len(requests) != 1 or requests[0].get("project_id") != goal.project_id:
                    raise BuildPlanIntegrityError("Original source intent budget scope changed.")
                origin, kind = requests[0], "source_intent"
                limit = origin.get("budget", {}).get("max_tool_calls", 80)
        budget = BuildToolBudget(goal.id, goal.project_id, goal.conversation_id, goal.workflow_id,
            limit, snapshot_digest(origin), kind)
        record.tool_budget_hash = budget.digest
        session.flush()
        session.add(BuildToolBudgetRecord(goal_id=goal.id, payload=asdict(budget), content_hash=budget.digest))

    @staticmethod
    def _budget(session, goal):
        row = session.get(BuildToolBudgetRecord, goal.id)
        if goal.tool_budget_hash is None:
            if row is not None:
                raise BuildPlanIntegrityError("Legacy goal cannot acquire a fabricated tool ledger.")
            return None
        if row is None:
            raise BuildPlanIntegrityError("Original cumulative tool budget is missing.")
        budget = BuildToolBudget(**row.payload)
        if (budget.digest != row.content_hash or goal.tool_budget_hash != budget.digest
                or (budget.goal_id, budget.project_id, budget.conversation_id, budget.workflow_id) !=
                   (goal.id, goal.project_id, goal.conversation_id, goal.workflow_id)
                or goal.goal_template not in BUILD_GOAL_TEMPLATES):
            raise BuildPlanIntegrityError("Original cumulative tool budget scope changed.")
        return budget

    @staticmethod
    def _input_digest(invocation):
        return snapshot_digest({"conversation_id": invocation.conversation_id, "tool_id": invocation.tool_id,
            "initiator_surface": invocation.initiator_surface, "initiator_actor": invocation.initiator_actor,
            "input": invocation.input_payload})

    @classmethod
    def _entries(cls, session, budget):
        rows = session.scalars(select(BuildToolConsumptionRecord).where(
            BuildToolConsumptionRecord.goal_id == budget.goal_id).order_by(
                BuildToolConsumptionRecord.sequence).limit(budget.max_tool_calls + 1)).all()
        previous = budget.digest
        for sequence, row in enumerate(rows, 1):
            command = session.get(ToolInvocationRecord, row.invocation_id)
            if command is None:
                raise BuildPlanIntegrityError("Cumulative tool command is missing.")
            expected = consumption_payload(budget, invocation_id=row.invocation_id, tool_id=command.tool_id,
                work_key=row.work_key, input_digest=cls._input_digest(command), sequence=sequence, previous_hash=previous)
            if row.sequence != sequence or row.payload != expected or row.content_hash != snapshot_digest(expected):
                raise BuildPlanIntegrityError("Cumulative tool consumption failed integrity verification.")
            previous = row.content_hash
        return rows

    @staticmethod
    def _work_key(session, goal, invocation):
        from .conversation_repository import ConversationRepository
        from .image_plan_phase_repository import ImagePlanPhaseRepository

        if invocation.initiator_surface == "agent_loop" and invocation.initiator_actor == "agent":
            if goal.status != "running" or invocation.conversation_id != goal.conversation_id:
                raise BuildPlanIntegrityError("Tool reservation requires its running AgentGoal.")
            _, start = ImagePlanPhaseRepository.scope_in_session(session, ConversationRepository._to_goal(goal))
            clean = lambda value: {key: item for key, item in query_payload(value).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            candidates = [step for step in goal.steps[start:] if step.get("phase") == "acting"
                and step.get("selected_tool_id") == invocation.tool_id and step.get("status") in {"pending", "running", "blocked"}
                and step.get("tool_invocation_id") in {None, "", invocation.id}
                and clean(step.get("tool_input_payload", {})) == clean(invocation.input_payload)]
            # Investigation adds its own goal ID at dispatch, before the step is persisted.
            if not candidates and invocation.tool_id == "system_image.build.investigate":
                candidates = [step for step in goal.steps[start:] if step.get("phase") == "acting"
                    and step.get("selected_tool_id") == invocation.tool_id and step.get("status") in {"pending", "running", "blocked"}
                    and step.get("tool_invocation_id") in {None, "", invocation.id}
                    and {**clean(step.get("tool_input_payload", {})), "goal_id": goal.id} == clean(invocation.input_payload)]
            if len(candidates) != 1:
                raise BuildPlanIntegrityError("Tool work does not match one active goal step.")
            step = candidates[0]
            attempt = step.get("tool_input_payload", {}).get("agent_loop_attempt", 0)
            if type(attempt) is not int or not 0 <= attempt <= 1000:
                raise BuildPlanIntegrityError("Invalid tool attempt identity.")
            work_key = f"{goal.id}:{step['id']}:{attempt}"
            if (invocation.input_payload.get("agent_loop_iteration_id") != work_key
                    or invocation.idempotency_key != f"agent-goal:{goal.id}:step:{step['id']}:attempt:{attempt}"):
                raise BuildPlanIntegrityError("Canonical tool work identity changed.")
            return work_key
        if invocation.tool_id in GOAL_BOUND_BUILD_CONTROLS:
            from .build_tool_budget_controls import confirmed_control_work_key

            return confirmed_control_work_key(session, goal, invocation)
        if (invocation.tool_id != "system_image.build.investigate"
                or invocation.input_payload.get("goal_id") != goal.id
                or invocation.input_payload.get("confirmed_by_user") is not True
                or invocation.conversation_id not in {None, goal.conversation_id}
                or goal.status not in {"running", "paused", "blocked"}):
            raise BuildPlanIntegrityError("Non-agent work cannot consume a different goal's tool budget.")
        phases, _ = ImagePlanPhaseRepository.scope_in_session(session, ConversationRepository._to_goal(goal))
        plan_ids = [phases[-1].phase.plan_id] if phases else [ref.removeprefix("build_plan:")
            for ref in goal.target_refs if ref.startswith("build_plan:")]
        if plan_ids != [invocation.input_payload.get("plan_id")]:
            raise BuildPlanIntegrityError("Investigation does not belong to the original goal's current phase.")
        return "confirmed-investigation:" + invocation.id

    def reserve(self, invocation):
        from .conversation_repository import ConversationRepository

        goal_id = invocation.input_payload.get("agent_goal_id")
        if invocation.tool_id in GOAL_BOUND_BUILD_CONTROLS | {"system_image.build.investigate"}:
            explicit = invocation.input_payload.get("goal_id")
            if goal_id and explicit and goal_id != explicit:
                raise BuildPlanIntegrityError("Tool budget goal references disagree.")
            goal_id = goal_id or explicit
        if not goal_id:
            return False
        with session_scope() as session:
            goal = session.scalar(select(AgentGoalRecord).where(AgentGoalRecord.id == goal_id).with_for_update())
            if goal is None:
                raise BuildPlanIntegrityError("Tool budget goal is unavailable.")
            if goal.goal_template not in BUILD_GOAL_TEMPLATES:
                return False
            budget = self._budget(session, goal)
            if budget is None:
                return False  # Never reconstruct unmeasured pre-migration history.
            command = session.get(ToolInvocationRecord, invocation.id)
            if (command is None or self._input_digest(command) != self._input_digest(invocation)
                    or command.input_payload.get("project_id") != budget.project_id):
                raise BuildPlanIntegrityError("Canonical tool command differs from its budget scope.")
            rows = self._entries(session, budget)
            if any(row.invocation_id == invocation.id for row in rows):
                return True
            if command.status != "running":
                raise BuildPlanIntegrityError("Only claimed tool work can reserve cumulative budget.")
            work_key = self._work_key(session, goal, command)
            if any(row.work_key == work_key for row in rows):
                raise BuildPlanIntegrityError("This work identity already owns another canonical command.")
            budget.require_available(len(rows))
            payload = consumption_payload(budget, invocation_id=command.id, tool_id=command.tool_id,
                work_key=work_key, input_digest=self._input_digest(command), sequence=len(rows) + 1,
                previous_hash=rows[-1].content_hash if rows else budget.digest)
            session.add(BuildToolConsumptionRecord(invocation_id=command.id, goal_id=goal.id,
                sequence=payload["sequence"], work_key=work_key, payload=payload, content_hash=snapshot_digest(payload)))
            now = datetime.now(timezone.utc).isoformat()
            summary = "Reserved one tool work item under the original cumulative goal ceiling."
            session.add(ConversationRepository._new_audit_event_record(AuditEvent(id=str(uuid4()), occurred_at=now,
                actor="system", actor_kind="system", action="system_image.build.tool_work.reserved",
                entity_type="agent_goal", entity_id=goal.id, status="accepted", summary=summary,
                conversation_id=goal.conversation_id, tool_invocation_id=command.id, agent_goal_id=goal.id,
                metadata={"sequence": payload["sequence"], "budget_hash": budget.digest})))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()),
                event_type="system_image.build.tool_work.reserved", occurred_at=now,
                correlation_id=goal.conversation_id, entity_type="agent_goal", entity_id=goal.id,
                entity_version=payload["sequence"], mutation_kind="append",
                patch={"project_id": goal.project_id, "goal_id": goal.id, "invocation_id": command.id,
                    "sequence": payload["sequence"], "max_tool_calls": budget.max_tool_calls,
                    "budget_hash": budget.digest}, query_keys=[["agent-goal", goal.id]]), session=session)
            return True

    def inspect(self, goal_id):
        with session_scope() as session:
            goal = session.get(AgentGoalRecord, goal_id)
            if goal is None:
                raise KeyError(goal_id)
            budget = self._budget(session, goal)
            if budget is None:
                return None
            return budget, tuple(dict(row.payload) for row in self._entries(session, budget))
