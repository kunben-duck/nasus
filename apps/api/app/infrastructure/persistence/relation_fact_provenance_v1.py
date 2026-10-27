"""Register committed relation facts before membership selection, using 0072 hashes."""
from dataclasses import asdict

from sqlalchemy import func, select

from ...application.system_image.image_membership import pin_assertion
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.link_decisions import assertion_evidence_digest
from ...domain.system_image.relation_provenance import RelationProvenanceNode
from ...domain.system_image.source_snapshots import snapshot_digest
from .document_projection_models import SourceDocumentRevisionRecord as Document
from .image_revision_models import ImageRevisionRecord as Image, ImageObjectMemberRecord as Member
from .link_decision_models import LinkDecisionRecord as ReferenceDecision
from .link_decision_repository import LinkDecisionRepository
from .object_provenance_models import ObjectProvenanceNodeRecord as ObjectNode
from .object_provenance_projection_v1 import ObjectProvenanceProjectorV1, _columns
from .reference_link_models import ReferenceProposalRecord as Proposal, ReferenceProposalInvocationRecord as ProposalInvocation
from .reference_link_repository import ReferenceLinkRepository
from .relation_provenance_projection_v1 import RelationProvenanceProjectorV1
from .semantic_evaluation_models import SemanticEvaluationRecord as Evaluation, SemanticCallReservationRecord as Reservation
from .semantic_evaluation_repository import SemanticEvaluationRepository
from .semantic_review_models import SemanticAssertionRecord as Assertion, SemanticDecisionRecord as Decision
from .semantic_review_repository import SemanticReviewRepository


FACT_EVENTS = {
    "system_image.references.proposed": (Proposal, "proposal"),
    "system_image.link.reviewed": (ReferenceDecision, "reference_review"),
    "system_image.semantic.evaluated": (Evaluation, "evaluation"),
    "system_image.semantic.reviewed": (Decision, "semantic_review"),
}


def _require(condition):
    if not condition:
        raise ImageRevisionIntegrityError("Relation fact provenance failed integrity verification.")


class _FactGraph:
    def __init__(self, session, project):
        self.session, self.project, self.nodes, self.images = session, project, {}, {}

    def add(self, kind, ident, digest, metadata, parents=(), native=None):
        node = RelationProvenanceNode(self.project, kind, ident, digest, snapshot_digest(metadata),
            tuple(sorted(set(parents))), *(native or (None, None)))
        _require(node.key not in self.nodes or self.nodes[node.key] == node)
        self.nodes[node.key] = node
        return node.key

    def pin(self, key):
        prior = "object_pin:" + key
        if prior not in self.nodes:
            row = self.session.execute(_columns(ObjectNode).where(ObjectNode.project_id == self.project,
                ObjectNode.node_key == key)).one_or_none()
            _require(row is not None)
            self.add("object_pin", key, row.content_hash, {"node_key": key, "content_hash": row.content_hash},
                native=(key, row.content_hash))
        return prior

    def image(self, ident, digest):
        if ident not in self.images:
            row = self.session.get(Image, ident)
            _require(row is not None and row.project_id == self.project and row.artifact_hash == digest)
            ObjectProvenanceProjectorV1().image(self.session, row, write=False)
            RelationProvenanceProjectorV1().image(self.session, row, write=False, native_verified=True)
            self.images[ident] = row
        _require(self.images[ident].artifact_hash == digest)
        return self.pin("image_objects:" + ident)

    def endpoints(self, assertion, ident):
        result = []
        for object_id, evidence in ((assertion.subject_object_id, assertion.subject_evidence_ids),
                                   (assertion.object_id, assertion.object_evidence_ids)):
            result.append(self.pin("member:" + ident + "/" + object_id))
            result.extend(self.pin("evidence:" + eid) for eid in evidence)
        return result

    def proposal(self, row):
        _require(row is not None and row.project_id == self.project)
        saved = ReferenceLinkRepository._stored(self.session, row)
        root = self.image(row.image_revision_id, row.image_artifact_hash)
        key = self.add("reference_proposal", saved.proposal_id, saved.digest,
            {"origin_image_revision_id": row.image_revision_id, "proposal_digest": saved.digest}, (root,))
        for ident, assertion in zip(saved.assertion_ids, saved.proposal.assertions):
            self.add("reference_assertion", ident, snapshot_digest(asdict(assertion)),
                {"predicate": "references", "evidence_digest": assertion_evidence_digest(assertion)},
                (key, *self.endpoints(assertion, row.image_revision_id)))
        return saved

    def reference_review(self, row):
        _require(row is not None and row.project_id == self.project)
        saved = self.proposal(self.session.get(Proposal, row.proposal_id))
        history = LinkDecisionRepository._history(self.session, self.project, row.proposal_id,
            row.assertion_id, row.decision_id)
        _require(bool(history) and history[-1].decision_id == row.decision_id)
        previous = None
        for decision in history:
            pin_assertion(saved, decision.assertion_id, decision)
            previous = self.add("reference_decision", decision.decision_id, decision.digest,
                {"sequence": decision.sequence, "decision": decision.decision, "invocation_id": decision.invocation_id},
                ("reference_assertion:" + decision.assertion_id, *((previous,) if previous else ())))

    def evaluation(self, row):
        _require(row is not None and row.project_id == self.project)
        reservation = self.session.get(Reservation, row.invocation_id)
        _require(reservation is not None and reservation.project_id == self.project)
        frozen = SemanticEvaluationRepository._payload(reservation)
        request = frozen["request"]
        root = self.image(reservation.image_revision_id, request["expected_image_hash"])
        subjects = request["subject_object_ids"]
        _require(type(subjects) is list and 1 <= len(subjects) <= 30 and len(set(subjects)) == len(subjects)
            and request["relation"] in {"implements", "asserts"} and request["target_object_id"] not in subjects
            and frozen["preview"]["request"] == request)
        # Even an unreviewed evaluation pins the complete native image scope,
        # including negative/top-k inputs. Its exact selection is in the hashed reservation.
        for ident in (request["target_object_id"], *subjects):
            member = self.session.get(Member, (reservation.image_revision_id, ident))
            _require(member is not None and member.project_id == self.project)
            if ident != request["target_object_id"] and request["relation"] == "implements":
                _require(member.kind == "code_entity")
            else:
                document = self.session.get(Document, member.document_revision_id) if member.document_revision_id else None
                allowed = ({"acceptance_criterion", "business_rule"} if request["relation"] == "implements"
                    else {"acceptance_criterion"}) if ident == request["target_object_id"] else {"test_case"}
                _require(member.kind == "source_document" and document is not None
                    and document.project_id == self.project and document.kind in allowed)
        return self.add("semantic_evaluation", row.invocation_id, row.artifact_hash,
            {"reservation_hash": reservation.content_hash, "input_digest": request["input_digest"]}, (root,))

    def assertion(self, row):
        _require(row is not None and row.project_id == self.project)
        assertion = SemanticReviewRepository._assertion(row)
        SemanticReviewRepository._frozen(self.session, assertion)
        key = self.evaluation(self.session.get(Evaluation, assertion.evaluation_id))
        self.add("semantic_assertion", assertion.assertion_id, assertion.digest,
            {"predicate": assertion.predicate, "evidence_digest": assertion.evidence_digest,
             "oracle_digest": assertion.oracle_digest, "assessment": assertion.assessment},
            (key, *self.endpoints(assertion, assertion.image_revision_id)))

    def semantic_review(self, row):
        _require(row is not None and row.project_id == self.project)
        history = SemanticReviewRepository._history(self.session, self.project, row.claim_id, row.decision_id)
        _require(bool(history) and history[-1].decision_id == row.decision_id)
        previous = None
        for decision in history:
            self.assertion(self.session.get(Assertion, decision.assertion_id))
            previous = self.add("semantic_decision", decision.decision_id, decision.digest,
                {"sequence": decision.sequence, "decision": decision.decision, "invocation_id": decision.invocation_id},
                ("semantic_assertion:" + decision.assertion_id, *((previous,) if previous else ())))


