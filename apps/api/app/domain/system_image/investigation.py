"""Evidence-driven, bounded revisions of a fixed-input investigation."""
from dataclasses import asdict, dataclass

from .build_plan import BuildPlanGap, InvestigationPlan
from .image_revision import require_digest
from .source_snapshots import snapshot_digest


INVESTIGATION_POLICY = "nasus.image-investigation-revision.v1"
REFERENCE_INVESTIGATION_POLICY = "nasus.image-investigation-revision.v2"
INVESTIGATION_POLICIES = frozenset({INVESTIGATION_POLICY, REFERENCE_INVESTIGATION_POLICY})


@dataclass(frozen=True)
class InvestigationEvidence:
    object_id: str
    evidence_id: str
    source_revision_id: str
    result_hash: str

    def __post_init__(self):
        if any(type(value) is not str or not 1 <= len(value) <= 256 for value in (
                self.object_id, self.evidence_id, self.source_revision_id)):
            raise ValueError("Invalid investigation evidence pin.")
        require_digest(self.result_hash)


@dataclass(frozen=True)
class InvestigationTask:
    work_item_id: str
    question: str
    reason: str
    gap_code: str
    tool_id: str
    input_payload: dict
    acceptance_conditions: tuple[str, ...]
    max_attempts: int = 1
    max_model_calls: int = 0
    authorization_state: str = "not_granted"


@dataclass(frozen=True)
class InvestigationReview:
    image_revision_id: str
    image_artifact_hash: str
    evidence_signature: str
    verified_evidence: tuple[InvestigationEvidence, ...]
    work_items: tuple[InvestigationTask, ...]
    gaps: tuple[BuildPlanGap, ...]
    inventory: dict
    readiness: dict
    observed_evidence_keys: tuple[str, ...]
    observed_image_hashes: tuple[str, ...]
    no_progress_rounds: int
    consumed_review_calls: int
    state: str
    policy_version: str = INVESTIGATION_POLICY
    publication_allowed: bool = False

    @property
    def digest(self):
        return snapshot_digest(asdict(self))


