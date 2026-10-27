"""Original recipe pins, independently confirmed command, audit and atomic Outbox."""
from uuid import uuid4

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.http_fixture_recipes import HttpFixtureRecipeRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_recipe import (
    RECIPE_SCHEMA, RECIPE_TOOL, RECIPE_EVENT, RECIPE_EVENT_FIELDS, RECIPE_PARENT_FIELDS,
    recipe_identity, recipe_metadata,
)
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from .db_models import AuditEventRecord, ToolInvocationRecord
from .environment_observation_repository import EnvironmentObservationRepository
from .event_outbox_repository import EventOutboxRepository
from .http_fixture_recipe_models import HttpFixtureRecipeRecord as Record
from .image_revision_models import ImageRevisionRecord
from .source_snapshot_models import SourceManifestRecord
from .run_plan_models import RunPlanRecord as Plan
from .run_plan_repository import RunPlanRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class HttpFixtureRecipeRepository(EnvironmentObservationRepository):
    record_model = Record
    record_tool = RECIPE_TOOL

    @staticmethod
    def _request(command):
        try:
            return HttpFixtureRecipeRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError):
            raise RunPlanIntegrityError("fixture recipe canonical original request invalid") from None

    @staticmethod
    def _parents(session, request):
        plan = session.get(Plan, request.run_plan_id)
        if plan is None or plan.project_id != request.project_id or plan.artifact_hash != request.run_plan_artifact_hash:
            raise RunPlanIntegrityError("fixture recipe original saved plan differs")
        value = RunPlanRepository._verify(session, plan)
        image = session.get(ImageRevisionRecord, value["image_revision_id"])
        manifest = session.get(SourceManifestRecord, value["manifest_id"])
        if (image is None or manifest is None or image.project_id != request.project_id
                or manifest.project_id != request.project_id or image.manifest_id != value["manifest_id"]):
            raise RunPlanIntegrityError("fixture recipe registered image/manifest ancestry differs")
        # The original RunPlan metadata deliberately has no source hashes.
        # Resolve their immutable FK parents, rather than inventing fields in old records.
        return {**value, "image_artifact_hash": image.artifact_hash, "manifest_hash": manifest.content_hash}

    @classmethod
    def _verify(cls, session, row):
        if row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash:
            raise RunPlanIntegrityError("registered fixture recipe metadata invalid")
        request = cls._request(session.get(ToolInvocationRecord, row.invocation_id))
        cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        parent = cls._parents(session, request)
        original = {"schema": RECIPE_SCHEMA, "project_id": row.project_id, "record_id": row.record_id,
            "invocation_id": row.invocation_id, "actor_id": row.actor_id, "recorded_at": row.recorded_at,
            "request": request.model_dump(mode="json"), "parents": {key: getattr(row, key) for key in RECIPE_PARENT_FIELDS},
            "fixture_digest": row.fixture_digest}
        expected = recipe_metadata(original)
        fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
        if (acceptance_digest(row.payload) != acceptance_digest(expected) or any(getattr(row, key) != expected[key] for key in fields)
                or row.record_id != recipe_identity(row.invocation_id) or row.status != "recorded"
                or any(getattr(row, key) != parent[key] for key in RECIPE_PARENT_FIELDS)
                or not row.artifact_ref.startswith("s3://")):
            raise RunPlanIntegrityError("registered fixture recipe original ancestry or authority differs")
        return expected

    def record(self, request, payload, ref, metadata, *, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, metadata["actor_id"])
            prior = self._committed(session, request, metadata["actor_id"], metadata["invocation_id"])
            command = self._canonical(session, request, metadata["invocation_id"], metadata["actor_id"], historical=prior is not None)
            if prior is not None:
                if acceptance_digest(prior) != acceptance_digest(metadata):
                    raise RunPlanIntegrityError("fixture recipe replay cannot replace committed original bytes")
                require_access()
                return prior
            parent = self._parents(session, request)
            if (acceptance_digest(recipe_metadata(payload)) != acceptance_digest(metadata)
                    or any(metadata[key] != parent[key] for key in RECIPE_PARENT_FIELDS)):
                raise RunPlanIntegrityError("fixture recipe archive differs from canonical ancestry")
            require_access()
            fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
            row = Record(**{key: metadata[key] for key in fields}, artifact_ref=ref, payload=metadata,
                content_hash=acceptance_digest(metadata))
            session.add(row)
            session.flush()
            self._verify(session, row)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=row.recorded_at, actor=row.actor_id, actor_kind="user",
                action=RECIPE_EVENT, entity_type="http_fixture_recipe", entity_id=row.record_id, status="recorded",
                summary="Fixed complete fixture definition registered; no target dispatch or verified coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["http_fixture_recipe:" + row.record_id], evidence_refs=[],
                event_metadata={"run_plan_id": request.run_plan_id, "execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=RECIPE_EVENT,
                occurred_at=row.recorded_at, correlation_id=request.project_id, entity_type="http_fixture_recipe", entity_id=row.record_id,
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=0, mutation_kind="append", patch={key: metadata[key] for key in RECIPE_EVENT_FIELDS},
                query_keys=[["http-fixture-recipes", request.project_id]], snapshot_hint=True), session=session)
            require_access()
            session.flush()
            return metadata

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != RECIPE_EVENT:
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="http_fixture_recipe",
            query_key="http-fixture-recipes", error=RunPlanIntegrityError)
        if event.patch != {key: value[key] for key in RECIPE_EVENT_FIELDS}:
            raise RunPlanIntegrityError("fixture recipe event differs from original fact")
