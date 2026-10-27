"""Replay frozen recall through application ports; compilation never invokes a model."""
from dataclasses import asdict, replace
from typing import Protocol

from ...domain.system_image.context_pack import ContextIndexChanged, ContextPackIntegrityError, ContextPublicationChanged
from ...domain.system_image.link_recall import RankedLinkCandidate
from ...domain.system_image.publication import PublicationChanged
from ...domain.system_image.retrieval_index import IndexConfigurationChanged, fuse_ranks
from ...domain.system_image.source_snapshots import snapshot_digest
from .screened_link_candidates import ScreenedLinkCandidateQueryApplicationService


INDEXED_RECALL_METHOD = "nasus.link-recall.indexed-reviewed.v3"


class ContextRetrievalReplayPort(Protocol):
    def replay_candidates(self, project_id, retrieval_id, publication_pin, *, historical=False): ...
    def require_replay_current(self, project_id, replay): ...


class IndexedContextRecall:
    def __init__(self, traces: ContextRetrievalReplayPort, screened: ScreenedLinkCandidateQueryApplicationService):
        self.traces, self.screened = traces, screened

    def load(self, request, publication_pin, *, historical=False):
        try:
            # Reuse only within this derivation; commit rechecks open a fresh one.
            unique = {ident: self.traces.replay_candidates(request.project_id, ident, publication_pin, historical=historical)
                for ident in sorted(set(request.retrieval_bindings.values()))}
        except IndexConfigurationChanged as exc:
            raise ContextIndexChanged("Context retrieval model changed; retrieve and preview again") from exc
        except PublicationChanged as exc:
            raise ContextPublicationChanged("Context publication changed during trace verification") from exc
        return {target: unique[ident] for target, ident in request.retrieval_bindings.items()}

    def require_current(self, project_id, replays):
        try:
            for ident in sorted({value["retrieval_id"] for value in replays.values()}):
                replay = next(value for value in replays.values() if value["retrieval_id"] == ident)
                self.traces.require_replay_current(project_id, replay)
        except IndexConfigurationChanged as exc:
            raise ContextIndexChanged("Context retrieval model changed before completion") from exc
        except PublicationChanged as exc:
            raise ContextPublicationChanged("Context publication changed before completion") from exc

    def read(self, request, target_object_id, relation, replay, *, pinned=None):
        corpus = self.screened.recall.collect(request.project_id, request.image_revision_id, target_object_id, relation=relation)
        if corpus.image_artifact_hash != request.image_artifact_hash:
            raise ContextPackIntegrityError("indexed context recall image mismatch")
        members = {member["object_id"]: member for member in corpus.payload["members"]}
        source_bindings = {(item["source_revision_id"], item["binding_id"]) for item in corpus.payload["source_members"]}
        indexed_ids = []
        for item in replay["candidates"]:
            document = item["document"]
            ident = document["object_id"]
            member = members.get(ident)
            if (not member or document["revision_id"] != (member.get("entity_revision_id") or member.get("document_revision_id"))
                    or document["source_revision_id"] != member["source_revision_id"] or document["kind"] != member["kind"]
                    or document["evidence_id"] not in member["evidence_ids"]
                    or (document["source_revision_id"], document["binding_id"]) not in source_bindings):
                raise ContextPackIntegrityError("indexed context candidate is not a frozen member")
            if ident in corpus.endpoints and ident not in indexed_ids:
                indexed_ids.append(ident)
        lexical = {item.object_id: item for item in corpus.ranked}
        indexed_set = set(indexed_ids)
        # Second-stage object RRF combines trace rank with AC-specific labels and
        # explicit references. Neither score nor query binding is a semantic claim.
        ranking = tuple(RankedLinkCandidate(ident, score,
            lexical[ident].matched_terms if ident in lexical else (),
            (("frozen_index_trace",) if ident in indexed_set else ()) + (lexical[ident].signals if ident in lexical else ()))
            for ident, score in fuse_ranks(indexed_ids, list(lexical), limit=len(corpus.endpoints)))
        corpus = replace(corpus, ranked=ranking)
        heads = None if pinned is None else tuple(tuple(pin) for pin in pinned["review_heads"])
        page = self.screened.screen_corpus(corpus, limit=request.candidate_limit, pinned_heads=heads)
        page = replace(page, method_version=INDEXED_RECALL_METHOD,
            limitations=("bounded_saved_trace_pool", "explicit_query_binding_not_relevance_proof", "structural_recall_not_run",
                "semantic_judgment_required", "source_specification_not_approved", "no_runtime_evidence"))
        receipt = {"method_version": INDEXED_RECALL_METHOD, "target_object_id": target_object_id, "relation": relation,
            "requested_limit": request.candidate_limit, "image_artifact_hash": request.image_artifact_hash,
            "trace_pin": {key: replay[key] for key in ("retrieval_id", "artifact_hash", "generation_id", "index_artifact_hash", "query_hash")},
            "model_digest": snapshot_digest(replay["model"]), "ranking_digest": snapshot_digest([asdict(item) for item in ranking]),
            "result_digest": snapshot_digest(asdict(page)), "review_scope_digest": page.review_scope_digest,
            "review_heads": [list(pin) for pin in sorted((item.subject_object_id, item.head_decision_id, item.head_decision_digest)
                for item in page.review_screening)],
            "truncated": page.truncated or replay["pool_may_be_truncated"],
            "fallback_used": replay["embedding_fallback_reason"] is not None}
        if pinned is not None and snapshot_digest(receipt) != snapshot_digest(pinned):
            raise ContextPackIntegrityError("indexed context recall differs from its immutable receipt")
        return receipt, page
