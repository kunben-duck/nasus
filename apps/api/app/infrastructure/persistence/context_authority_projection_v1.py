"""Typed dependencies supplied by a verified archive, never by latest authority."""
from sqlalchemy import select

from ...domain.system_image.context_authorities import (
    ContextAuthorityDependency, REGISTER_CONTEXT_AUTHORITIES_TOOL, dependency_root,
    require_context_authority as require,
)
from ...domain.system_image.context_pack import COMPILE_CONTEXT_TOOL, ContextPackIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.system_image.context_pack_inputs import ContextCompileInput, ContextAuthorityRegistrationInput
from .authority_provenance_models import AuthorityProvenanceRecord as Authority
from .authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1, FACT_TYPES
from .context_authority_models import (
    ContextAuthorityRootRecord as Root, ContextAuthorityDependencyRecord as Dependency,
    ContextAuthorityBackfillTargetRecord as Target,
)
from .context_pack_models import ContextPackRecord as Context
from .db_models import ToolInvocationRecord as Command, ConversationRecord as Conversation, AgentGoalRecord as Goal
from .document_projection_models import SourceDocumentRevisionRecord as Document
from .image_revision_models import ImageObjectMemberRecord as Member
from .object_provenance_models import ObjectProvenanceNodeRecord as Node


def columns(row):
    return {col.name: getattr(row, col.name) for col in row.__table__.columns}


