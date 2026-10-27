"""Metadata-only relation graph in the caller's transaction; no permission grants."""
from dataclasses import asdict

from sqlalchemy import insert, select

from ...application.system_image.image_membership import pin_assertion
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageObjectMember, member_payload
from ...domain.system_image.relation_provenance import RELATION_PROVENANCE_POLICY, RelationProvenanceNode
from ...domain.system_image.semantic_membership import validate_semantic_members, semantic_membership_digest
from ...domain.system_image.image_membership import validate_assertion_members, reviewed_membership_digest
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.context_pack import ContextPackIntegrityError
from .context_pack_models import ContextPackRecord as Context
from .context_provenance_projection_v1 import ContextProvenanceProjectorV1
from .image_revision_models import ImageRevisionRecord as Image, ImageObjectMemberRecord as Member
from .image_membership_repository import ImageMembershipRepository
from .semantic_membership_repository import SemanticMembershipRepository
from .semantic_review_repository import SemanticReviewRepository
from .semantic_review_models import SemanticAssertionRecord as Assertion, SemanticDecisionRecord as Decision
from .semantic_evaluation_models import SemanticEvaluationRecord as Evaluation, SemanticCallReservationRecord as Reservation
from .semantic_evaluation_repository import SemanticEvaluationRepository
from .link_decision_repository import LinkDecisionRepository
from .reference_link_repository import ReferenceLinkRepository
from .reference_link_models import ReferenceProposalRecord as Proposal
from .object_provenance_models import ObjectProvenanceNodeRecord as ObjectNode
from .object_provenance_projection_v1 import ObjectProvenanceProjectorV1, _batches, _columns
from .relation_provenance_models import (
    RelationProvenanceNodeRecord as Node, RelationProvenanceEdgeRecord as Edge,
    ImageRelationProvenanceRecord as Root, ContextRelationProvenanceRecord as Anchor,
)


def _require(condition):
    if not condition:
        raise ImageRevisionIntegrityError("Image relation provenance failed integrity verification.")


