"""Append in the original fact transaction; reads verify and never heal history."""
from sqlalchemy import select

from ...application.quality_loop.test_design_results import TestDesignResultIntegrityError
from ...domain.system_image.automation_provenance import AutomationProvenance, AUTOMATION_PROVENANCE_POLICY
from ...domain.system_image.derivation_impact import DerivationNode
from ...domain.system_image.derivation_registry import DerivationRegistration, REGISTRY_POLICY
from ...domain.system_image.source_snapshots import snapshot_digest
from .automation_provenance_models import AutomationProvenanceRecord as Node, AutomationProvenanceEdgeRecord as Edge
from .automation_script_models import AutomationScriptRevisionRecord as Script, AutomationCallReservationRecord as Reservation, AutomationNativeReplyRecord as Reply
from .automation_script_review_models import AutomationScriptReviewRecord as Review
from .context_pack_models import ContextPackRecord as Context
from .derivation_registry_models import DerivationRegistryRecord as DesignNode, DerivationRegistryEdgeRecord as DesignEdge
from .test_design_scope_models import TestDesignScopeRecord as Scope
from .test_design_result_models import TestDesignResultRecord as Generation, TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage
from .test_design_mapping_models import TestDesignMappingRecord as Mapping


def _require(condition):
    if not condition:
        raise TestDesignResultIntegrityError("automation provenance failed integrity verification")


def _metadata(row, fields):
    _require(row is not None and type(row.payload) is dict and snapshot_digest(row.payload) == row.content_hash
        and all(row.payload.get(key) == getattr(row, key) for key in fields))
    return row.payload