class RelationFactProvenanceProjectorV1:
    def facts(self, session, method, rows, *, write):
        if not rows:
            return 0
        try:
            graph = _FactGraph(session, rows[0].project_id)
            for row in rows:
                _require(row.project_id == graph.project)
                getattr(graph, method)(row)
            _require(all(parent in graph.nodes for node in graph.nodes.values() for parent in node.parents))
            return RelationProvenanceProjectorV1()._compare(session, graph.nodes, write=write)
        except ImageRevisionIntegrityError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ImageRevisionIntegrityError("Relation fact provenance failed integrity verification.") from error

    def project_event(self, session, event):
        contract = FACT_EVENTS.get(event.event_type)
        if contract is None:
            return
        model, method = contract
        row = session.get(model, event.entity_id)
        _require(row is not None and event.patch.get("project_id") == row.project_id)
        if method in {"reference_review", "semantic_review"} and row.previous_decision_id:
            prior = session.get(model, row.previous_decision_id)
            _require(prior is not None)
            self.facts(session, method, (prior,), write=False)
        if method == "proposal":
            bindings = session.scalar(select(func.count()).select_from(ProposalInvocation).where(
                ProposalInvocation.project_id == row.project_id, ProposalInvocation.proposal_id == row.proposal_id))
            _require(bindings >= 1)
            if bindings > 1:
                self.facts(session, method, (row,), write=False)
        self.facts(session, method, (row,), write=True)

    def backfill(self, session):
        count = 0
        # Complete fact inventories, not just positively reviewed image members.
        for model, method, order in (
                (Proposal, "proposal", (Proposal.project_id, Proposal.proposal_id)),
                (Evaluation, "evaluation", (Evaluation.project_id, Evaluation.invocation_id)),
                (ReferenceDecision, "reference_review", (ReferenceDecision.project_id, ReferenceDecision.assertion_id, ReferenceDecision.sequence)),
                (Assertion, "assertion", (Assertion.project_id, Assertion.assertion_id)),
                (Decision, "semantic_review", (Decision.project_id, Decision.claim_id, Decision.sequence))):
            for row in session.scalars(select(model).order_by(*order).execution_options(yield_per=128)):
                count += self.facts(session, method, (row,), write=True)
        session.flush()
        return count
