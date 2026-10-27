from __future__ import annotations

from typing import Optional, Protocol, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from .structure_builds import StructureBuildCommit
    from .image_membership import ImageReviewCommit, ImageReviewFreezeInput
    from .semantic_membership import SemanticFreezeCommit, SemanticFreezeInput

from ...domain.system_image.image_revision import ImageObjectMember, ImageRevisionSummary
from ...domain.system_image.source_snapshots import CapturedSourceManifest
from .system_image_models import KnowledgeObject, ContextRelationship
from .evidence_queries import EvidencePage


class ImageEvidenceReadPort(Protocol):
    def read(self, project_id: str, evidence_id: str, *, source_revision_id: str,
             start_line: Optional[int] = None, max_lines: int = 100) -> EvidencePage: ...


class ImageCandidatePort(Protocol):
    def freeze(self, manifest: CapturedSourceManifest, baseline_id: str, *,
               objects: Sequence[KnowledgeObject], relationships: Sequence[ContextRelationship],
               invocation_id: Optional[str], recorded_at: str,
               build_commit: Optional[StructureBuildCommit] = None) -> ImageRevisionSummary: ...


class ImageArtifactPort(Protocol):
    def put(self, project_id: str, payload: dict) -> tuple[str, str]: ...
    def read(self, project_id: str, artifact_ref: str, artifact_hash: str) -> dict: ...


class ImageRevisionRepositoryPort(Protocol):
    def reviewed_invocation(self, request: ImageReviewFreezeInput | SemanticFreezeInput, invocation_id: str,
                            *, tool_id: str = "system_image.revisions.freeze_links") -> Optional[str]: ...
    def pin_evidence(self, project_id: str, members: Sequence[ImageObjectMember]) -> tuple[ImageObjectMember, ...]: ...
    def record(self, manifest: CapturedSourceManifest, baseline_id: str, *, artifact_ref: str, artifact_hash: str,
               members: Sequence[ImageObjectMember], relationship_count: int,
               invocation_id: Optional[str], recorded_at: str,
               build_commit: Optional[StructureBuildCommit] = None,
               review_commit: Optional[ImageReviewCommit | SemanticFreezeCommit] = None) -> ImageRevisionSummary: ...
    def get(self, project_id: str, image_revision_id: str) -> tuple[ImageRevisionSummary, str, frozenset[str]]: ...
    def list(self, project_id: str, *, binding_ids: frozenset[str], after_id: str, limit: int) -> list[ImageRevisionSummary]: ...
