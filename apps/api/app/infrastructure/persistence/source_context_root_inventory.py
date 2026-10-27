"""One SQL snapshot over project-scoped immutable source/image/context FKs."""
from sqlalchemy import func, select, true
from sqlalchemy.orm import aliased

from ...domain.system_image.source_context_roots import SourceContextRoot, SourceContextRootInventory
from ...domain.system_image.derivation_impact import DerivationImpactIntegrityError
from ...domain.system_image.derivation_registry import REGISTRY_POLICY
from .context_pack_models import ContextPackRecord as Context
from .context_pack_repository import ContextPackRepository
from .image_revision_models import ImageRevisionRecord as Image
from .source_snapshot_models import SourceManifestMemberRecord as Member
from .derivation_registry_models import (
    ContextQueryScopeRecord as QueryScope, ContextQuerySourceRecord as QuerySource, DerivationRegistryRecord as Node,
)
from .unit_of_work import session_scope


class SourceContextRootInventoryRepository:
    def list(self, project_id, binding_id, source_revision_id, *, binding_ids, after_id, limit):
        hidden = aliased(Member)
        inaccessible_source = select(hidden.manifest_id).where(hidden.project_id == Image.project_id,
            hidden.manifest_id == Image.manifest_id, hidden.binding_id.not_in(binding_ids)).exists()
        roots = select(Context.context_id, Context.image_revision_id, Context.invocation_id,
            Context.project_id, Context.content_hash, Context.payload, Image.manifest_id,
            Image.artifact_hash.label("image_artifact_hash"))
        roots = roots.join(Image, (Context.project_id == Image.project_id) & (Context.image_revision_id == Image.image_revision_id))
        roots = roots.join(Member, (Image.project_id == Member.project_id) & (Image.manifest_id == Member.manifest_id))
        canonical = roots.where(Context.project_id == project_id, Member.binding_id == binding_id,
            Member.source_revision_id == source_revision_id, Member.status == "captured",
            ~inaccessible_source).cte("canonical_source_context_roots")
        roots = select(canonical).join(QueryScope, (QueryScope.project_id == canonical.c.project_id)
            & (QueryScope.context_id == canonical.c.context_id)
            & (QueryScope.image_revision_id == canonical.c.image_revision_id)
            & (QueryScope.image_artifact_hash == canonical.c.image_artifact_hash)
            & (QueryScope.manifest_id == canonical.c.manifest_id)
            & (QueryScope.input_digest == canonical.c.payload["input_digest"].as_string())).join(Node,
                (Node.project_id == canonical.c.project_id) & (Node.context_id == canonical.c.context_id)
                & (Node.kind == "context") & (Node.artifact_id == canonical.c.context_id)
                & (Node.artifact_hash == canonical.c.payload["artifact_hash"].as_string())
                & (Node.invocation_id == canonical.c.invocation_id) & (Node.policy_revision == REGISTRY_POLICY)).join(QuerySource,
                (QuerySource.project_id == QueryScope.project_id) & (QuerySource.context_id == QueryScope.context_id)
                & (QuerySource.manifest_id == QueryScope.manifest_id)).where(QueryScope.policy_revision == REGISTRY_POLICY,
                    QuerySource.binding_id == binding_id, QuerySource.source_revision_id == source_revision_id,
                    QuerySource.status == "captured").cte("indexed_source_context_roots")
        total = select(func.count().label("total"),
            select(func.count()).select_from(canonical).scalar_subquery().label("canonical_total")).select_from(roots).subquery()
        page = select(roots).where(roots.c.context_id > after_id).order_by(roots.c.context_id).limit(limit + 1).subquery()
        # The left join also returns the total on an empty page. Both count and
        # page are from the same statement, never two racing READ COMMITTED reads.
        query = select(total.c.total, total.c.canonical_total, page).select_from(total.outerjoin(page, true())).order_by(page.c.context_id)
        with session_scope() as session:
            rows = session.execute(query).all()
            count = rows[0].total
            if count != rows[0].canonical_total:
                raise DerivationImpactIntegrityError("source context query index is incomplete")
            selected = [row for row in rows if row.context_id is not None]
            items = []
            for row in selected[:limit]:
                metadata = ContextPackRepository._metadata(row)
                items.append(SourceContextRoot(row.context_id, metadata.get("artifact_hash"),
                    row.image_revision_id, row.image_artifact_hash))
        return SourceContextRootInventory(tuple(items), count,
            items[-1].context_id if len(selected) > limit else None).validate(after_id, limit)