class AutomationProvenanceProjectorV1:
    @staticmethod
    def _design_registration(project, context, invocation, kind, ident, digest, parents):
        node = DerivationNode(kind, ident, digest, tuple(sorted(parents)))
        return DerivationRegistration(project, context, invocation, node)

    @staticmethod
    def _design_pins(session, registrations):
        project, context = registrations[0].project_id, registrations[0].context_id
        keys = [value.node.key for value in registrations]
        _require(len(keys) == len(set(keys)) and all(value.project_id == project and value.context_id == context
            for value in registrations))
        stored = {row.node_key: row for row in session.scalars(select(DesignNode).where(
            DesignNode.project_id == project, DesignNode.node_key.in_(keys)))}
        edges = {}
        for edge in session.scalars(select(DesignEdge).where(DesignEdge.project_id == project,
                DesignEdge.node_key.in_(keys)).order_by(DesignEdge.parent_key)):
            _require(edge.context_id == context)
            edges.setdefault(edge.node_key, []).append(edge.parent_key)
        _require(set(stored) == set(keys))
        pins = []
        for value in registrations:
            node, row = value.node, stored[value.node.key]
            _require(all(getattr(row, key) == expected for key, expected in {
                "context_id": context, "kind": node.kind, "artifact_id": node.artifact_id,
                "artifact_hash": node.artifact_hash, "invocation_id": value.invocation_id,
                "content_hash": value.content_hash, "policy_revision": REGISTRY_POLICY}.items())
                and tuple(edges.get(node.key, ())) == node.dependencies)
            pins.append((node.key, node.artifact_hash, value.content_hash))
        return tuple(sorted(pins))

    def _script(self, session, row):
        meta = _metadata(row, ("project_id", "script_revision_id", "invocation_id", "call_id", "artifact_hash", "response_hash", "status"))
        reservation = session.get(Reservation, row.invocation_id)
        original = _metadata(reservation, ("project_id", "invocation_id", "call_id", "generation_id", "mapping_revision_id"))
        reply = session.get(Reply, row.invocation_id)
        response = _metadata(reply, ("project_id", "invocation_id", "call_id", "artifact_ref", "artifact_hash", "response_hash"))
        request = original["request"]
        _require(meta["status"] == "draft" and meta.get("execution_authorized") is False
            and row.project_id == reservation.project_id == reply.project_id == request["project_id"]
            and row.call_id == reservation.call_id == reply.call_id and row.response_hash == response["response_hash"]
            and meta["input_digest"] == request["input_digest"]
            and meta["mapping_revision_id"] == request["mapping_revision_id"] == reservation.mapping_revision_id
            and meta["mapping_artifact_hash"] == request["mapping_artifact_hash"])
        mapping = session.get(Mapping, reservation.mapping_revision_id)
        mapped = _metadata(mapping, ("project_id", "revision_id", "generation_id", "invocation_id", "previous_revision_id"))
        generation = session.get(Generation, reservation.generation_id)
        generated = _metadata(generation, ("project_id", "generation_id", "scope_revision_id", "invocation_id", "artifact_hash"))
        scope = session.get(Scope, generation.scope_revision_id)
        scoped = _metadata(scope, ("project_id", "revision_id", "context_id", "invocation_id", "previous_revision_id"))
        context = session.get(Context, scope.context_id)
        contextual = _metadata(context, ("project_id", "context_id", "image_revision_id", "invocation_id"))
        _require(row.project_id == mapping.project_id == generation.project_id == scope.project_id == context.project_id
            and mapping.generation_id == generation.generation_id
            and mapped["artifact_hash"] == request["mapping_artifact_hash"]
            and mapped["generation_artifact_hash"] == generation.artifact_hash
            and scoped["context_artifact_hash"] == contextual["artifact_hash"])
        project, context_id = row.project_id, context.context_id
        pin = lambda fact, kind, ident, digest, parents: self._design_registration(
            project, context_id, fact.invocation_id, kind, ident, digest, parents)
        scope_parents = ["context:" + context_id]
        if scope.previous_revision_id:
            scope_parents.append("scope:" + scope.previous_revision_id)
        mapping_parents = ["generation:" + generation.generation_id]
        if mapping.previous_revision_id:
            mapping_parents.append("mapping:" + mapping.previous_revision_id)
        parents = [pin(context, "context", context_id, contextual["artifact_hash"], ()),
            pin(scope, "scope", scope.revision_id, scoped["artifact_hash"], scope_parents),
            pin(generation, "generation", generation.generation_id, generated["artifact_hash"], ("scope:" + scope.revision_id,)),
            pin(mapping, "mapping", mapping.revision_id, mapped["artifact_hash"], mapping_parents)]
        coverage = session.get(Coverage, generation.generation_id)
        _metadata(coverage, ())
        _require(coverage.project_id == project)
        parents.append(self._design_registration(project, context_id, generation.invocation_id, "coverage",
            generation.generation_id, coverage.content_hash, ("generation:" + generation.generation_id,)))
        cases = request["case_ids"]
        _require(type(cases) is list and 1 <= len(cases) <= 512 and len(set(cases)) == len(cases))
        case_rows = session.scalars(select(Case).where(Case.generation_id == generation.generation_id,
            Case.case_id.in_(cases)).order_by(Case.case_id)).all()
        _require(len(case_rows) == len(cases))
        for case in case_rows:
            _metadata(case, ("case_id",))
            _require(case.project_id == project)
            parents.append(self._design_registration(project, context_id, generation.invocation_id, "case",
                generation.generation_id + "/" + case.case_id, case.content_hash, ("generation:" + generation.generation_id,)))
        origin = snapshot_digest({"reservation_hash": reservation.content_hash, "reply_hash": reply.content_hash,
            "call_id": row.call_id, "response_hash": row.response_hash})
        return AutomationProvenance(project, context_id, "script", row.script_revision_id, row.artifact_hash,
            row.invocation_id, row.content_hash, origin, self._design_pins(session, parents))

    def expected(self, session, row, *, script_anchor=None, predecessor=None):
        try:
            if isinstance(row, Script):
                return self._script(session, row)
            meta = _metadata(row, ("project_id", "revision_id", "script_revision_id", "invocation_id", "previous_revision_id", "sequence", "status"))
            script = session.get(Script, row.script_revision_id)
            anchor = script_anchor or self.verify(session, script)
            _require(script.project_id == row.project_id and script.artifact_hash == meta["script_artifact_hash"]
                and anchor.kind == "script" and anchor.artifact_id == row.script_revision_id
                and anchor.project_id == row.project_id)
            parents = [(anchor.key, anchor.artifact_hash, anchor.content_hash)]
            if row.previous_revision_id:
                _require(predecessor is not None and predecessor.kind == "script_review"
                    and predecessor.artifact_id == row.previous_revision_id
                    and predecessor.project_id == row.project_id and predecessor.context_id == anchor.context_id)
                parents.append((predecessor.key, predecessor.artifact_hash, predecessor.content_hash))
            return AutomationProvenance(row.project_id, anchor.context_id, "script_review", row.revision_id,
                meta["artifact_hash"], row.invocation_id, row.content_hash, anchor.content_hash, tuple(sorted(parents)))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if isinstance(exc, TestDesignResultIntegrityError):
                raise
            raise TestDesignResultIntegrityError("automation provenance failed integrity verification") from exc

    def _persist(self, session, value, script_id, review_id, *, write):
        stored = session.get(Node, (value.project_id, value.key))
        fields = {"project_id": value.project_id, "node_key": value.key, "context_id": value.context_id,
            "kind": value.kind, "artifact_id": value.artifact_id, "artifact_hash": value.artifact_hash,
            "invocation_id": value.invocation_id, "script_revision_id": script_id, "review_revision_id": review_id,
            "policy_revision": AUTOMATION_PROVENANCE_POLICY, "payload": value.payload_v1, "content_hash": value.content_hash}
        if stored is None:
            _require(write)
            session.add(Node(**fields))
            session.flush()
            for key, artifact_hash, registration_hash in value.parents:
                automation = key.partition(":")[0] in {"script", "script_review"}
                session.add(Edge(project_id=value.project_id, node_key=value.key, parent_key=key,
                    context_id=value.context_id, node_hash=value.content_hash, parent_hash=registration_hash,
                    parent_artifact_hash=artifact_hash, test_design_key=None if automation else key,
                    automation_key=key if automation else None))
            session.flush()
        else:
            _require(all(getattr(stored, key) == expected for key, expected in fields.items()))
        edges = session.scalars(select(Edge).where(Edge.project_id == value.project_id,
            Edge.node_key == value.key).order_by(Edge.parent_key)).all()
        _require(tuple((edge.parent_key, edge.parent_artifact_hash, edge.parent_hash) for edge in edges) == value.parents
            and all(edge.context_id == value.context_id and edge.node_hash == value.content_hash
                and (edge.automation_key, edge.test_design_key) == ((edge.parent_key, None)
                    if edge.parent_key.partition(":")[0] in {"script", "script_review"} else (None, edge.parent_key))
                for edge in edges))
        return value

    def verify(self, session, row):
        return self._persist(session, self.expected(session, row), row.script_revision_id, None, write=False)

    def record_script(self, session, row):
        session.flush()
        return self._persist(session, self.expected(session, row), row.script_revision_id, None, write=True)

    def record_review(self, session, row):
        session.flush()
        script = session.get(Script, row.script_revision_id)
        rows = session.scalars(select(Review).where(Review.project_id == row.project_id,
            Review.script_revision_id == row.script_revision_id, Review.sequence <= row.sequence)
            .order_by(Review.sequence).limit(1001)).all()
        _require(len(rows) <= 1000 and rows[-1].revision_id == row.revision_id)
        prior = self.reviews(session, script, rows[:-1])
        anchor = self.verify(session, script)
        _require(row.sequence == len(prior) + 1
            and row.previous_revision_id == (prior[-1].artifact_id if prior else None))
        value = self.expected(session, row, script_anchor=anchor, predecessor=prior[-1] if prior else None)
        return self._persist(session, value, script.script_revision_id, row.revision_id, write=True)

    def reviews(self, session, script, rows, *, write=False):
        anchor, previous = self.verify(session, script), None
        values = []
        for index, row in enumerate(rows):
            _require(row.project_id == script.project_id and row.script_revision_id == script.script_revision_id
                and row.sequence == index + 1 and row.previous_revision_id == (previous.artifact_id if previous else None)
                and row.status in {"reviewed", "withdrawn"}
                and (row.status != "withdrawn" or index > 0 and rows[index - 1].status == "reviewed"))
            value = self.expected(session, row, script_anchor=anchor, predecessor=previous)
            previous = self._persist(session, value, script.script_revision_id, row.revision_id, write=write)
            values.append(previous)
        return tuple(values)

    def project_event(self, session, event):
        if event.event_type == "quality.automation.draft_saved":
            row = session.get(Script, event.patch.get("script_revision_id"))
            _require(row is not None and event.entity_id == row.invocation_id and event.correlation_id == row.project_id
                and event.patch.get("artifact_hash") == row.artifact_hash
                and event.patch.get("input_digest") == row.payload.get("input_digest"))
            self.verify(session, row)
        elif event.event_type == "quality.automation.script_reviewed":
            row = session.get(Review, event.entity_id)
            _require(row is not None and event.correlation_id == row.project_id
                and event.patch == {key: getattr(row, key) for key in ("project_id", "script_revision_id", "revision_id", "status")})
            script = session.get(Script, row.script_revision_id)
            rows = session.scalars(select(Review).where(Review.project_id == row.project_id,
                Review.script_revision_id == row.script_revision_id, Review.sequence <= row.sequence)
                .order_by(Review.sequence).limit(1001)).all()
            _require(len(rows) <= 1000 and rows[-1].revision_id == row.revision_id)
            self.reviews(session, script, rows)

    def backfill(self, session):
        count = 0
        for script in session.scalars(select(Script).order_by(Script.project_id, Script.script_revision_id)
                .execution_options(yield_per=128)):
            self._persist(session, self.expected(session, script), script.script_revision_id, None, write=True)
            rows = session.scalars(select(Review).where(Review.project_id == script.project_id,
                Review.script_revision_id == script.script_revision_id).order_by(Review.sequence).limit(1001)).all()
            _require(len(rows) <= 1000)
            self.reviews(session, script, rows, write=True)
            count += 1 + len(rows)
        return count
