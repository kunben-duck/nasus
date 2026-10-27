"""Frozen v1 backfill contract; future alias policies need a new projector."""
from dataclasses import asdict, dataclass

from sqlalchemy import select

from ...domain.system_image.code_alias import CodeObjectAlias, legacy_code_object_id
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_alias_models import CodeObjectAliasRecord as Alias
from .code_entity_models import CodeEntityProviderBindingRecord as Mapping, CodeEntityRevisionRecord as Revision, CodeEntityIdentityRecord as Identity
from .source_snapshot_models import SourceBindingRecord as Binding


@dataclass(frozen=True)
class _BindingIdentityV1:
    project_id: str
    binding_id: str
    kind: str
    legacy_source_id: str


class CodeAliasProjectorV1:
    @staticmethod
    def append(session, mapping, revision, identity, binding):
        if (mapping.project_id != revision.project_id or mapping.binding_id != revision.binding_id
                or mapping.source_revision_id != revision.source_revision_id
                or mapping.entity_revision_id != revision.entity_revision_id
                or identity.entity_id != revision.entity_id or identity.project_id != revision.project_id
                or identity.binding_id != revision.binding_id or binding.project_id != revision.project_id
                or binding.binding_id != revision.binding_id or binding.kind != "code"
                or snapshot_digest(identity.symbol_key) != identity.symbol_key_hash
                or snapshot_digest(revision.payload) != revision.payload_hash
                or not isinstance(revision.payload.get("symbol"), dict)
                or snapshot_digest(revision.payload["symbol"]) != identity.symbol_key_hash
                or snapshot_digest(mapping.provider_node_id) != mapping.provider_node_hash
                or mapping.legacy_object_id != legacy_code_object_id(mapping.project_id, binding.legacy_source_id, mapping.provider_node_id)):
            raise ImageRevisionIntegrityError("Code identity alias audit failed.")
        alias = CodeObjectAlias(mapping.project_id, mapping.binding_id, mapping.source_revision_id,
            revision.entity_id, revision.entity_revision_id, mapping.legacy_object_id,
            mapping.extraction_digest, mapping.provider_node_hash)
        values = {**asdict(alias), "canonical_object_id": alias.canonical_object_id, "content_hash": alias.content_hash}
        key = {name: values[name] for name in ("project_id", "binding_id", "source_revision_id", "extraction_digest", "provider_node_hash")}
        previous = session.get(Alias, key)
        if previous is not None:
            if any(getattr(previous, name) != value for name, value in values.items()):
                raise ImageRevisionIntegrityError("Code identity alias conflicts with its immutable registration.")
            return False
        session.add(Alias(**values))
        return True

    def backfill(self, session):
        # Later source fields do not exist when migration 0069 runs.
        rows = session.execute(select(Mapping, Revision, Identity,
            Binding.project_id.label("binding_project_id"), Binding.binding_id.label("source_binding_id"),
            Binding.kind.label("binding_kind"), Binding.legacy_source_id.label("binding_legacy_source_id"))
            .outerjoin(Revision, Revision.entity_revision_id == Mapping.entity_revision_id)
            .outerjoin(Identity, Identity.entity_id == Revision.entity_id)
            .outerjoin(Binding, Binding.binding_id == Mapping.binding_id)
            .order_by(Mapping.project_id, Mapping.binding_id, Mapping.source_revision_id,
                      Mapping.extraction_digest, Mapping.provider_node_hash).execution_options(yield_per=256))
        appended = 0
        for mapping, revision, identity, project_id, binding_id, kind, legacy_source_id in rows:
            if any(item is None for item in (revision, identity, project_id, binding_id, kind, legacy_source_id)):
                raise ImageRevisionIntegrityError("Code identity alias has missing provenance.")
            binding = _BindingIdentityV1(project_id, binding_id, kind, legacy_source_id)
            appended += self.append(session, mapping, revision, identity, binding)
        session.flush()
        return appended
