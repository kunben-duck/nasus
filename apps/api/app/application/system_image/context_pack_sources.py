from dataclasses import asdict

from ...domain.system_image.context_pack import ContextPackIntegrityError, MandatoryContextTooLarge, budget_context
from ...domain.system_image.context_partition import PARTITION_POLICY, RULE_AUTHORITY_POLICY, PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY, MAX_CONSTRAINTS, partition_context
from ...domain.system_image.source_snapshots import snapshot_digest
from .image_query_models import ImageScreenedCandidatesInput, ImageScreenedCandidatesReceipt
from .context_publications import ContextPublicationPort, context_publication
from .indexed_context_recall import INDEXED_RECALL_METHOD


class TestDesignContextSources:
    """Use application ports; never inspect another bounded context's tables."""

    def __init__(self, images, authority, image_queries, *, rules=None, publications: ContextPublicationPort = None, indexed_recall=None):
        self.images, self.authority, self.image_queries = images, authority, image_queries
        self.rules = rules
        self.publications = publications
        self.indexed_recall = indexed_recall

    def require_image(self, request):
        header, image = self.images.frozen_snapshot(request.project_id, request.image_revision_id)
        if header.artifact_hash != request.image_artifact_hash:
            raise ContextPackIntegrityError("context image digest mismatch")
        return header, image

    def prepare(self, request, *, pinned=None):
        # Standalone calls are fresh; enclosing compilers share only immutable proof.
        with self.images.verified_read_session(reuse=True):
            return self._prepare(request, pinned=pinned)

    def _prepare(self, request, *, pinned=None):
        publication = (context_publication(self.publications, request, historical=pinned is not None)
            if request.policy_revision in {PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY} else None)
        header, image = self.require_image(request)
        if publication and (publication["manifest_id"] != header.manifest_id or publication["manifest_hash"] != header.manifest_hash):
            raise ContextPackIntegrityError("Context publication source manifest mismatch")
        members = {m["object_id"]: m for m in image["members"]}
        targets = sorted((o for o in image["objects"] if o["type"] in {"SourceAcceptanceCriterion", "SourceBusinessRule"}), key=lambda o: o["id"])
        indexed = request.policy_revision == INDEXED_CONTEXT_POLICY
        with_rule_authority = request.policy_revision in {RULE_AUTHORITY_POLICY, PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY}
        if with_rule_authority and self.rules is None:
            raise ContextPackIntegrityError("business rule authority port is required for this context policy")
        partitioned = request.policy_revision in {PARTITION_POLICY, RULE_AUTHORITY_POLICY, PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY}
        if len(targets) > (MAX_CONSTRAINTS if partitioned else 32):
            raise MandatoryContextTooLarge("Mandatory source constraint count exceeds this policy's limit; no top-k selection is allowed")
        if indexed:
            if self.indexed_recall is None:
                raise ContextPackIntegrityError("indexed context recall port is required")
            if set(request.retrieval_bindings) != {obj["id"] for obj in targets if obj["type"] == "SourceAcceptanceCriterion"}:
                raise ContextPackIntegrityError("Every source AC requires exactly one explicit retrieval binding")
            replays = self.indexed_recall.load(request, publication, historical=pinned is not None)
        constraints, authorities, retrievals, facts, evidence = [], [], [], [], []
        for obj in targets:
            ident, member = obj["id"], members[obj["id"]]
            if member["kind"] != "source_document":
                raise ContextPackIntegrityError("context requirement is not frozen source evidence")
            if obj["type"] == "SourceAcceptanceCriterion" or with_rule_authority:
                authority = self.authority if obj["type"] == "SourceAcceptanceCriterion" else self.rules
                if pinned is None:
                    view = authority.inspect(request.project_id, request.image_revision_id, request.image_artifact_hash, ident)
                    basis, head, current = view["basis"], view["head"], view["current"]
                else:
                    pin = next((p for p in pinned["authority_pins"] if p["object_id"] == ident), None)
                    if pin is None:
                        raise ContextPackIntegrityError("mandatory authority missing from context provenance")
                    # Verify historical pins without silently substituting today's authority.
                    view = authority.source_basis(request.project_id, request.image_revision_id, request.image_artifact_hash, ident)
                    current = authority.read(request.project_id, pin["revision_id"]) if pin["revision_id"] else None
                    basis, head = view, current["revision"] if current else None
                if head and (head["project_id"] != request.project_id or head["image_revision_id"] != request.image_revision_id
                             or head["image_artifact_hash"] != request.image_artifact_hash or head["object_id"] != ident
                             or head["basis_digest"] != snapshot_digest(basis)):
                    raise ContextPackIntegrityError("context authority belongs to a different source")
                pin = {"object_id": ident, "basis_digest": snapshot_digest(basis),
                    "revision_id": head["revision_id"] if head else None, "artifact_hash": head["artifact_hash"] if head else None,
                    "status": head["status"] if head else "unapproved"}
                authorities.append(pin)
                fields, evidence_ids = basis["fields"], basis["evidence_ids"]
                oracle = current["oracle"] if head and head["status"] == "approved" else None
            else:
                page = self.images.read_document(request.project_id, request.image_revision_id, ident, limit=90)
                if page["next_offset"] is not None or page["document"]["kind"] != "business_rule":
                    raise ContextPackIntegrityError("mandatory rule is incomplete")
                fields, evidence_ids = page["fields"], [e["evidence_id"] for e in page["evidence"]]
                pin, oracle = {"object_id": ident, "revision_id": None, "artifact_hash": None, "status": "unapproved"}, None
            if not evidence_ids or not fields:
                raise ContextPackIntegrityError("mandatory constraint has no evidence")
            evidence.extend((ident, eid) for eid in evidence_ids)
            constraints.append({"object_id": ident, "source_revision_id": member["source_revision_id"],
                "document_revision_id": member["document_revision_id"], "source_fields": fields, "evidence_ids": evidence_ids,
                "authority": pin, "oracle": oracle, "semantic_class": "expected" if oracle else "pending_confirmation"})
            if partitioned:
                constraints[-1]["kind"] = "acceptance_criterion" if obj["type"] == "SourceAcceptanceCriterion" else "business_rule"
            if obj["type"] != "SourceAcceptanceCriterion":
                continue
            for relation in ("implements", "asserts"):
                query = ImageScreenedCandidatesInput(project_id=request.project_id, image_revision_id=request.image_revision_id,
                    target_object_id=ident, relation=relation, limit=request.candidate_limit)
                if indexed:
                    raw = None if pinned is None else next((r for r in pinned["retrieval_runs"]
                        if r.get("target_object_id") == ident and r.get("relation") == relation), None)
                    if pinned is not None and raw is None:
                        raise ContextPackIntegrityError("indexed context retrieval receipt missing")
                    receipt, page = self.indexed_recall.read(request, ident, relation, replays[ident], pinned=raw)
                elif pinned is None:
                    receipt, page = self.image_queries.execute_with_observation(query)
                else:
                    raw = next((r for r in pinned["retrieval_runs"] if r["request"] == query.model_dump(mode="json")), None)
                    if raw is None:
                        raise ContextPackIntegrityError("context retrieval run missing")
                    receipt = ImageScreenedCandidatesReceipt.model_validate(raw)
                    page = self.image_queries.expand(receipt)
                retrievals.append(receipt if indexed else receipt.model_dump(mode="json"))
                for candidate in page.items:
                    endpoint = asdict(candidate.endpoint)
                    facts.append({"target_object_id": ident, "relation": relation, "endpoint": endpoint,
                        "review_status": candidate.review_status, "semantic_class": "retrieval_candidate_not_coverage"})
        base = {"schema_version": "nasus.context-pack.v1", "purpose": request.purpose, "project_id": request.project_id,
            "image_revision_id": request.image_revision_id, "image_artifact_hash": header.artifact_hash,
            "source_manifest_id": header.manifest_id, "source_manifest_hash": header.manifest_hash,
            "policy_version": request.policy_revision, "required_constraints": constraints,
            "readiness": {"status": "blocked" if not constraints or any(c["oracle"] is None for c in constraints) else "partial",
                "reason_codes": [*([] if constraints else ["missing_requirements"]),
                    *([] if all(c["oracle"] for c in constraints) else ["unapproved_mandatory_constraint"]),
                    "behavior_risk_contract_not_verified", *(["bounded_saved_trace_recall", "structural_recall_not_run"] if indexed else ["lexical_retrieval_only"]),
                    *([] if publication else ["image_not_published"]), "model_budget_not_bound"]},
            "use_policy": "draft_investigation_only_not_generation_or_execution_authorization",
            "retrieval": {"method": INDEXED_RECALL_METHOD if indexed else "nasus.link-recall.reviewed.v2",
                "fallback_used": any(r["fallback_used"] for r in retrievals) if indexed else True,
                "truncated": any(r["truncated"] for r in retrievals)}, "conflicts": {"status": "not_evaluated"}}
        if publication:
            base["publication_pin"] = publication
        compiler = partition_context if partitioned else budget_context
        context = compiler(base, facts, request.max_tokens)
        for fact in context["facts"]:
            evidence.extend((fact["endpoint"]["object_id"], eid) for eid in fact["endpoint"]["evidence_ids"])
        evidence = sorted(set(evidence))
        for start in range(0, len(evidence), 512):
            self.images.verify_evidence_selection(request.project_id, request.image_revision_id, tuple(evidence[start:start + 512]))
        provenance = {"authority_pins": authorities, "retrieval_runs": retrievals, "evidence_selections": evidence}
        if publication:
            provenance["publication_pin"] = context_publication(self.publications, request, historical=pinned is not None)
            if provenance["publication_pin"] != publication:
                raise ContextPackIntegrityError("Context publication changed during compilation")
        if indexed and pinned is None:
            self.indexed_recall.require_current(request.project_id, replays)
        if pinned is not None and snapshot_digest(provenance) != snapshot_digest(pinned):
            raise ContextPackIntegrityError("context provenance does not match fixed source and authority")
        return context, provenance
