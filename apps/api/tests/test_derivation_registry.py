from dataclasses import asdict, dataclass, replace

import pytest

from apps.api.app.domain.system_image.derivation_registry import DerivationRegistration, FrozenQueryScope, REGISTRY_POLICY
from apps.api.app.domain.system_image.derivation_impact import DerivationNode, DerivationImpactIntegrityError
from apps.api.app.domain.system_image.source_snapshots import SourceManifestMember, snapshot_digest


H = "sha256:" + "a" * 64


def scope():
    return FrozenQueryScope("project", "context", "image", H, "manifest", H, H,
        (SourceManifestMember("code", "code", "source", "captured"),
         SourceManifestMember("missing-tests", "test_asset", None, "pending")))


def test_complete_query_scope_records_negative_and_pending_sources_with_compatible_fingerprint():
    value = scope()
    assert value.fingerprint == snapshot_digest({"input_digest": H, "image_artifact_hash": H,
        "source_members": [asdict(member) for member in value.source_members]})
    assert value.source_members_hash == snapshot_digest([asdict(member) for member in value.source_members])
    assert replace(value, source_members=value.source_members[:1]).fingerprint != value.fingerprint
    assert replace(value, input_digest="sha256:" + "b" * 64).fingerprint != value.fingerprint


@pytest.mark.parametrize("changes", [
    {"project_id": ""}, {"input_digest": "bad"}, {"manifest_hash": True},
    {"source_members": ()}, {"source_members": list(scope().source_members)},
    {"source_members": tuple(reversed(scope().source_members))},
    {"source_members": (scope().source_members[0],) * 2},
    {"source_members": (SourceManifestMember("binding", "code", None, "captured"),)},
    {"source_members": (SourceManifestMember("binding", "test_asset", "source", "failed"),)},
    {"source_members": (SourceManifestMember("binding", "unknown", "source", "captured"),)},
])
def test_invalid_scope_membership_is_rejected_not_repaired(changes):
    with pytest.raises(DerivationImpactIntegrityError):
        replace(scope(), **changes)


@pytest.mark.parametrize("kind,ident,parents", [
    ("context", "context", ()), ("scope", "s", ("context:context",)),
    ("scope", "s", ("context:context", "scope:previous")),
    ("generation", "g", ("scope:s",)), ("case", "g/c", ("generation:g",)),
    ("coverage", "g", ("generation:g",)), ("mapping", "m", ("generation:g",)),
    ("mapping", "m", ("generation:g", "mapping:previous")),
])
def test_registration_hash_pins_project_context_invocation_and_parent_set(kind, ident, parents):
    value = DerivationRegistration("project", "context", "command", DerivationNode(kind, ident, H, parents))
    assert value.content_hash.startswith("sha256:")
    assert replace(value, invocation_id="another-command").content_hash != value.content_hash
    assert replace(value, project_id="another-project").content_hash != value.content_hash


@pytest.mark.parametrize("kind,ident,parents", [
    ("context", "another-context", ()), ("scope", "s", ("context:other",)),
    ("generation", "g", ("context:context",)), ("case", "g/c", ("scope:s",)),
    ("mapping", "m", ("generation:g", "mapping:m")),
    ("coverage", "g", ()), ("scope", "s", ("context:context", "scope:s")),
])
def test_wrong_parent_types_and_self_dependencies_fail_closed(kind, ident, parents):
    with pytest.raises(DerivationImpactIntegrityError):
        DerivationRegistration("project", "context", "command", DerivationNode(kind, ident, H, parents))


def test_registry_does_not_reuse_128_node_impact_limit_or_grant_authority():
    nodes = tuple(DerivationRegistration("project", "context", "command",
        DerivationNode("case", "generation/case-" + str(i), H, ("generation:g",))) for i in range(540))
    assert len(nodes) == 540 and len({node.node.key for node in nodes}) == 540
    assert not {"impact_complete", "generation_authorized", "execution_authorized", "accepted"} & set(asdict(nodes[0]))


@pytest.mark.parametrize("kind,ident,parents", [
    ("context", "context", ()), ("scope", "s", ("context:context",)),
    ("scope", "s", ("context:context", "scope:previous")),
    ("generation", "g", ("scope:s",)), ("case", "g/c", ("generation:g",)),
    ("coverage", "g", ("generation:g",)), ("mapping", "m", ("generation:g",)),
    ("mapping", "m", ("generation:g", "mapping:previous")),
    ("case", "g/\u4e2d\u6587-\U0001f986-\"-\\", ("generation:g",)),
])
def test_v1_registration_digest_keeps_original_bytes_after_new_dataclass_fields(kind, ident, parents):
    value = DerivationRegistration("project", "context", "command", DerivationNode(kind, ident, H, parents))
    original = snapshot_digest({"policy_revision": REGISTRY_POLICY, **asdict(value)})
    assert value.content_hash == original

    @dataclass(frozen=True)
    class FutureNode(DerivationNode):
        future_metadata: str = "not a v1 node field"

    @dataclass(frozen=True)
    class FutureRegistration(DerivationRegistration):
        future_metadata: str = "not a v1 registration field"

    extended = FutureRegistration(value.project_id, value.context_id, value.invocation_id, FutureNode(**asdict(value.node)))
    assert snapshot_digest({"policy_revision": REGISTRY_POLICY, **asdict(extended)}) != original
    assert extended.content_hash == original


def test_v1_source_scope_digest_does_not_adopt_future_source_member_fields():
    value = scope()
    original_members_hash, original_fingerprint = value.source_members_hash, value.fingerprint

    @dataclass(frozen=True)
    class FutureMember(SourceManifestMember):
        future_metadata: str = "not a v1 source member field"

    extended = replace(value, source_members=tuple(FutureMember(**asdict(member)) for member in value.source_members))
    assert snapshot_digest([asdict(member) for member in extended.source_members]) != original_members_hash
    assert extended.source_members_hash == original_members_hash
    assert extended.fingerprint == original_fingerprint


@pytest.mark.parametrize("changes", [
    {"binding_id": "a-new-binding"}, {"source_type": "test_asset"}, {"source_revision_id": "new-source"},
    {"source_revision_id": None, "status": "failed"},
])
def test_all_v1_source_member_fields_still_change_scope_hash_and_fingerprint(changes):
    value = scope()
    changed = replace(value, source_members=(replace(value.source_members[0], **changes), value.source_members[1]))
    assert changed.source_members_hash != value.source_members_hash
    assert changed.fingerprint != value.fingerprint


@pytest.mark.parametrize("field,changed", [
    ("kind", "coverage"), ("artifact_id", "g/another-case"), ("artifact_hash", "sha256:" + "b" * 64),
    ("dependencies", ("generation:another",)),
])
def test_every_v1_node_field_remains_part_of_the_registration_digest(field, changed):
    value = DerivationRegistration("project", "context", "command", DerivationNode("case", "g/c", H, ("generation:g",)))
    altered = replace(value, node=replace(value.node, **{field: changed}))
    assert altered.content_hash != value.content_hash
    assert altered.content_hash == snapshot_digest({"policy_revision": REGISTRY_POLICY, **asdict(altered)})


def test_v1_context_identity_is_not_dropped_from_registration_digest():
    value = DerivationRegistration("project", "context", "command", DerivationNode("case", "g/c", H, ("generation:g",)))
    assert replace(value, context_id="another-context").content_hash != value.content_hash