def propose_investigation(plan: InvestigationPlan, image_revision_id: str, payload: dict,
                          evidence: tuple[InvestigationEvidence, ...], *, previous=None,
                          policy_version=INVESTIGATION_POLICY) -> InvestigationReview:
    """Select useful next questions, without upgrading observations to oracles."""
    if policy_version not in INVESTIGATION_POLICIES or (previous and previous.policy_version != policy_version):
        raise ValueError("Investigation policy cannot change within an existing revision chain.")
    artifact_hash = snapshot_digest(payload)
    require_digest(artifact_hash)
    if (payload["project_id"] != plan.intent.project_id or payload["manifest_id"] != plan.intent.source_manifest_id
            or payload["manifest_hash"] != plan.intent.source_manifest_hash):
        raise ValueError("Investigation candidate differs from the fixed plan inputs.")
    members = payload["members"]
    by_id = {item["object_id"]: item for item in members}
    if len(by_id) != len(members) or len(evidence) > 8 or len({(e.object_id, e.evidence_id) for e in evidence}) != len(evidence):
        raise ValueError("Invalid investigation evidence membership.")
    for pin in evidence:
        member = by_id.get(pin.object_id)
        if (not member or pin.evidence_id not in member["evidence_ids"]
                or pin.source_revision_id != member["source_revision_id"]):
            raise ValueError("Investigation evidence is outside the fixed image.")
    evidence = tuple(sorted(evidence, key=lambda item: (item.object_id, item.evidence_id)))
    code = [item for item in members if item["kind"] == "code_entity"]
    documents = [item for item in members if item["kind"] == "source_document"]
    unpinned = sum(not item["evidence_ids"] for item in code)
    legacy = sum(item["kind"] == "legacy_observation" for item in members)
    signature = snapshot_digest({"image_artifact_hash": artifact_hash,
        "verified_evidence": [asdict(item) for item in evidence]})
    old_keys = set(previous.observed_evidence_keys) if previous else set()
    old_images = set(previous.observed_image_hashes) if previous else set()
    keys = {snapshot_digest(asdict(item)) for item in evidence}
    progressed = artifact_hash not in old_images or bool(keys - old_keys)
    rounds = previous.no_progress_rounds + 1 if previous and not progressed else 0
    consumed = previous.consumed_review_calls + 1 if previous else 1
    remaining = max(0, plan.intent.budget.max_tool_calls - consumed)
    gaps = []
    tasks = []

    def gap(code, blocks, reason, action):
        gaps.append(BuildPlanGap(code, blocks, reason, action))

    def read_task(ident, question, reason, code, tool_id, body, conditions):
        tasks.append(InvestigationTask(ident, question, reason, code, tool_id,
            {"project_id": plan.intent.project_id, "image_revision_id": image_revision_id, **body}, conditions))

    if unpinned or legacy:
        gap("structural_evidence_incomplete", "structure", "Some objects have no frozen source evidence or are legacy observations.",
            "Repair missing source evidence; do not infer structural completeness from object counts.")
        read_task("inspect-membership", "Which structural objects lack source evidence?",
            "Inspect the immutable membership before proposing a repair.", "structural_evidence_incomplete",
            "query.system_image.revisions.read", {"section": "members", "offset": 0, "limit": 25},
            ("exact image artifact verified", "missing evidence retained as a gap", "all further pages explicitly accounted for"))
    if len(evidence) < sum(len(item["evidence_ids"]) for item in code + documents):
        gap("evidence_inspection_partial", "behavior", "The bounded evidence sample is not exhaustive source or behavior coverage.",
            "Inspect additional evidence under a separate bounded authorization.")
        read_task("inspect-further-members", "Which further source evidence needs investigation?",
            "Bounded sampling cannot establish full behavior coverage.", "evidence_inspection_partial",
            "query.system_image.revisions.read", {"section": "members", "offset": min(8, len(members)), "limit": 25},
            ("exact image artifact verified", "new evidence identities explicitly selected", "sample not reported as complete coverage"))
    selected_documents = {source.source_type for source in plan.intent.sources if source.status == "captured"}
    for kind, dimension in (("us_doc", "business_acceptance"), ("test_asset", "test_reuse")):
        if kind not in selected_documents:
            gap(f"{kind}_unavailable", dimension, "This optional source is absent from the fixed manifest.",
                "Supply this source in a separately captured and reviewed manifest; structural delivery may continue.")
    if documents:
        gap("document_semantics_unreviewed", "traceability", "Source document membership is not approved business semantics or code/test linkage.",
            "Inspect field evidence before proposing and independently reviewing semantic relationships.")
        for item in sorted(documents, key=lambda item: item["object_id"])[:4]:
            read_task(f"document-{len(tasks)}", "Which requirements or historical test fields are explicitly supported?",
                "Preserve observed, expected and hypothesized claims separately.", "document_semantics_unreviewed",
                "query.system_image.revisions.document", {"object_id": item["object_id"], "offset": 0, "limit": 20},
                ("field-level evidence verified", "document pagination explicit", "no approval inferred from a document mention"))
        if len(documents) > 4:
            gap("document_investigation_truncated", "traceability", "More documents exist than this bounded task proposal includes.",
                "Continue from explicit frozen document identities in another bounded revision.")
    if policy_version == REFERENCE_INVESTIGATION_POLICY and {"us_doc", "test_asset"}.issubset(selected_documents):
        if documents:
            gap("explicit_reference_candidates_unreviewed", "traceability",
                "Explicit requirement references have not been proposed and independently inspected for this image.",
                "Propose fixed-evidence references and inspect all candidates and gaps; this does not prove coverage.")
            read_task("propose-explicit-references", "Which historical tests explicitly reference a requirement?",
                "Derive references from frozen document fields, without models, semantic approval or execution.",
                "explicit_reference_candidates_unreviewed", "system_image.links.propose_references", {},
                ("both endpoint revisions and field evidence fixed", "all candidates and gaps independently inspected",
                 "references not reported as implements, asserts or verified coverage"))
        else:
            gap("reference_source_projection_missing", "traceability",
                "Captured document sources have no frozen document members for reference matching.",
                "Inspect extraction gaps; do not invent document identities or reference relationships.")
    # Even reviewed semantic membership does not itself carry an approved AC/oracle.
    gap("business_oracle_authority_unresolved", "business_acceptance", "Code and knowledge assertions do not prove approved acceptance criteria.",
        "Resolve version-applicable, independently approved AC and observable oracle through the acceptance use case.")
    gap("runtime_evidence_unresolved", "execution", "No controlled target execution has been established by this investigation.",
        "Bind a reviewed RunPlan and real execution evidence; never count planned tests as executed coverage.")
    gap("publication_review_required", "publication", "Investigation delivery is not an official publication decision.",
        "Request independent revision governance after the remaining evidence gaps are reviewed.")
    if len(tasks) > remaining:
        gap("investigation_budget_insufficient", "investigation", "Proposed follow-up work exceeds the remaining proposal ceiling.",
            "Request a separately approved budget; this revision cannot expand the original ceiling.")
        tasks = tasks[:remaining]
    state = "paused_no_progress" if rounds >= 3 else "paused_budget" if not remaining else "needs_input" if not tasks else "investigation_ready"
    if state.startswith("paused_"):
        tasks = []
    readiness = {name: {"state": "unresolved", "coverage": None} for name in (
        "structure", "behavior", "traceability", "automation", "execution")}
    readiness["structure"]["state"] = "evidence_gaps" if unpinned or legacy else "membership_verified_not_coverage"
    return InvestigationReview(image_revision_id, artifact_hash, signature, evidence, tuple(tasks), tuple(gaps),
        {"code_members": len(code), "document_members": len(documents), "legacy_members": legacy,
         "code_members_without_evidence": unpinned, "verified_evidence_sample": len(evidence)},
        readiness, tuple(sorted(old_keys | keys)), tuple(sorted(old_images | {artifact_hash})), rounds, consumed, state,
        policy_version=policy_version)


def decode_investigation(payload):
    try:
        review = InvestigationReview(**{**payload,
            "observed_evidence_keys": tuple(payload["observed_evidence_keys"]),
            "observed_image_hashes": tuple(payload["observed_image_hashes"]),
            "verified_evidence": tuple(InvestigationEvidence(**item) for item in payload["verified_evidence"]),
            "work_items": tuple(InvestigationTask(**{**item, "acceptance_conditions": tuple(item["acceptance_conditions"])})
                                for item in payload["work_items"]),
            "gaps": tuple(BuildPlanGap(**item) for item in payload["gaps"])})
        if review.policy_version not in INVESTIGATION_POLICIES or review.publication_allowed is not False or review.digest != snapshot_digest(payload):
            raise ValueError("Invalid investigation revision.")
        return review
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid investigation revision.") from exc