class RelationProvenanceProjectorV1:
    def expected(self, session, image, *, native_verified=False):
        try:
            return self._expected(session, image, native_verified=native_verified)
        except ImageRevisionIntegrityError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ImageRevisionIntegrityError("Image relation provenance failed integrity verification.") from error

    def _expected(self, session, image, *, native_verified):
        _require(image is not None)
        project, nodes, audited = image.project_id, {}, set()
        if native_verified:
            audited.add(image.image_revision_id)

        def add(kind, ident, digest, metadata, parents=(), native=None):
            node = RelationProvenanceNode(project, kind, ident, digest, snapshot_digest(metadata),
                tuple(sorted(set(parents))), *(native or (None, None)))
            _require(node.key not in nodes or nodes[node.key] == node)
            nodes[node.key] = node
            return node.key

        def native_pin(key):
            prior = "object_pin:" + key
            if prior in nodes:
                return prior
            row = session.execute(_columns(ObjectNode).where(ObjectNode.project_id == project,
                ObjectNode.node_key == key)).one_or_none()
            _require(row is not None)
            return add("object_pin", key, row.content_hash,
                {"node_key": key, "content_hash": row.content_hash}, native=(key, row.content_hash))

        def origin(ident, expected_hash=None):
            row = session.get(Image, ident)
            _require(row is not None and row.project_id == project
                and (expected_hash is None or row.artifact_hash == expected_hash)
                and row.manifest_id == image.manifest_id and row.manifest_hash == image.manifest_hash
                and row.baseline_id == image.baseline_id)
            if ident not in audited:
                ObjectProvenanceProjectorV1().image(session, row, write=False)
                audited.add(ident)
            return native_pin("image_objects:" + ident)

        def endpoints(assertion, ident):
            result = []
            for object_id, evidence in ((assertion.subject_object_id, assertion.subject_evidence_ids),
                                       (assertion.object_id, assertion.object_evidence_ids)):
                result.append(native_pin("member:" + ident + "/" + object_id))
                result.extend(native_pin("evidence:" + eid) for eid in evidence)
            return result

        objects = session.execute(_columns(Member).where(Member.project_id == project,
            Member.image_revision_id == image.image_revision_id).order_by(Member.object_id)).all()
        object_values = [member_payload(ImageObjectMember(row.object_id, row.object_hash, row.kind, row.entity_id,
            row.entity_revision_id, row.source_revision_id, tuple(row.evidence_ids), row.document_revision_id)) for row in objects]
        references = ImageMembershipRepository.read(session, project, image.image_revision_id)
        semantics = SemanticMembershipRepository.read(session, project, image.image_revision_id)
        _require(len(references) + len(semantics) == image.assertion_count)
        validate_assertion_members(references, object_values)
        if semantics:
            validate_semantic_members(semantics, object_values, project)
        digest = (semantic_membership_digest(object_values, [asdict(v) for v in references], [asdict(v) for v in semantics])
            if image.policy_version == "nasus.image-candidate.v3" else
            reviewed_membership_digest(object_values, [asdict(v) for v in references])
            if image.policy_version == "nasus.image-candidate.v2" else snapshot_digest(object_values))
        _require(digest == image.membership_hash
            and (not semantics or image.policy_version == "nasus.image-candidate.v3")
            and (not references or image.policy_version in {"nasus.image-candidate.v2", "nasus.image-candidate.v3"}))

        # Validate immutable parent pins, not today's decision heads. Later
        # redecisions must not rewrite the dependencies of a historical image.
        ancestry, current = {}, image
        while current is not None:
            _require(len(ancestry) < 1000 and current.image_revision_id not in ancestry
                and (current.project_id, current.manifest_id, current.manifest_hash, current.baseline_id) ==
                    (project, image.manifest_id, image.manifest_hash, image.baseline_id))
            ancestry[current.image_revision_id] = current.artifact_hash
            if current.parent_revision_id is None:
                _require(current.parent_artifact_hash is None)
                break
            parent = session.get(Image, current.parent_revision_id)
            _require(parent is not None and parent.artifact_hash == current.parent_artifact_hash)
            current = parent

        root_pin = origin(image.image_revision_id, image.artifact_hash)
        member_keys, proposals = [], {}
        for member in references:
            _require(member.origin_image_revision_id in ancestry)
            ident = member.origin_image_revision_id
            origin_pin = origin(ident, ancestry[ident])
            if member.proposal_id not in proposals:
                row = session.get(Proposal, member.proposal_id)
                _require(row is not None and row.project_id == project and row.image_revision_id == ident)
                proposals[member.proposal_id] = ReferenceLinkRepository._stored(session, row)
            saved = proposals[member.proposal_id]
            _require(saved.digest == member.proposal_digest and member.assertion_id in saved.assertion_ids)
            assertion = saved.proposal.assertions[saved.assertion_ids.index(member.assertion_id)]
            proposal_key = add("reference_proposal", saved.proposal_id, saved.digest,
                {"origin_image_revision_id": ident, "proposal_digest": saved.digest}, (origin_pin,))
            assertion_key = add("reference_assertion", member.assertion_id, member.assertion_digest,
                {"predicate": "references", "evidence_digest": member.evidence_digest},
                (proposal_key, *endpoints(assertion, ident)))
            history = LinkDecisionRepository._history(session, project, member.proposal_id,
                member.assertion_id, member.decision_id)
            _require(bool(history) and pin_assertion(saved, member.assertion_id, history[-1]) == member)
            previous = None
            for decision in history:
                previous = add("reference_decision", decision.decision_id, decision.digest,
                    {"sequence": decision.sequence, "decision": decision.decision, "invocation_id": decision.invocation_id},
                    (assertion_key, *((previous,) if previous else ())))
            member_keys.append(add("relation_member", image.image_revision_id + "/reference/" + member.assertion_id,
                snapshot_digest(asdict(member)), {"decision_id": member.decision_id}, (previous,)))

        for member in semantics:
            assertion, selected = member.assertion, member.decision
            _require(ancestry.get(assertion.image_revision_id) == assertion.image_artifact_hash)
            origin_pin = origin(assertion.image_revision_id, assertion.image_artifact_hash)
            stored = session.get(Assertion, assertion.assertion_id)
            _require(stored is not None and SemanticReviewRepository._assertion(stored) == assertion)
            SemanticReviewRepository._frozen(session, assertion)
            evaluation = session.get(Evaluation, assertion.evaluation_id)
            reservation = session.get(Reservation, assertion.evaluation_id)
            frozen = SemanticEvaluationRepository._payload(reservation)
            evaluation_key = add("semantic_evaluation", assertion.evaluation_id, evaluation.artifact_hash,
                {"reservation_hash": reservation.content_hash, "input_digest": frozen["request"]["input_digest"]}, (origin_pin,))
            assertion_key = add("semantic_assertion", assertion.assertion_id, assertion.digest,
                {"predicate": assertion.predicate, "evidence_digest": assertion.evidence_digest,
                 "oracle_digest": assertion.oracle_digest, "assessment": assertion.assessment},
                (evaluation_key, *endpoints(assertion, assertion.image_revision_id)))
            history = SemanticReviewRepository._history(session, project, assertion.claim_id, selected.decision_id)
            _require(bool(history) and history[-1] == selected)
            previous = None
            for decision in history:
                # A claim can have different evaluations. Pin each predecessor's
                # own assertion, rather than borrowing the selected evaluation.
                prior_assertion = SemanticReviewRepository._assertion(session.get(Assertion, decision.assertion_id))
                SemanticReviewRepository._frozen(session, prior_assertion)
                prior_eval = session.get(Evaluation, prior_assertion.evaluation_id)
                prior_reservation = session.get(Reservation, prior_assertion.evaluation_id)
                prior_input = SemanticEvaluationRepository._payload(prior_reservation)
                prior_eval_key = add("semantic_evaluation", prior_assertion.evaluation_id, prior_eval.artifact_hash,
                    {"reservation_hash": prior_reservation.content_hash, "input_digest": prior_input["request"]["input_digest"]}, (origin_pin,))
                prior_key = add("semantic_assertion", prior_assertion.assertion_id, prior_assertion.digest,
                    {"predicate": prior_assertion.predicate, "evidence_digest": prior_assertion.evidence_digest,
                     "oracle_digest": prior_assertion.oracle_digest, "assessment": prior_assertion.assessment},
                    (prior_eval_key, *endpoints(prior_assertion, prior_assertion.image_revision_id)))
                previous = add("semantic_decision", decision.decision_id, decision.digest,
                    {"sequence": decision.sequence, "decision": decision.decision, "invocation_id": decision.invocation_id},
                    (prior_key, *((previous,) if previous else ())))
            _require(assertion_key in nodes)
            member_keys.append(add("relation_member", image.image_revision_id + "/semantic/" + assertion.claim_id,
                snapshot_digest(asdict(member)), {"decision_id": selected.decision_id}, (previous,)))
        add("image_relations", image.image_revision_id, image.artifact_hash,
            {"membership_hash": image.membership_hash, "policy_version": image.policy_version,
             "parent_revision_id": image.parent_revision_id, "parent_artifact_hash": image.parent_artifact_hash,
             "assertion_count": image.assertion_count}, (root_pin, *member_keys))
        _require(all(parent in nodes for node in nodes.values() for parent in node.parents))
        return nodes

    @staticmethod
    def _values(node):
        return {**{key: getattr(node, key) for key in ("project_id", "kind", "artifact_id", "artifact_hash",
            "metadata_hash", "object_node_key", "object_node_hash")}, "node_key": node.key,
            "content_hash": node.content_hash, "policy_revision": RELATION_PROVENANCE_POLICY}

    def _compare(self, session, nodes, *, write):
        project = next(iter(nodes.values())).project_id
        hashes = {key: value.content_hash for key, value in nodes.items()}
        existing, edges, missing = {}, {}, []
        for batch in _batches(nodes):
            existing.update({row.node_key: row._mapping for row in session.execute(_columns(Node).where(
                Node.project_id == project, Node.node_key.in_(batch)))})
            for row in session.execute(select(Edge.node_key, Edge.parent_key, Edge.node_hash, Edge.parent_hash).where(
                    Edge.project_id == project, Edge.node_key.in_(batch))):
                edges.setdefault(row.node_key, {})[row.parent_key] = (row.node_hash, row.parent_hash)
        for key, node in nodes.items():
            row = existing.get(key)
            if row is None:
                _require(write and key not in edges)
                missing.append(self._values(node))
            else:
                _require(all(row[field] == value for field, value in self._values(node).items())
                    and edges.get(key, {}) == {p: (hashes[key], hashes[p]) for p in node.parents})
        for batch in _batches(missing):
            session.execute(insert(Node), batch)
        new_edges = [{"project_id": project, "node_key": value["node_key"], "parent_key": parent,
            "node_hash": hashes[value["node_key"]], "parent_hash": hashes[parent]}
            for value in missing for parent in nodes[value["node_key"]].parents]
        for batch in _batches(new_edges):
            session.execute(insert(Edge), batch)
        return len(missing)

    def image(self, session, image, *, write, native_verified=False):
        nodes = self.expected(session, image, native_verified=native_verified)
        count = self._compare(session, nodes, write=write)
        node = nodes["image_relations:" + image.image_revision_id]
        expected = {"project_id": image.project_id, "image_revision_id": image.image_revision_id,
            "node_key": node.key, "content_hash": node.content_hash}
        prior = session.get(Root, (image.project_id, image.image_revision_id))
        if prior is None:
            _require(write)
            session.add(Root(**expected))
            session.flush()
        else:
            _require(all(getattr(prior, key) == value for key, value in expected.items()))
        return count

    def context(self, session, context, *, write):
        try:
            source = ContextProvenanceProjectorV1().verify(session, context)
            root = session.get(Root, (context.project_id, context.image_revision_id))
            _require(root is not None)
            expected = {"project_id": context.project_id, "context_id": context.context_id,
                "image_revision_id": context.image_revision_id, "image_node_key": root.node_key,
                "image_relations_hash": root.content_hash, "source_anchor_hash": source["content_hash"]}
            expected["content_hash"] = snapshot_digest({"policy_revision": RELATION_PROVENANCE_POLICY, **expected})
            prior = session.get(Anchor, (context.project_id, context.context_id))
            if prior is None:
                _require(write)
                session.add(Anchor(**expected))
                session.flush()
                return 1
            _require(all(getattr(prior, key) == value for key, value in expected.items()))
            return 0
        except ImageRevisionIntegrityError as error:
            raise ContextPackIntegrityError("Context relation provenance failed integrity verification.") from error

    def project_event(self, session, event):
        if event.event_type == "system_image.candidate.frozen":
            image = session.get(Image, event.entity_id)
            _require(image is not None and event.patch.get("project_id") == image.project_id)
            self.image(session, image, write=True, native_verified=True)
        elif event.event_type == "system_image.context.compiled":
            context = session.get(Context, event.entity_id)
            _require(context is not None and event.patch.get("project_id") == context.project_id)
            self.context(session, context, write=True)

    def backfill(self, session):
        count = 0
        for image in session.scalars(select(Image).order_by(Image.project_id, Image.image_revision_id)
                                     .execution_options(yield_per=128)):
            count += self.image(session, image, write=True)
        for context in session.scalars(select(Context).order_by(Context.project_id, Context.context_id)
                                       .execution_options(yield_per=128)):
            count += self.context(session, context, write=True)
        session.flush()
        return count
