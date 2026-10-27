"""One-statement quality-domain inventory; all artifact verification stays in use cases."""
from sqlalchemy import func, literal, select, true, union_all

from ...domain.system_image.derivation_impact import DerivationImpactIntegrityError, DerivationImpactTooLarge, MAX_DEPENDENCIES
from ...domain.system_image.derivation_registry import REGISTRY_POLICY
from .derivation_registry_models import DerivationRegistryRecord as Node
from .test_design_scope_models import TestDesignScopeRecord as Scope
from .test_design_result_models import TestDesignResultRecord as Generation
from .test_design_mapping_models import TestDesignMappingRecord as Mapping
from .unit_of_work import session_scope


class QualityContextDependencyInventory:
    def list(self, project_id, context_id):
        scopes = select(literal("scope").label("kind"), Scope.revision_id.label("artifact_id"),
            Scope.payload["artifact_hash"].as_string().label("artifact_hash")).where(
            Scope.project_id == project_id, Scope.context_id == context_id)
        generations = select(literal("generation"), Generation.generation_id, Generation.artifact_hash).join(Scope,
            (Generation.scope_revision_id == Scope.revision_id) & (Generation.project_id == Scope.project_id)).where(
            Scope.project_id == project_id, Scope.context_id == context_id)
        mappings = select(literal("mapping"), Mapping.revision_id, Mapping.payload["artifact_hash"].as_string()).join(Generation,
            (Mapping.generation_id == Generation.generation_id) & (Mapping.project_id == Generation.project_id)).join(Scope,
            (Generation.scope_revision_id == Scope.revision_id) & (Generation.project_id == Scope.project_id)).where(
            Scope.project_id == project_id, Scope.context_id == context_id)
        canonical = union_all(scopes, generations, mappings).cte("canonical_context_dependencies")
        inventory = select(Node.kind, Node.artifact_id).join(canonical,
            (Node.kind == canonical.c.kind) & (Node.artifact_id == canonical.c.artifact_id)
            & (Node.artifact_hash == canonical.c.artifact_hash)).where(Node.project_id == project_id,
                Node.context_id == context_id, Node.policy_revision == REGISTRY_POLICY).cte("indexed_context_dependencies")
        canonical_count = select(func.count()).select_from(canonical).scalar_subquery()
        registered_count = select(func.count()).select_from(Node).where(Node.project_id == project_id,
            Node.context_id == context_id, Node.kind.in_(("scope", "generation", "mapping"))).scalar_subquery()
        counts = select(func.count().label("total"), canonical_count.label("canonical_total"),
            registered_count.label("registered_total")).select_from(inventory).subquery()
        page = select(inventory).order_by(inventory.c.kind, inventory.c.artifact_id).limit(MAX_DEPENDENCIES).subquery()
        with session_scope() as session:
            rows = session.execute(select(counts, page).select_from(counts.outerjoin(page, true()))
                .order_by(page.c.kind, page.c.artifact_id)).all()
        if rows[0].total != rows[0].canonical_total or rows[0].total != rows[0].registered_total:
            raise DerivationImpactIntegrityError("quality derivation registry is incomplete")
        if rows[0].total >= MAX_DEPENDENCIES:
            raise DerivationImpactTooLarge("quality dependency inventory exceeds 127 artifacts")
        return tuple((row.kind, row.artifact_id) for row in rows if row.kind is not None)
