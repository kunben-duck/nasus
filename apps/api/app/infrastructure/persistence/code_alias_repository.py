from dataclasses import fields

from sqlalchemy import and_, or_, select

from ...domain.system_image.code_alias import CodeObjectAlias
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from .code_alias_models import CodeObjectAliasRecord as Alias
from .image_revision_models import ImageObjectMemberRecord as Member
from .unit_of_work import session_scope


def verified_code_alias(row):
    result = CodeObjectAlias(**{field.name: getattr(row, field.name) for field in fields(CodeObjectAlias)})
    if row.content_hash != result.content_hash or row.canonical_object_id != result.canonical_object_id:
        raise ImageRevisionIntegrityError("Code alias registration failed integrity verification.")
    return result


class CodeObjectAliasRepository:
    def find_in_image(self, project_id, image_revision_id, object_id, *, registration_hash=None):
        query = select(Alias, Member.object_id).join(Member, and_(
            Member.project_id == Alias.project_id, Member.binding_id == Alias.binding_id,
            Member.source_revision_id == Alias.source_revision_id,
            Member.entity_revision_id == Alias.entity_revision_id, Member.entity_id == Alias.entity_id,
        )).where(Member.project_id == project_id, Member.image_revision_id == image_revision_id,
            Member.kind == "code_entity", Alias.project_id == project_id,
            or_(Alias.legacy_object_id == object_id, Alias.canonical_object_id == object_id))
        if registration_hash is not None:
            query = query.where(Alias.content_hash == registration_hash)
        with session_scope() as session:
            rows = session.execute(query.order_by(Alias.content_hash, Member.object_id).limit(513)).all()
            if len(rows) > 512:
                raise ImageRevisionPageTooLarge("Code alias verification exceeds the complete query budget.")
            return tuple((verified_code_alias(alias), frozen_id) for alias, frozen_id in rows)