class ContextAuthorityProjectorV1:
    def dependencies(self, session, context, pins, *, reuse_snapshot=False):
        require(snapshot_digest(context.payload) == context.content_hash)
        grouped = {}
        for pin in pins:
            if pin["revision_id"] is not None:
                model = FACT_TYPES[pin["kind"]][0]
                native = session.get(model, pin["revision_id"])
                require(native is not None and native.project_id == context.project_id)
                grouped.setdefault(pin["kind"], []).append(native)
        for kind, natives in grouped.items():
            AuthorityProvenanceProjectorV1().facts(session, kind, tuple(natives), write=False,
                reuse_snapshot=reuse_snapshot)
        result = []
        for pin in pins:
            member = session.get(Member, (context.image_revision_id, pin["object_id"]))
            require(member is not None and member.project_id == context.project_id and member.kind == "source_document")
            document = session.get(Document, member.document_revision_id)
            require(document is not None and document.kind ==
                ("acceptance_criterion" if pin["kind"] == "acceptance" else "business_rule"))
            node = session.get(Node, (context.project_id, "member:" + context.image_revision_id + "/" + pin["object_id"]))
            require(node is not None)
            authority = None
            if pin["revision_id"] is not None:
                authority = session.get(Authority, (context.project_id, pin["kind"], pin["revision_id"]))
                require(authority is not None and all(getattr(authority, key) == expected for key, expected in {
                    "object_id": pin["object_id"], "image_revision_id": context.image_revision_id,
                    "image_artifact_hash": context.payload["image_artifact_hash"], "basis_digest": pin["basis_digest"],
                    "status": pin["status"], "artifact_hash": pin["artifact_hash"],
                    "document_revision_id": document.document_revision_id, "member_provenance_hash": node.content_hash,
                }.items()))
            result.append(ContextAuthorityDependency(context.project_id, context.context_id, pin["object_id"],
                pin["kind"], pin["basis_digest"], pin["status"], pin["revision_id"], pin["artifact_hash"],
                authority.content_hash if authority else None, context.image_revision_id, node.content_hash))
        require(tuple(item.object_id for item in result) == tuple(sorted({item.object_id for item in result})))
        return tuple(result)

    def record(self, session, context, pins, *, invocation_id, actor_id, recorded_at):
        dependencies = self.dependencies(session, context, pins)
        value = dependency_root(context.payload, context.content_hash, dependencies,
            invocation_id=invocation_id, actor_id=actor_id, recorded_at=recorded_at)
        prior = session.get(Root, (context.project_id, context.context_id))
        if prior is not None:
            return self.verify(session, context, pins=pins)
        session.add(Root(**value))
        session.flush()
        session.add_all(Dependency(**item.record_v1) for item in dependencies)
        session.flush()
        return value

    def verify(self, session, context, *, pins=None, reuse_snapshot=False):
        try:
            return self._verify(session, context, pins=pins, reuse_snapshot=reuse_snapshot)
        except ContextPackIntegrityError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise ContextPackIntegrityError("context authority dependencies failed verification") from exc

    def _verify(self, session, context, *, pins, reuse_snapshot):
        root = session.get(Root, (context.project_id, context.context_id))
        require(root is not None)
        self._registration_command(session, context, root)
        rows = session.scalars(select(Dependency).where(Dependency.project_id == context.project_id,
            Dependency.context_id == context.context_id).order_by(Dependency.object_id).limit(257)).all()
        require(len(rows) <= 256)
        saved = [columns(row) for row in rows]
        raw = [{key: value[key] for key in ("object_id", "kind", "basis_digest", "status", "revision_id", "artifact_hash")}
            for value in saved]
        if pins is not None:
            require(tuple(raw) == pins)
        dependencies = self.dependencies(session, context, raw, reuse_snapshot=reuse_snapshot)
        require(saved == [item.record_v1 for item in dependencies])
        expected = dependency_root(context.payload, context.content_hash, dependencies,
            invocation_id=root.registration_invocation_id, actor_id=root.registered_by, recorded_at=root.registered_at)
        require(columns(root) == expected)
        return expected

    def _registration_command(self, session, context, root):
        command = session.get(Command, root.registration_invocation_id)
        require(command is not None and command.input_payload.get("confirmed_by_user") is True)
        payload = {key: value for key, value in query_payload(command.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}}
        if root.registration_invocation_id == context.invocation_id:
            require(command.tool_id == COMPILE_CONTEXT_TOOL and root.registered_by == context.payload["actor_id"]
                and root.registered_at == context.payload["recorded_at"])
            request = ContextCompileInput.model_validate(payload)
            require(snapshot_digest(request.model_dump(mode="json")) == context.request_hash)
            # Original compile commands predate persisted confirmation actors.
            require(command.input_payload.get("confirmed_actor_id", root.registered_by) == root.registered_by)
        else:
            require(command.tool_id == REGISTER_CONTEXT_AUTHORITIES_TOOL
                and command.input_payload.get("confirmed_actor_id") == root.registered_by)
            request = ContextAuthorityRegistrationInput.model_validate(payload)
            require(request.project_id == context.project_id and request.context_id == context.context_id
                and request.artifact_hash == context.payload["artifact_hash"])
            target = session.get(Target, (context.project_id, context.context_id))
            require(target is not None and target.context_metadata_hash == context.content_hash
                and target.artifact_hash == request.artifact_hash and target.policy_revision == request.policy_revision)
        require(request.project_id == context.project_id)
        if command.conversation_id:
            conversation = session.get(Conversation, command.conversation_id)
            require(conversation is not None and conversation.project_id == context.project_id)
        if command.input_payload.get("agent_goal_id"):
            goal = session.get(Goal, command.input_payload["agent_goal_id"])
            require(goal is not None and goal.project_id == context.project_id
                and goal.conversation_id == command.conversation_id)
        # Historical facts survive command completion/failure and confirmation expiry.

    def project_event(self, session, event):
        if event.event_type not in {"system_image.context.compiled", "system_image.context.authorities_registered"}:
            return
        context = session.get(Context, event.entity_id)
        require(context is not None and event.patch.get("context_id") == context.context_id
            and event.patch.get("project_id") == context.project_id)
        value = self.verify(session, context)
        if event.event_type == "system_image.context.authorities_registered":
            expected = {key: value[key] for key in ("project_id", "context_id", "authority_count",
                "authority_pins_hash", "registration_invocation_id")}
            require(event.patch == expected and event.occurred_at == value["registered_at"])
        else:
            expected = {key: context.payload[key] for key in ("context_id", "project_id", "image_revision_id", "readiness")}
            require(event.patch == expected and event.occurred_at == context.payload["recorded_at"])
        require(event.entity_type == "context_pack" and event.mutation_kind == "append"
            and event.correlation_id == context.project_id)
