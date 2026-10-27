from dataclasses import asdict, dataclass
import json
from typing import Optional, Protocol

from ...domain.system_image.code_member_delta import (
    CODE_MEMBER_DELTA_KINDS, CODE_MEMBER_DELTA_POLICY, CodeMemberChange, compare_code_members,
)
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge, require_digest
from .source_access import SourceScopeAuthorizationPort


class FrozenCodeDeltaReadPort(Protocol):
    authorization: SourceScopeAuthorizationPort
    def verified_read_session(self, *, reuse=False): ...
    def frozen_snapshot(self, project_id, image_revision_id): ...


@dataclass(frozen=True)
class CodeMemberDeltaPage:
    project_id: str
    before_image_revision_id: str
    before_image_hash: str
    after_image_revision_id: str
    after_image_hash: str
    content_hash: str
    counts: dict[str, int]
    source_scope_changed: bool
    kind: Optional[str]
    items: tuple[CodeMemberChange, ...]
    total: int
    next_offset: Optional[int]
    schema: str = CODE_MEMBER_DELTA_POLICY
    comparison_scope: str = "registered_members_of_two_frozen_images"
    source_deletions_verified: bool = False
    rename_lineage_transferred: bool = False
    impact_complete: bool = False
    approval_transferred: bool = False
    execution_authorized: bool = False


class CodeMemberDeltaApplicationService:
    def __init__(self, images: FrozenCodeDeltaReadPort):
        self.images = images

    def read(self, project_id, before_image_revision_id, before_image_hash, after_image_revision_id,
             after_image_hash, *, kind=None, offset=0, limit=20):
        if (any(type(value) is not str or not 1 <= len(value) <= 128 for value in
                (project_id, before_image_revision_id, after_image_revision_id))
                or kind is not None and kind not in CODE_MEMBER_DELTA_KINDS
                or type(offset) is not int or not 0 <= offset <= 100000
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError("Invalid fixed code member delta page.")
        require_digest(before_image_hash)
        require_digest(after_image_hash)
        scope = self.images.authorization.scope(project_id)
        with self.images.verified_read_session(reuse=True):
            before = self.images.frozen_snapshot(project_id, before_image_revision_id)
            self.images.authorization.require_current(scope)
            after = self.images.frozen_snapshot(project_id, after_image_revision_id)
            if ((before[0].project_id, before[0].image_revision_id, before[0].artifact_hash) !=
                    (project_id, before_image_revision_id, before_image_hash)
                    or (after[0].project_id, after[0].image_revision_id, after[0].artifact_hash) !=
                    (project_id, after_image_revision_id, after_image_hash)):
                raise ImageRevisionIntegrityError("Code delta differs from the displayed image hashes.")
            delta = compare_code_members(*before, *after)
        changes = tuple(item for item in delta.changes if kind is None or item.kind == kind)
        if offset > len(changes):
            raise ValueError("Code delta offset is outside its fixed membership.")
        end = min(offset + limit, len(changes))
        result = CodeMemberDeltaPage(**{key: getattr(delta, key) for key in (
            "project_id", "before_image_revision_id", "before_image_hash", "after_image_revision_id",
            "after_image_hash", "content_hash", "counts", "source_scope_changed")},
            kind=kind, items=changes[offset:end], total=len(changes), next_offset=end if end < len(changes) else None)
        self.images.authorization.require_current(scope)
        if len(json.dumps(asdict(result), ensure_ascii=False, allow_nan=False).encode()) > 65536:
            raise ImageRevisionPageTooLarge("Code member delta page exceeds 64 KiB; request fewer members.")
        return result
