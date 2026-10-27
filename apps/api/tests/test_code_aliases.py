from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.code_alias import (
    AmbiguousCodeObjectAlias, CodeObjectAlias, canonical_code_object_id, legacy_code_object_id,
)
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.application.system_image.code_aliases import FrozenCodeObjectIdentity
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.system_image.image_query_models import ImageCodeIdentityInput, ImageCodeIdentityReceipt


ENTITY = "f98509ad-b5e1-4aa0-ae70-1d33cfb5fda1"


def alias(**changes):
    original = CodeObjectAlias("project", "binding", "source-v1", ENTITY, "entity-v1",
        legacy_code_object_id("project", "source", "provider-node"), "sha256:" + "a" * 64, "sha256:" + "b" * 64)
    return replace(original, **changes)


@pytest.mark.parametrize("entity_id", ["provider-node", "", None, ENTITY.upper(), " " + ENTITY])
def test_canonical_id_cannot_be_a_provider_id_or_unnormalized_uuid(entity_id):
    with pytest.raises(ImageRevisionIntegrityError):
        canonical_code_object_id(entity_id)


def test_alias_is_source_revision_pinned_and_metadata_only():
    first = alias()
    assert first.canonical_object_id == "CODE-" + ENTITY
    assert alias(source_revision_id="source-v2").canonical_object_id == first.canonical_object_id
    assert alias(source_revision_id="source-v2").content_hash != first.content_hash
    assert "provider-node" not in str(asdict(first))
    assert canonical_code_object_id(ENTITY) not in first.legacy_object_id


@pytest.mark.parametrize("changes", [{"project_id": ""}, {"legacy_object_id": "CTX-wrong"},
    {"extraction_digest": "not-a-digest"}, {"provider_node_hash": None}, {"policy_version": "new-policy"}])
def test_alias_scope_and_hash_contract_is_strict(changes):
    with pytest.raises(ImageRevisionIntegrityError):
        alias(**changes)


def application(candidates):
    first = candidates[0][0]
    calls = []
    auth = SimpleNamespace(scope=lambda _: "authorized-scope", require_current=lambda _: calls.append("authorize"))
    application = ImageRevisionQueryApplicationService(None, None, auth,
        code_aliases=SimpleNamespace(find_in_image=lambda *_, **__: candidates))
    members, objects = [], []
    for item, ident in candidates:
        reference = {key: getattr(item, key) for key in ("entity_id", "entity_revision_id", "source_revision_id")}
        members.append({"object_id": ident, "kind": "code_entity", **reference})
        objects.append({"id": ident, "code_reference": reference})
    payload = {"members": members, "objects": objects,
        "source_members": [{"binding_id": first.binding_id, "source_revision_id": first.source_revision_id}]}
    application._verified_payload = lambda *_: (SimpleNamespace(artifact_hash="sha256:" + "c" * 64), payload)
    return application, payload, calls


def test_canonical_and_legacy_requests_resolve_one_fixed_member():
    first = alias()
    app, _, calls = application(((first, first.canonical_object_id),))
    old = app.resolve_code_object("project", "image", first.legacy_object_id)
    current = app.resolve_code_object("project", "image", first.canonical_object_id)
    assert old.frozen_object_id == current.frozen_object_id == first.canonical_object_id
    assert old.alias_registration_hash == first.content_hash
    assert calls[-1] == "authorize"


def test_history_uses_exact_frozen_id_without_changing_old_membership():
    first = alias()
    app, payload, _ = application(((first, first.legacy_object_id),))
    result = app.resolve_code_object("project", "image", first.canonical_object_id)
    assert result.frozen_object_id == first.legacy_object_id
    assert payload["members"][0]["object_id"] == first.legacy_object_id


def test_nonmember_endpoint_mismatch_and_ambiguous_aliases_are_rejected():
    first = alias()
    second = alias(entity_id="071d553d-40f3-45c8-b8b9-8d67398c722d", entity_revision_id="entity-other")
    app, payload, _ = application(((first, first.canonical_object_id), (second, second.canonical_object_id)))
    with pytest.raises(AmbiguousCodeObjectAlias):
        app.resolve_code_object("project", "image", first.legacy_object_id)
    payload["objects"][1]["code_reference"]["source_revision_id"] = "foreign-source"
    with pytest.raises(ImageRevisionIntegrityError):
        app.resolve_code_object("project", "image", first.legacy_object_id)


def test_permissions_are_rechecked_after_alias_lookup():
    first = alias()
    app, _, _ = application(((first, first.canonical_object_id),))
    app.authorization.require_current = lambda *_: (_ for _ in ()).throw(SourceAccessDenied("revoked"))
    with pytest.raises(SourceAccessDenied):
        app.resolve_code_object("project", "image", first.legacy_object_id)


def test_canonical_receipt_replay_pins_registration_and_checks_the_whole_result():
    first = alias()
    result = FrozenCodeObjectIdentity("project", "image", "sha256:" + "c" * 64, first.legacy_object_id,
        first.canonical_object_id, first.canonical_object_id, ENTITY, "entity-v1", "source-v1", first.content_hash)
    pins = []
    def resolve(**kwargs):
        pins.append(kwargs.get("registration_hash"))
        return result
    tools = ImageQueryToolApplicationService(SimpleNamespace(resolve_code_object=resolve))
    receipt = tools.execute(ImageCodeIdentityInput(project_id="project", image_revision_id="image", object_id=first.legacy_object_id))
    assert isinstance(receipt, ImageCodeIdentityReceipt)
    assert tools.expand(receipt) == result and pins == [None, first.content_hash]
    assert "provider-node" not in receipt.model_dump_json()
    with pytest.raises(ImageRevisionIntegrityError):
        tools.expand(receipt.model_copy(update={"source_revision_id": "source-v2"}))
